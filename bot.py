import os
import re
import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands


print("PremiereBot code version: 5.2")


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_WEB_URL = "https://www.themoviedb.org"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w780"
TMDB_THUMBNAIL_URL = "https://image.tmdb.org/t/p/w342"


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


async def get_details(
    media_type: str,
    tmdb_id: int
) -> dict:

    return await fetch_tmdb(
        f"{media_type}/{tmdb_id}",
        {
            "append_to_response":
                "credits,watch/providers"
        }
    )


def format_runtime(
    details: dict,
    media_type: str
) -> str:

    runtime = None

    if media_type == "movie":

        runtime = details.get(
            "runtime"
        )

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


def format_genres(
    details: dict
) -> str:

    genres = [
        genre.get("name")
        for genre in details.get(
            "genres",
            []
        )
        if genre.get("name")
    ]

    if not genres:
        return "Genre unavailable"

    return " • ".join(
        genres[:3]
    )


def format_cast(
    details: dict
) -> str:

    credits = (
        details.get("credits")
        or {}
    )

    cast = (
        credits.get("cast")
        or []
    )

    names = []

    for actor in cast:

        name = actor.get("name")

        if name:
            names.append(name)

        if len(names) == 3:
            break

    if not names:
        return "Cast unavailable"

    return " • ".join(names)


def get_us_watch_data(
    details: dict
) -> dict:

    watch_data = (
        details.get("watch/providers")
        or {}
    )

    results = (
        watch_data.get("results")
        or {}
    )

    return (
        results.get("US")
        or {}
    )


def get_us_provider_names(
    details: dict
) -> list[str]:

    us_data = get_us_watch_data(
        details
    )

    names = []

    categories = [
        "flatrate",
        "free",
        "ads",
        "rent",
        "buy",
    ]

    for category in categories:

        providers = (
            us_data.get(category)
            or []
        )

        for provider in providers:

            name = provider.get(
                "provider_name"
            )

            if (
                name
                and name not in names
            ):
                names.append(name)

    return names


def format_tv_availability(
    details: dict
) -> str | None:

    names = []

    for network in (
        details.get("networks")
        or []
    ):

        name = network.get("name")

        if (
            name
            and name not in names
        ):
            names.append(name)

    for name in get_us_provider_names(
        details
    ):

        if name not in names:
            names.append(name)

    if not names:
        return None

    return " • ".join(
        names[:5]
    )


def format_search_availability(
    details: dict
) -> str | None:

    names = get_us_provider_names(
        details
    )

    if not names:
        return None

    return " • ".join(
        names[:6]
    )


def parse_tmdb_date(
    date_string: str
) -> datetime:

    return datetime.strptime(
        date_string,
        "%Y-%m-%d"
    ).replace(
        hour=12,
        tzinfo=timezone.utc
    )


def format_release_date(
    date_string: str
) -> str:

    if not date_string:
        return "Date unavailable"

    release_date = parse_tmdb_date(
        date_string
    )

    unix_time = int(
        release_date.timestamp()
    )

    return f"<t:{unix_time}:D>"


def format_countdown(
    date_string: str
) -> str:

    release_date = parse_tmdb_date(
        date_string
    )

    now = datetime.now(
        timezone.utc
    )

    remaining = (
        release_date - now
    )

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


def format_exact_countdown(
    date_string: str
) -> str:

    release_date = parse_tmdb_date(
        date_string
    )

    now = datetime.now(
        timezone.utc
    )

    remaining = (
        release_date - now
    )

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

    minutes, seconds = divmod(
        remainder,
        60
    )

    return (
        f"{days}d "
        f"{hours}h "
        f"{minutes}m "
        f"{seconds}s"
    )


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


