import os
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands


print("PremiereBot code version: 1.0")


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_WEB_URL = "https://www.themoviedb.org"


if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

if not TMDB_API_KEY:
    raise RuntimeError("TMDB_API_KEY is missing.")

if not DISCORD_GUILD_ID:
    raise RuntimeError("DISCORD_GUILD_ID is missing.")


TEST_GUILD = discord.Object(
    id=int(DISCORD_GUILD_ID)
)


class PremiereClient(discord.Client):

    def __init__(self):
        intents = discord.Intents.default()

        super().__init__(
            intents=intents
        )

        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):

        print("PremiereBot setup_hook started.")

        # Copy our commands into the Wodies server
        # so they appear immediately while testing.
        self.tree.copy_global_to(
            guild=TEST_GUILD
        )

        synced = await self.tree.sync(
            guild=TEST_GUILD
        )

        print(
            f"Synced {len(synced)} guild command(s)."
        )

        for command in synced:
            print(
                f"Synced: /{command.name}"
            )

    async def on_ready(self):

        print(
            f"PremiereBot online as {self.user}"
        )


client = PremiereClient()


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

    timeout = aiohttp.ClientTimeout(
        total=15
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.get(
            f"{TMDB_BASE_URL}/{endpoint}",
            params=params
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

            # TMDb:
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


        # Prevent old or bad TMDb dates
        # from slipping into our results.
        if (
            today
            <= item_date
            <= end_date
        ):
            results.append(item)


    return results


@client.tree.command(
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
    timeframe: app_commands.Choice[str]
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

        print(
            f"TMDb error: {error}"
        )

        await interaction.followup.send(
            "PremiereBot couldn't retrieve "
            "release information from TMDb "
            "right now."
        )

        return


    if not results:

        await interaction.followup.send(
            f"No upcoming "
            f"{media_label.lower()} "
            f"were found for the "
            f"{time_label.lower()}."
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


        if media_value == "movie":

            date_string = item.get(
                "release_date"
            )

            media_path = "movie"

        else:

            date_string = item.get(
                "first_air_date"
            )

            media_path = "tv"


        tmdb_id = item.get("id")


        if tmdb_id:

            title_display = (
                f"[{title}]"
                f"({TMDB_WEB_URL}/"
                f"{media_path}/"
                f"{tmdb_id})"
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

            value += (
                f"\n{overview}"
            )


        embed.add_field(
            name=title_display,
            value=value,
            inline=False
        )


    if len(results) > 10:

        footer_text = (
            f"Showing 10 of "
            f"{len(results)} results "
            f"• Data provided by TMDb"
        )

    else:

        footer_text = (
            "Data provided by TMDb"
        )


    embed.set_footer(
        text=footer_text
    )


    await interaction.followup.send(
        embed=embed
    )


client.run(DISCORD_TOKEN)
