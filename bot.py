import os
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands


print("PremiereBot code version: 3.1")


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_WEB_URL = "https://www.themoviedb.org"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w780"


if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

if not TMDB_API_KEY:
    raise RuntimeError("TMDB_API_KEY is missing.")

if not DISCORD_GUILD_ID:
    raise RuntimeError("DISCORD_GUILD_ID is missing.")


GUILD = discord.Object(id=int(DISCORD_GUILD_ID))


class PremiereClient(discord.Client):

    def __init__(self):
        super().__init__(
            intents=discord.Intents.default()
        )
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        print("PremiereBot setup started.")

        self.tree.copy_global_to(guild=GUILD)
        synced = await self.tree.sync(guild=GUILD)

        print(f"Synced {len(synced)} guild command(s).")

        for command in synced:
            print(f"Synced: /{command.name}")

    async def on_ready(self):
        print(f"PremiereBot online as {self.user}")


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

    timeout = aiohttp.ClientTimeout(total=15)

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


async def get_details(
    media_type: str,
    tmdb_id: int
) -> dict:

    return await fetch_tmdb(
        f"{media_type}/{tmdb_id}"
    )


def format_runtime(
    details: dict,
    media_type: str
) -> str:

    runtime = None

    if media_type == "movie":
        runtime = details.get("runtime")

    else:
        runtimes = (
            details.get("episode_run_time")
            or []
        )

        if runtimes:
            runtime = runtimes[0]

    if not runtime:
        return "Runtime unavailable"

    hours = runtime // 60
    minutes = runtime % 60

    if hours and minutes:
        return f"{hours}h {minutes}m"

    if hours:
        return f"{hours}h"

    return f"{minutes}m"


def format_genres(details: dict) -> str:

    genres = [
        genre.get("name")
        for genre in details.get("genres", [])
        if genre.get("name")
    ]

    if not genres:
        return "Genre unavailable"

    return " • ".join(genres[:3])


def format_release_date(
    date_string: str
) -> str:

    date = datetime.strptime(
        date_string,
        "%Y-%m-%d"
    ).replace(
        hour=12,
        tzinfo=timezone.utc
    )

    unix_time = int(date.timestamp())

    return f"<t:{unix_time}:D>"


def format_countdown(
    date_string: str
) -> str:

    release_date = datetime.strptime(
        date_string,
        "%Y-%m-%d"
    ).replace(
        hour=12,
        tzinfo=timezone.utc
    )

    now = datetime.now(timezone.utc)

    remaining = release_date - now

    total_seconds = int(
        remaining.total_seconds()
    )

    if total_seconds <= 0:
        return "Released"

    days, remainder = divmod(
        total_seconds,
        86400
    )

    hours, remainder = divmod(
        remainder,
        3600
    )

    minutes, _ = divmod(
        remainder,
        60
    )

    parts = []

    if days:
        parts.append(f"{days}d")

    if hours or days:
        parts.append(f"{hours}h")

    parts.append(f"{minutes}m")

    return " ".join(parts)


def score_meter(
    rating: float,
    vote_count: int
) -> str:

    if vote_count <= 0:
        return (
            "⭐️ **Not Rated Yet**\n"
            "`▱▱▱▱▱▱▱▱▱▱`"
        )

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
        f"⭐️ **{rating:.1f}/10**\n"
        f"`{bar}`"
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

            # U.S. theatrical releases
            # 3 = Theatrical
            # 2 = Limited Theatrical
            "with_release_type": "3|2",

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

            "include_adult":
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

    # Release date first.
    # More popular titles first
    # when dates are the same.
    results.sort(
        key=lambda item: (
            item.get(date_field, ""),
            -float(
                item.get("popularity")
                or 0
            )
        )
    )

    return results