def normalize_title(
    text: str
) -> str:

    text = text.lower().strip()

    text = re.sub(
        r"[^a-z0-9\s]",
        "",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def search_relevance(
    item: dict,
    query: str
) -> tuple:

    query_norm = normalize_title(
        query
    )

    title = (
        item.get("title")
        or item.get("name")
        or ""
    )

    original_title = (
        item.get("original_title")
        or item.get("original_name")
        or ""
    )

    title_norm = normalize_title(
        title
    )

    original_norm = normalize_title(
        original_title
    )

    titles = [
        title_norm,
        original_norm
    ]

    exact = any(
        candidate == query_norm
        for candidate in titles
    )

    extension = any(
        candidate.startswith(
            query_norm + " "
        )
        for candidate in titles
    )

    contains_phrase = any(
        query_norm in candidate
        for candidate in titles
    )

    vote_count = int(
        item.get("vote_count")
        or 0
    )

    popularity = float(
        item.get("popularity")
        or 0
    )

    if exact:
        match_rank = 0

    elif extension:
        match_rank = 1

    elif contains_phrase:
        match_rank = 2

    else:
        match_rank = 3

    return (
        match_rank,
        -vote_count,
        -popularity
    )


async def get_movie_collection_parts(
    movie_item: dict
) -> list[dict]:

    tmdb_id = movie_item.get("id")

    if not tmdb_id:
        return []

    details = await fetch_tmdb(
        f"movie/{tmdb_id}"
    )

    collection = details.get(
        "belongs_to_collection"
    )

    if not collection:
        return []

    collection_id = collection.get(
        "id"
    )

    if not collection_id:
        return []

    data = await fetch_tmdb(
        f"collection/{collection_id}"
    )

    parts = []

    for item in data.get(
        "parts",
        []
    ):

        item["_media_type"] = "movie"
        item["_from_collection"] = True

        parts.append(item)

    parts.sort(
        key=lambda item:
            item.get("release_date")
            or "9999-12-31"
    )

    return parts


async def get_us_movie_release_date(
    movie_id: int
) -> str | None:

    data = await fetch_tmdb(
        f"movie/{movie_id}/release_dates"
    )

    theatrical_dates = []

    for country in data.get(
        "results",
        []
    ):

        if (
            country.get(
                "iso_3166_1"
            ) != "US"
        ):
            continue

        for release in country.get(
            "release_dates",
            []
        ):

            release_type = release.get(
                "type"
            )

            if release_type not in (
                3,
                2
            ):
                continue

            raw_date = release.get(
                "release_date"
            )

            if not raw_date:
                continue

            try:

                parsed = (
                    datetime.fromisoformat(
                        raw_date.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                )

            except ValueError:
                continue

            theatrical_dates.append(
                (
                    release_type,
                    parsed
                )
            )

    if not theatrical_dates:
        return None


    today = datetime.now(
        timezone.utc
    ).date()


    future_dates = [
        entry
        for entry in theatrical_dates
        if entry[1].date() >= today
    ]


    if future_dates:

        future_dates.sort(
            key=lambda entry: (
                entry[1].date(),
                0 if entry[0] == 3 else 1
            )
        )

        return (
            future_dates[0][1]
            .date()
            .isoformat()
        )


    theatrical_dates.sort(
        key=lambda entry: (
            entry[1].date(),
            0 if entry[0] == 3 else 1
        )
    )

    return (
        theatrical_dates[0][1]
        .date()
        .isoformat()
    )


async def verify_us_movie_release(
    item: dict,
    start_date,
    end_date
) -> dict | None:

    tmdb_id = item.get("id")

    if not tmdb_id:
        return None

    data = await fetch_tmdb(
        f"movie/{tmdb_id}/release_dates"
    )

    us_entries = None

    for country in data.get(
        "results",
        []
    ):

        if (
            country.get(
                "iso_3166_1"
            )
            == "US"
        ):
            us_entries = country
            break

    if not us_entries:
        return None

    possible_dates = []

    for release in us_entries.get(
        "release_dates",
        []
    ):

        release_type = release.get(
            "type"
        )

        if release_type not in (3, 2):
            continue

        raw_date = release.get(
            "release_date"
        )

        if not raw_date:
            continue

        try:

            release_date = (
                datetime.fromisoformat(
                    raw_date.replace(
                        "Z",
                        "+00:00"
                    )
                ).date()
            )

        except ValueError:
            continue

        if (
            start_date
            <= release_date
            <= end_date
        ):
            possible_dates.append(
                (
                    release_type,
                    release_date
                )
            )

    if not possible_dates:
        return None

    possible_dates.sort(
        key=lambda entry: (
            0 if entry[0] == 3 else 1,
            entry[1]
        )
    )

    chosen_date = (
        possible_dates[0][1]
    )

    verified = dict(item)

    verified["release_date"] = (
        chosen_date.isoformat()
    )

    return verified


async def verify_us_tv_relevance(
    item: dict
) -> dict | None:

    tmdb_id = item.get("id")

    if not tmdb_id:
        return None

    details = await get_details(
        "tv",
        tmdb_id
    )

    origin_countries = (
        details.get("origin_country")
        or item.get("origin_country")
        or []
    )

    is_us_origin = (
        "US" in origin_countries
    )

    us_providers = (
        get_us_provider_names(
            details
        )
    )

    if (
        not is_us_origin
        and not us_providers
    ):
        return None

    verified = dict(item)
    verified["_details"] = details

    return verified


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
        today
        + timedelta(days=days)
    )

    if media_type == "movie":

        endpoint = "discover/movie"
        date_field = "release_date"

        params = {
            "region": "US",
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

    candidates = []

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
            candidates.append(item)

    if media_type == "movie":

        checks = [
            verify_us_movie_release(
                item,
                today,
                end_date
            )
            for item in candidates
        ]

    else:

        checks = [
            verify_us_tv_relevance(
                item
            )
            for item in candidates
        ]

    checked_results = await asyncio.gather(
        *checks,
        return_exceptions=True
    )

    results = []

    for result in checked_results:

        if isinstance(
            result,
            Exception
        ):

            print(
                f"Filtering error: {result}"
            )

            continue

        if result is not None:
            results.append(result)

    results.sort(
        key=lambda item: (
            item.get(
                date_field,
                ""
            ),
            -float(
                item.get(
                    "popularity"
                )
                or 0
            )
        )
    )

    return results


async def build_upcoming_embed(
    item: dict,
    media_type: str
) -> discord.Embed:

    tmdb_id = item.get("id")

    details = item.get(
        "_details"
    )

    if not details:

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

        date_string = item.get(
            "release_date"
        )

        media_label = "MOVIE"

    else:

        title = (
            details.get("name")
            or item.get("name")
            or "Untitled"
        )

        date_string = item.get(
            "first_air_date"
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

    cast_text = format_cast(
        details
    )

    overview = (
        details.get("overview")
        or item.get("overview")
        or "No synopsis is currently available."
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

    if media_type == "movie":

        runtime_text = format_runtime(
            details,
            "movie"
        )

        metadata_lines = [
            f"🏷️ *{genre_text}*",
            f"🎭 **{cast_text}**",
            f"🕒 **{runtime_text}**",
        ]

    else:

        metadata_lines = [
            f"🏷️ *{genre_text}*",
            f"🎭 **{cast_text}**",
        ]

        availability = (
            format_tv_availability(
                details
            )
        )

        if availability:

            metadata_lines.append(
                f"📺 **{availability}**"
            )

    metadata = "\n".join(
        metadata_lines
    )

    description = (
        f"{metadata}\n\n"
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

    if (
        media_type == "tv"
        and get_us_provider_names(
            details
        )
    ):

        embed.set_footer(
            text=(
                "Data provided by TMDb "
                "• Availability powered by JustWatch"
            )
        )

    else:

        embed.set_footer(
            text="Data provided by TMDb"
        )

    return embed


async def search_titles(
    name: str,
    media_type: str | None
) -> list[dict]:

    results = []

    if media_type == "movie":

        data = await fetch_tmdb(
            "search/movie",
            {
                "query": name,
                "include_adult": "false",
            }
        )

        for item in data.get(
            "results",
            []
        ):

            item["_media_type"] = "movie"
            results.append(item)

    elif media_type == "tv":

        data = await fetch_tmdb(
            "search/tv",
            {
                "query": name,
                "include_adult": "false",
            }
        )

        for item in data.get(
            "results",
            []
        ):

            item["_media_type"] = "tv"
            results.append(item)

    else:

        movie_data, tv_data = await asyncio.gather(

            fetch_tmdb(
                "search/movie",
                {
                    "query": name,
                    "include_adult": "false",
                }
            ),

            fetch_tmdb(
                "search/tv",
                {
                    "query": name,
                    "include_adult": "false",
                }
            )
        )

        for item in movie_data.get(
            "results",
            []
        ):

            item["_media_type"] = "movie"
            results.append(item)

        for item in tv_data.get(
            "results",
            []
        ):

            item["_media_type"] = "tv"
            results.append(item)


    query_norm = normalize_title(
        name
    )

    relevant = []

    for item in results:

        title = (
            item.get("title")
            or item.get("name")
            or ""
        )

        original_title = (
            item.get("original_title")
            or item.get("original_name")
            or ""
        )

        title_norm = normalize_title(
            title
        )

        original_norm = normalize_title(
            original_title
        )

        if (
            title_norm == query_norm
            or original_norm == query_norm
            or title_norm.startswith(
                query_norm + " "
            )
            or original_norm.startswith(
                query_norm + " "
            )
            or query_norm in title_norm
            or query_norm in original_norm
        ):

            relevant.append(item)


    relevant.sort(
        key=lambda item:
            search_relevance(
                item,
                name
            )
    )


    collection_results = []

    strongest_movie = next(
        (
            item
            for item in relevant
            if item.get(
                "_media_type"
            ) == "movie"
        ),
        None
    )


    if strongest_movie:

        try:

            collection_results = (
                await get_movie_collection_parts(
                    strongest_movie
                )
            )

        except Exception as error:

            print(
                f"Collection lookup error: {error}"
            )


    final_results = []
    seen = set()


    def add_unique(
        item: dict
    ):

        media = item.get(
            "_media_type"
        )

        item_id = item.get("id")

        key = (
            media,
            item_id
        )

        if (
            item_id is not None
            and key not in seen
        ):

            seen.add(key)

            final_results.append(
                item
            )


    if relevant:
        add_unique(
            relevant[0]
        )


    for item in collection_results:
        add_unique(item)


    for item in relevant:
        add_unique(item)


    return final_results[:10]


async def build_search_embed(
    item: dict
) -> discord.Embed:

    media_type = item.get(
        "_media_type"
    )

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
            details.get("release_date")
            or item.get("release_date")
        )

        media_label = "MOVIE"

    else:

        title = (
            details.get("name")
            or item.get("name")
            or "Untitled"
        )

        date_string = (
            details.get("first_air_date")
            or item.get("first_air_date")
        )

        media_label = "TV"


    year = ""

    if date_string:
        year = date_string[:4]


    display_title = (
        f"{title} ({year})"
        if year
        else title
    )


    page_url = (
        f"{TMDB_WEB_URL}/"
        f"{media_type}/"
        f"{tmdb_id}"
    )


    genre_text = format_genres(
        details
    )

    cast_text = format_cast(
        details
    )

    runtime_text = format_runtime(
        details,
        media_type
    )

    availability = (
        format_search_availability(
            details
        )
    )


    overview = (
        details.get("overview")
        or item.get("overview")
        or "No synopsis is currently available."
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


    metadata_lines = [
        f"🏷️ *{genre_text}*",
        f"🎭 **{cast_text}**",
        f"🕒 **{runtime_text}**",
    ]


    if availability:

        metadata_lines.append(
            f"📺 **{availability}**"
        )


    metadata = "\n".join(
        metadata_lines
    )


    description = (
        f"{metadata}\n\n"
        f"{overview}\n\n"
        f"📅 **{format_release_date(date_string)}**\n"
        f"{score_meter(rating, vote_count)}"
    )


    embed = discord.Embed(
        title=display_title,
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


    if availability:

        embed.set_footer(
            text=(
                "Data provided by TMDb "
                "• Availability powered by JustWatch"
            )
        )

    else:

        embed.set_footer(
            text="Data provided by TMDb"
        )


    return embed


async def get_future_countdown_item(
    results: list[dict]
) -> tuple[dict, str] | None:

    today = datetime.now(
        timezone.utc
    ).date()


    for item in results:

        media_type = item.get(
            "_media_type"
        )

        tmdb_id = item.get(
            "id"
        )

        if not tmdb_id:
            continue


        try:

            details = await get_details(
                media_type,
                tmdb_id
            )


            if media_type == "movie":

                # This is the critical fix:
                # first check the movie's
                # ORIGINAL TMDb release date.
                original_date_string = (
                    details.get(
                        "release_date"
                    )
                    or item.get(
                        "release_date"
                    )
                )

                if not original_date_string:
                    continue


                original_release_date = (
                    datetime.strptime(
                        original_date_string,
                        "%Y-%m-%d"
                    ).date()
                )


                # If the movie already
                # originally released,
                # reject it completely.
                # Future re-releases do
                # NOT count.
                if (
                    original_release_date
                    < today
                ):
                    continue


                # Now that we know the movie
                # itself is genuinely unreleased,
                # prefer its U.S. theatrical date.
                date_string = (
                    await get_us_movie_release_date(
                        tmdb_id
                    )
                )


                if not date_string:
                    date_string = (
                        original_date_string
                    )


            else:

                date_string = (
                    details.get(
                        "first_air_date"
                    )
                    or item.get(
                        "first_air_date"
                    )
                )

                if not date_string:
                    continue


                first_air_date = (
                    datetime.strptime(
                        date_string,
                        "%Y-%m-%d"
                    ).date()
                )


                # Existing TV shows do not
                # qualify for /countdown.
                if first_air_date < today:
                    continue


            countdown_date = (
                datetime.strptime(
                    date_string,
                    "%Y-%m-%d"
                ).date()
            )


            if countdown_date < today:
                continue


            return (
                item,
                date_string
            )


        except Exception as error:

            print(
                f"Countdown filter error: {error}"
            )

            continue


    return None


async def build_countdown_embed(
    item: dict,
    date_string: str
) -> discord.Embed:

    media_type = item.get(
        "_media_type"
    )

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

        media_label = "MOVIE"


    else:

        title = (
            details.get("name")
            or item.get("name")
            or "Untitled"
        )

        media_label = "TV"


    page_url = (
        f"{TMDB_WEB_URL}/"
        f"{media_type}/"
        f"{tmdb_id}"
    )


    description = (
        f"📅 **{format_release_date(date_string)}**\n"
        f"⏳ **{format_exact_countdown(date_string)}**"
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
            f"{media_label} COUNTDOWN"
        )
    )


    poster_path = (
        details.get("poster_path")
        or item.get("poster_path")
    )


    if poster_path:

        embed.set_thumbnail(
            url=(
                f"{TMDB_THUMBNAIL_URL}"
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
        self.total_pages = len(
            results
        )

        self.update_buttons()


    def update_buttons(
        self
    ):

        has_multiple_pages = (
            self.total_pages > 1
        )

        self.previous_button.disabled = (
            not has_multiple_pages
        )

        self.next_button.disabled = (
            not has_multiple_pages
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

        return await build_upcoming_embed(
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

        self.page = (
            self.page - 1
        ) % self.total_pages

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

        self.page = (
            self.page + 1
        ) % self.total_pages

        self.update_buttons()

        embed = await self.get_current_embed()

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


class SearchBrowser(
    discord.ui.View
):

    def __init__(
        self,
        results: list[dict],
        requester_id: int
    ):

        super().__init__(
            timeout=300
        )

        self.results = results
        self.requester_id = requester_id

        self.page = 0
        self.total_pages = len(
            results
        )

        self.update_buttons()


    def update_buttons(
        self
    ):

        has_multiple_pages = (
            self.total_pages > 1
        )

        self.previous_button.disabled = (
            not has_multiple_pages
        )

        self.next_button.disabled = (
            not has_multiple_pages
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
                "Run `/search` to open "
                "your own PremiereBot search.",
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

        return await build_search_embed(
            item
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

        self.page = (
            self.page - 1
        ) % self.total_pages

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

        self.page = (
            self.page + 1
        ) % self.total_pages

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


@client.tree.command(
    name="search",
    description="Search for a movie or TV show."
)
@app_commands.describe(
    name="Title to search for.",
    media_type="Optionally limit the search to movies or TV."
)
@app_commands.rename(
    media_type="type"
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
    ]
)
async def search(
    interaction: discord.Interaction,
    name: str,
    media_type: app_commands.Choice[str] | None = None
):

    await interaction.response.defer()

    selected_type = (
        media_type.value
        if media_type
        else None
    )

    try:

        results = await search_titles(
            name,
            selected_type
        )

    except Exception as error:

        print(
            f"Search error: {error}"
        )

        await interaction.followup.send(
            "PremiereBot couldn't complete "
            "that search right now."
        )

        return

    if not results:

        await interaction.followup.send(
            f"No relevant results found for **{name}**."
        )

        return

    view = SearchBrowser(
        results=results,
        requester_id=interaction.user.id
    )

    try:

        embed = await view.get_current_embed()

    except Exception as error:

        print(
            f"Search detail error: {error}"
        )

        await interaction.followup.send(
            "PremiereBot found a result, "
            "but couldn't load its details."
        )

        return

    await interaction.followup.send(
        embed=embed,
        view=view
    )


@client.tree.command(
    name="countdown",
    description="Countdown to an upcoming movie or TV premiere."
)
@app_commands.describe(
    title="Upcoming movie or TV title.",
    media_type="Optionally limit the search to movies or TV."
)
@app_commands.rename(
    media_type="type"
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
    ]
)
async def countdown(
    interaction: discord.Interaction,
    title: str,
    media_type: app_commands.Choice[str] | None = None
):

    await interaction.response.defer()

    selected_type = (
        media_type.value
        if media_type
        else None
    )

    try:

        results = await search_titles(
            title,
            selected_type
        )

    except Exception as error:

        print(
            f"Countdown search error: {error}"
        )

        await interaction.followup.send(
            "PremiereBot couldn't search "
            "for that title right now."
        )

        return


    if not results:

        await interaction.followup.send(
            f"No relevant upcoming title "
            f"was found for **{title}**."
        )

        return


    future_match = (
        await get_future_countdown_item(
            results
        )
    )


    if not future_match:

        await interaction.followup.send(
            f"No unreleased movie or TV show "
            f"matching **{title}** was found."
        )

        return


    result, date_string = future_match


    try:

        embed = await build_countdown_embed(
            result,
            date_string
        )

    except Exception as error:

        print(
            f"Countdown detail error: {error}"
        )

        await interaction.followup.send(
            "PremiereBot found an upcoming title, "
            "but couldn't load its countdown."
        )

        return


    await interaction.followup.send(
        embed=embed
    )


client.run(DISCORD_TOKEN)
