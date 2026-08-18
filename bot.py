import os
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands


print("PremiereBot code version: 2.0")


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_WEB_URL = "https://www.themoviedb.org"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w500"


if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

if not TMDB_API_KEY:
    raise RuntimeError("TMDB_API_KEY is missing.")

if not DISCORD_GUILD_ID:
    raise RuntimeError("DISCORD_GUILD_ID is missing.")


GUILD = discord.Object(
    id=int(DISCORD_GUILD_ID)
)


class PremiereClient(discord.Client):

    def __init__(self):
        super().__init__(
            intents=discord.Intents.default()
        )

        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):

        print("PremiereBot setup started.")

        self.tree.copy_global_to(
            guild=GUILD
        )

        synced = await self.tree.sync(
            guild=GUILD
        )

        print(
            f"Synced {len(synced)} guild command(s)."
        )

        for command in synced:
            print(f"Synced: /{command.name}")

    async def on_ready(self):

        print(
            f"PremiereBot online as {self.user}"
        )


client = PremiereClient()


async def fetch_tmdb(
    endpoint: str,
    params: dict | None = None
) -> dict:

    if params is None:
        params = {}

    params = {
        **params,
        "api_key": TMDB_API_KEY,
        "language": "en-US",
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


def discord_date(
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
        f"<t:{unix_time}:D>\n"
        f"⏳ <t:{unix_time}:R>"
    )


def score_meter(
    rating: float
) -> str:

    rating = max(
        0,
        min(float(rating), 10)
    )

    filled = round(rating)
    empty = 10 - filled

    bar = (
        "▰" * filled
        + "▱" * empty
    )

    return (
        f"⭐ **{rating:.1f}/10**\n"
        f"`{bar}`"
    )


async def get_genres(
    media_type: str
) -> dict:

    data = await fetch_tmdb(
        f"genre/{media_type}/list"
    )

    return {
        genre["id"]: genre["name"]
        for genre in data.get(
            "genres",
            []
        )
    }


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

            "with_release_type":
                "2|3",

            "release_date.gte":
                today.isoformat(),

            "release_date.lte":
                end_date.isoformat(),

            "sort_by":
                "release_date.asc",

            "include_adult":
                "false",
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


def build_release_embed(
    item: dict,
    media_type: str,
    genres: dict
) -> discord.Embed:

    if media_type == "movie":

        title = item.get(
            "title",
            "Untitled"
        )

        date_string = item.get(
            "release_date"
        )

        media_label = "MOVIE"

    else:

        title = item.get(
            "name",
            "Untitled"
        )

        date_string = item.get(
            "first_air_date"
        )

        media_label = "TV PREMIERE"


    tmdb_id = item.get("id")

    page_url = (
        f"{TMDB_WEB_URL}/"
        f"{media_type}/"
        f"{tmdb_id}"
    )


    overview = (
        item.get("overview")
        or
        "No synopsis is currently available."
    ).strip()


    if len(overview) > 500:

        overview = (
            overview[:497].rstrip()
            + "..."
        )


    rating = float(
        item.get("vote_average")
        or 0
    )


    vote_count = int(
        item.get("vote_count")
        or 0
    )


    genre_names = [
        genres[genre_id]
        for genre_id
        in item.get(
            "genre_ids",
            []
        )
        if genre_id in genres
    ]


    if genre_names:

        genre_text = " • ".join(
            genre_names[:3]
        )

    else:

        genre_text = (
            "Genre unavailable"
        )


    embed = discord.Embed(
        title=title,
        url=page_url,
        description=overview,
        color=discord.Color.from_rgb(
            40,
            105,
            150
        )
    )


    embed.add_field(
        name="📅 RELEASE",
        value=discord_date(
            date_string
        ),
        inline=True
    )


    if vote_count > 0:

        rating_text = (
            score_meter(rating)
            + f"\n*{vote_count:,} ratings*"
        )

    else:

        rating_text = (
            "⭐ **Not Rated Yet**\n"
            "`▱▱▱▱▱▱▱▱▱▱`"
        )


    embed.add_field(
        name="🍿 TMDb SCORE",
        value=rating_text,
        inline=True
    )


    embed.add_field(
        name="🎭 GENRES",
        value=genre_text,
        inline=False
    )


    poster_path = item.get(
        "poster_path"
    )


    if poster_path:

        embed.set_thumbnail(
            url=(
                f"{TMDB_IMAGE_URL}"
                f"{poster_path}"
            )
        )


    embed.set_author(
        name=(
            f"PREMIEREBOT  •  "
            f"{media_label}"
        )
    )


    embed.set_footer(
        text=(
            "Movie & TV data provided by TMDb"
        )
    )


    return embed


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


    try:

        results = await get_upcoming(
            media_value,
            time_value
        )

        genres = await get_genres(
            media_value
        )

    except Exception as error:

        print(
            f"TMDb error: {error}"
        )

        await interaction.followup.send(
            "PremiereBot couldn't retrieve "
            "release information right now."
        )

        return


    if not results:

        await interaction.followup.send(
            "No releases were found "
            "for that period."
        )

        return


    period = (
        "NEXT 7 DAYS"
        if time_value == "week"
        else "NEXT 30 DAYS"
    )


    media_heading = (
        "MOVIE RELEASES"
        if media_value == "movie"
        else "TV PREMIERES"
    )


    header = discord.Embed(
        title=f"🎬 {media_heading}",
        description=(
            f"**{period}**\n"
            f"Showing the next "
            f"{min(5, len(results))} releases."
        ),
        color=discord.Color.from_rgb(
            40,
            105,
            150
        )
    )


    embeds = [header]


    for item in results[:5]:

        embeds.append(
            build_release_embed(
                item,
                media_value,
                genres
            )
        )


    await interaction.followup.send(
        embeds=embeds
    )


client.run(DISCORD_TOKEN)
