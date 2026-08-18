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


class PremiereBot(commands.Bot):
    async def setup_hook(self):
        synced = await self.tree.sync()

        print(
            f"Synced {len(synced)} command(s) with Discord."
        )

        for command in synced:
            print(
                f"Synced command: /{command.name}"
            )


intents = discord.Intents.default()

bot = PremiereBot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print(
        f"PremiereBot is online as {bot.user}"
    )


async def fetch_tmdb(
    endpoint: str,
    params: dict
) -> dict:

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
                    f"TMDb returned HTTP "
                    f"{response.status}: "
                    f"{body[:300]}"
                )

            return await response.json()


def make_discord_date(
    date_string: str
) -> str:

    release_date = datetime.strptime(
        date_string,
        "%Y-%m-%d"
    ).replace(
        hour=12,
        tzinfo=timezone.utc
    )

    unix_time = int(
        release_date.timestamp()
    )

    return (
        f"<t:{unix_time}:D> • "
        f"<t:{unix_time}:R>"
    )


async def get_upcoming(
    media_type: str,
    timeframe: str
) -> list[dict]:

    today = datetime.now(
        timezone.utc
    ).date()

    days = (
        7
        if timeframe == "week"
        else 30
    )

    end_date = (
        today + timedelta(days=days)
    )

    if media_type == "movie":

        endpoint = "discover/movie"
        date_field = "release_date"

        params = {
            "region": "US",

            # 2 = Limited Theatrical
            # 3 = Theatrical
            "with_release_type": "2|3",

            "release_date.gte":
                today.isoformat(),

            "release_date.lte":
                end_date.isoformat(),

            "sort_by":
                "release_date.asc",
        }

    else:

        endpoint = "discover/tv"
        date_field = "first_air_date"

        params = {
            "first_air_date.gte":
                today.isoformat(),

            "first_air_date.lte":
                end_date.isoformat(),

            "sort_by":
                "first_air_date.asc",

            "include_null_first_air_dates":
                "false",
        }

    data = await fetch_tmdb(
        endpoint,
        params
    )

    results = []

    for item in data.get(
        "results",
        []
    ):

        date_string = item.get(
            date_field
        )

        if not date_string:
            continue

        try:
            item_date = datetime.strptime(
                date_string,
                "%Y-%m-%d"
            ).date()

        except ValueError:
            continue

        if (
            today
            <= item_date
            <= end_date
        ):
            results.append(item)

    return results


@bot.tree.command(
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
        if time_value ==