async def build_release_embed(
    item: dict,
    media_type: str
) -> discord.Embed:

    tmdb_id = item.get("id")

    details = await get_details(
        media_type,
        tmdb_id
    )

    if media_type == "movie":

        title = (
            details.get("title")
            or item.get("title")
            or "Untitled"
        )

        date_string = (
            item.get("release_date")
        )

        media_label = "MOVIE"

    else:

        title = (
            details.get("name")
            or item.get("name")
            or "Untitled"
        )

        date_string = (
            item.get("first_air_date")
        )

        media_label = "TV"

    page_url = (
        f"{TMDB_WEB_URL}/"
        f"{media_type}/"
        f"{tmdb_id}"
    )

    genre_text = format_genres(
        details
    )

    runtime_text = format_runtime(
        details,
        media_type
    )

    overview = (
        details.get("overview")
        or item.get("overview")
        or
        "No synopsis is currently available."
    ).strip()

    if len(overview) > 650:
        overview = (
            overview[:647].rstrip()
            + "..."
        )

    rating = float(
        details.get("vote_average")
        or item.get("vote_average")
        or 0
    )

    vote_count = int(
        details.get("vote_count")
        or item.get("vote_count")
        or 0
    )

    description = (
        f"*{genre_text}*\n"
        f"🕒 **{runtime_text}**\n\n"
        f"{overview}\n\n"
        f"📅 **{format_release_date(date_string)}**\n"
        f"⏳ **{format_countdown(date_string)}**\n"
        f"{score_meter(rating, vote_count)}"
    )

    embed = discord.Embed(
        title=title,
        url=page_url,
        description=description,
        color=discord.Color.from_rgb(
            40,
            105,
            150
        )
    )

    embed.set_author(
        name=(
            f"PREMIEREBOT  •  "
            f"{media_label}"
        )
    )

    poster_path = (
        details.get("poster_path")
        or item.get("poster_path")
    )

    if poster_path:
        embed.set_image(
            url=(
                f"{TMDB_IMAGE_URL}"
                f"{poster_path}"
            )
        )

    embed.set_footer(
        text="Data provided by TMDb"
    )

    return embed


class ReleaseBrowser(
    discord.ui.View
):

    def __init__(
        self,
        results: list[dict],
        media_type: str,
        requester_id: int
    ):

        super().__init__(
            timeout=300
        )

        self.results = results
        self.media_type = media_type
        self.requester_id = requester_id

        self.page = 0
        self.total_pages = len(results)

        self.update_buttons()


    def update_buttons(self):

        self.previous_button.disabled = (
            self.page <= 0
        )

        self.next_button.disabled = (
            self.page
            >= self.total_pages - 1
        )

        self.page_button.label = (
            f"{self.page + 1} "
            f"/ {self.total_pages}"
        )


    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if (
            interaction.user.id
            != self.requester_id
        ):

            await interaction.response.send_message(
                "Run `/upcoming` to open "
                "your own PremiereBot browser.",
                ephemeral=True
            )

            return False

        return True


    async def get_current_embed(
        self
    ) -> discord.Embed:

        item = self.results[
            self.page
        ]

        return await build_release_embed(
            item,
            self.media_type
        )


    @discord.ui.button(
        label="Previous",
        emoji="◀️",
        style=discord.ButtonStyle.secondary
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if self.page > 0:
            self.page -= 1

        self.update_buttons()

        embed = await self.get_current_embed()

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


    @discord.ui.button(
        label="1 / 1",
        style=discord.ButtonStyle.secondary,
        disabled=True
    )
    async def page_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        pass


    @discord.ui.button(
        label="Next",
        emoji="▶️",
        style=discord.ButtonStyle.secondary
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if (
            self.page
            < self.total_pages - 1
        ):
            self.page += 1

        self.update_buttons()

        embed = await self.get_current_embed()

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


@client.tree.command(
    name="upcoming",
    description="Browse upcoming movie or TV releases."
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

    try:

        results = await get_upcoming(
            media_type.value,
            timeframe.value
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

    view = ReleaseBrowser(
        results=results,
        media_type=media_type.value,
        requester_id=interaction.user.id
    )

    try:

        embed = await view.get_current_embed()

    except Exception as error:

        print(
            f"TMDb detail error: {error}"
        )

        await interaction.followup.send(
            "PremiereBot found releases, "
            "but couldn't load their details."
        )

        return

    await interaction.followup.send(
        embed=embed,
        view=view
    )


client.run(DISCORD_TOKEN)
