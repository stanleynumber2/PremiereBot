import os
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_WEB_URL = "https://www.themoviedb.org"

intents = discord.Intents.default()


class PremiereBot(commands.Bot):
    async def setup_hook(self):
        await self.tree.sync()


bot = PremiereBot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print(f"PremiereBot is online as {bot.user}")


async def fetch_tmdb(endpoint: str, params: dict) -> dict:
    params = {
        **params,
        "api_key": TMDB_API_KEY,
        "language": "en-US",
        "include_adult": "false",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{TMDB_BASE_URL}/{endpoint}",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:

            if response.status != 200:
                body = await response.text()
                raise RuntimeError(
                    f"TMDb returned HTTP {response.status}: "
                    f"{body[:300]}"
                )

            return await response.json()


def make_discord_date(date_string: str) -> str:
    release_date = datetime.strptime(
        date_string,
        "%Y-%m-%d"
    ).replace(
        hour=12,
        tzinfo=timezone.utc
    )

    unix_time = int(release_date.timestamp())

    return f"<t:{unix_time}:D> • <t:{unix_time}:R>"


async def get_upcoming(
    media_type: str,
    timeframe: str
) -> list[dict]:

    today = datetime.now(timezone.utc).date()

    days = 7 if timeframe == "week" else 30

    end_date = today + timedelta(days=days)

    if media_type == "movie":
        endpoint = "discover/movie"
        date_field = "release_date"

        params = {
            "region": "US",

            # TMDb release types:
            # 2 = Limited Theatrical
            # 3 = Theatrical
            "with_release_type": "2|3",

            "release_date.gte": today.isoformat(),
            "release_date.lte": end_date.isoformat(),

            "sort_by": "release_date.asc",
        }

    else:
        endpoint = "discover/tv"
        date_field = "first_air_date"

        params = {
            "first_air_date.gte": today.isoformat(),
            "first_air_date.lte": end_date.isoformat(),

            "sort_by": "first_air_date.asc",

            "include_null_first_air_dates": "false",
        }

    data = await fetch_tmdb(
        endpoint,
        params
    )

    results = []

    for item in data.get("results", []):

        date_string = item.get(date_field)

        if not date_string:
            continue

        try:
            item_date = datetime.strptime(
                date_string,
                "%Y-%m-%d"
            ).date()

        except ValueError:
            continue

        # Extra safety check.
        if today <= item_date <= end_date:
            results.append(item)

    return results


@app_commands.command(
    name="upcoming",
    description="See upcoming movie or TV releases."
)
@app_commands.describe(
    media_type="Choose movies or TV.",
    timeframe="Choose week or month."
)
@app_commands.rename(
    media_type="type",
    timeframe="time"
)
@app_commands.choices(
    media_type=[
        app_commands.Choice(
            name="Movie",
            value="movie"
        ),
        app_commands.Choice(
            name="TV",
            value="tv"
        ),
    ],
    timeframe=[
        app_commands.Choice(
            name="Week",
            value="week"
        ),
        app_commands.Choice(
            name="Month",
            value="month"
        ),
    ],
)
async def upcoming(
    interaction: discord.Interaction,
    media_type: app_commands.Choice[str],
    timeframe: app_commands.Choice[str],
):

    await interaction.response.defer()

    media_value = media_type.value
    time_value = timeframe.value

    media_label = (
        "Movies"
        if media_value == "movie"
        else "TV Series"
    )

    time_label = (
        "Next 7 Days"
        if time_value == "week"
        else "Next 30 Days"
    )

    try:
        results = await get_upcoming(
            media_value,
            time_value
        )

    except Exception as error:
        print(f"TMDb error: {error}")

        await interaction.followup.send(
            "PremiereBot couldn't retrieve release "
            "information from TMDb right now."
        )

        return

    if not results:
        await interaction.followup.send(
            f"No upcoming {media_label.lower()} "
            f"were found for the {time_label.lower()}."
        )

        return

    embed = discord.Embed(
        title=f"🎬 Upcoming {media_label}",
        description=f"**{time_label}**"
    )

    for item in results[:10]:

        title = (
            item.get("title")
            or item.get("name")
            or "Untitled"
        )

        date_string = (
            item.get("release_date")
            if media_value == "movie"
            else item.get("first_air_date")
        )

        tmdb_id = item.get("id")

        media_path = (
            "movie"
            if media_value == "movie"
            else "tv"
        )

        if tmdb_id:
            title_display = (
                f"[{title}]"
                f"({TMDB_WEB_URL}/{media_path}/{tmdb_id})"
            )
        else:
            title_display = title

        overview = (
            item.get("overview")
            or ""
        ).strip()

        if len(overview) > 150:
            overview = (
                overview[:147].rstrip()
                + "..."
            )

        value = make_discord_date(
            date_string
        )

        if overview:
            value += f"\n{overview}"

        embed.add_field(
            name=title_display,
            value=value,
            inline=False
        )

    if len(results) > 10:
        footer_text = (
            f"Showing 10 of {len(results)} results "
            f"• Data provided by TMDb"
        )
    else:
        footer_text = "Data provided by TMDb"

    embed.set_footer(
        text=footer_text
    )

    await interaction.followup.send(
        embed=embed
    )


if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is missing."
    )

if not TMDB_API_KEY:
    raise RuntimeError(
        "TMDB_API_KEY is missing."
    )


bot.run(DISCORD_TOKEN)
