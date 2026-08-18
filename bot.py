import os
import re
import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands


print("ReleaseBot code version: 7.0")


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")
TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET")

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_WEB_URL = "https://www.themoviedb.org"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w780"
TMDB_THUMBNAIL_URL = "https://image.tmdb.org/t/p/w342"

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_BASE_URL = "https://api.igdb.com/v4"
IGDB_IMAGE_URL = "https://images.igdb.com/igdb/image/upload"


for name, value in (
    ("DISCORD_TOKEN", DISCORD_TOKEN),
    ("TMDB_API_KEY", TMDB_API_KEY),
    ("DISCORD_GUILD_ID", DISCORD_GUILD_ID),
    ("TWITCH_CLIENT_ID", TWITCH_CLIENT_ID),
    ("TWITCH_CLIENT_SECRET", TWITCH_CLIENT_SECRET),
):
    if not value:
        raise RuntimeError(f"{name} is missing.")


GUILD = discord.Object(id=int(DISCORD_GUILD_ID))


class ReleaseClient(discord.Client):

    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.igdb_token = None
        self.igdb_token_expires_at = datetime.min.replace(tzinfo=timezone.utc)
        self.igdb_token_lock = asyncio.Lock()

    async def setup_hook(self):
        print("ReleaseBot setup started.")
        self.tree.copy_global_to(guild=GUILD)
        synced = await self.tree.sync(guild=GUILD)
        print(f"Synced {len(synced)} guild command(s).")
        for command in synced:
            print(f"Synced: /{command.name}")

    async def on_ready(self):
        print(f"ReleaseBot online as {self.user}")


client = ReleaseClient()


# ============================================================
# TMDB ENGINE
# This section intentionally preserves the original PremiereBot
# movie/TV behavior as closely as possible.
# ============================================================

async def fetch_tmdb(endpoint: str, params: dict | None = None) -> dict:

    if params is None:
        params = {}

    params = {
        **params,
        "api_key": TMDB_API_KEY,
        "language": "en-US",
    }

    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            f"{TMDB_BASE_URL}/{endpoint}",
            params=params
        ) as response:

            if response.status != 200:
                body = await response.text()
                raise RuntimeError(
                    f"TMDb returned HTTP {response.status}: {body[:300]}"
                )

            return await response.json()


async def get_details(media_type: str, tmdb_id: int) -> dict:
    return await fetch_tmdb(
        f"{media_type}/{tmdb_id}",
        {"append_to_response": "credits,watch/providers"}
    )


def format_runtime(details: dict, media_type: str) -> str:

    runtime = None

    if media_type == "movie":
        runtime = details.get("runtime")
    else:
        runtimes = details.get("episode_run_time") or []
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

    return " / ".join(genres[:3])


def format_cast(details: dict) -> str:

    credits = details.get("credits") or {}
    cast = credits.get("cast") or []
    names = []

    for actor in cast:
        name = actor.get("name")
        if name:
            names.append(name)
        if len(names) == 3:
            break

    if not names:
        return "Cast unavailable"

    return " / ".join(names)


def get_us_watch_data(details: dict) -> dict:

    watch_data = details.get("watch/providers") or {}
    results = watch_data.get("results") or {}
    return results.get("US") or {}


def get_us_provider_names(details: dict) -> list[str]:

    us_data = get_us_watch_data(details)
    names = []

    for category in ("flatrate", "free", "ads", "rent", "buy"):
        providers = us_data.get(category) or []

        for provider in providers:
            name = provider.get("provider_name")

            if name and name not in names:
                names.append(name)

    return names


def format_tv_availability(details: dict) -> str | None:

    names = []

    for network in details.get("networks") or []:
        name = network.get("name")
        if name and name not in names:
            names.append(name)

    for name in get_us_provider_names(details):
        if name not in names:
            names.append(name)

    if not names:
        return None

    return " / ".join(names[:5])


def format_search_availability(details: dict) -> str | None:

    names = get_us_provider_names(details)

    if not names:
        return None

    return " / ".join(names[:6])


def parse_tmdb_date(date_string: str) -> datetime:
    return datetime.strptime(
        date_string,
        "%Y-%m-%d"
    ).replace(hour=12, tzinfo=timezone.utc)


def format_release_date(date_string: str) -> str:

    if not date_string:
        return "Date unavailable"

    release_date = parse_tmdb_date(date_string)
    unix_time = int(release_date.timestamp())
    return f"<t:{unix_time}:D>"


def format_countdown(date_string: str) -> str:

    release_date = parse_tmdb_date(date_string)
    now = datetime.now(timezone.utc)
    remaining = release_date - now
    total_seconds = int(remaining.total_seconds())

    if total_seconds <= 0:
        return "Released"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []

    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")

    parts.append(f"{minutes}m")

    return " ".join(parts)


def format_exact_countdown(date_string: str) -> str:

    release_date = parse_tmdb_date(date_string)
    now = datetime.now(timezone.utc)
    remaining = release_date - now
    total_seconds = int(remaining.total_seconds())

    if total_seconds <= 0:
        return "Released"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    return f"{days}d {hours}h {minutes}m {seconds}s"


def score_meter(rating: float, vote_count: int) -> str:

    if vote_count <= 0:
        return "â­ï¸ **Not Rated Yet**\n`â±â±â±â±â±â±â±â±â±â±`"

    rating = max(0, min(float(rating), 10))
    filled = round(rating)
    empty = 10 - filled
    bar = "â°" * filled + "â±" * empty

    return f"â­ï¸ **{rating:.1f}/10**\n`{bar}`"


def normalize_title(text: str) -> str:

    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def search_relevance(item: dict, query: str) -> tuple:

    query_norm = normalize_title(query)

    title = item.get("title") or item.get("name") or ""
    original_title = (
        item.get("original_title")
        or item.get("original_name")
        or ""
    )

    title_norm = normalize_title(title)
    original_norm = normalize_title(original_title)
    titles = [title_norm, original_norm]

    exact = any(candidate == query_norm for candidate in titles)
    extension = any(
        candidate.startswith(query_norm + " ")
        for candidate in titles
    )
    contains_phrase = any(
        query_norm in candidate
        for candidate in titles
    )

    vote_count = int(item.get("vote_count") or 0)
    popularity = float(item.get("popularity") or 0)

    if exact:
        match_rank = 0
    elif extension:
        match_rank = 1
    elif contains_phrase:
        match_rank = 2
    else:
        match_rank = 3

    return (match_rank, -vote_count, -popularity)


async def get_movie_collection_parts(movie_item: dict) -> list[dict]:

    tmdb_id = movie_item.get("id")

    if not tmdb_id:
        return []

    details = await fetch_tmdb(f"movie/{tmdb_id}")
    collection = details.get("belongs_to_collection")

    if not collection:
        return []

    collection_id = collection.get("id")

    if not collection_id:
        return []

    data = await fetch_tmdb(f"collection/{collection_id}")
    parts = []

    for item in data.get("parts", []):
        item["_media_type"] = "movie"
        item["_source"] = "tmdb"
        parts.append(item)

    parts.sort(
        key=lambda item:
            item.get("release_date") or "9999-12-31"
    )

    return parts


async def get_us_movie_release_date(movie_id: int) -> str | None:

    data = await fetch_tmdb(f"movie/{movie_id}/release_dates")
    theatrical_dates = []

    for country in data.get("results", []):

        if country.get("iso_3166_1") != "US":
            continue

        for release in country.get("release_dates", []):

            release_type = release.get("type")

            if release_type not in (3, 2):
                continue

            raw_date = release.get("release_date")

            if not raw_date:
                continue

            try:
                parsed = datetime.fromisoformat(
                    raw_date.replace("Z", "+00:00")
                )
            except ValueError:
                continue

            theatrical_dates.append((release_type, parsed))

    if not theatrical_dates:
        return None

    today = datetime.now(timezone.utc).date()

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
        return future_dates[0][1].date().isoformat()

    theatrical_dates.sort(
        key=lambda entry: (
            entry[1].date(),
            0 if entry[0] == 3 else 1
        )
    )

    return theatrical_dates[0][1].date().isoformat()


async def verify_us_movie_release(
    item: dict,
    start_date,
    end_date
) -> dict | None:

    tmdb_id = item.get("id")

    if not tmdb_id:
        return None

    data = await fetch_tmdb(f"movie/{tmdb_id}/release_dates")
    us_entries = None

    for country in data.get("results", []):
        if country.get("iso_3166_1") == "US":
            us_entries = country
            break

    if not us_entries:
        return None

    possible_dates = []

    for release in us_entries.get("release_dates", []):

        release_type = release.get("type")

        if release_type not in (3, 2):
            continue

        raw_date = release.get("release_date")

        if not raw_date:
            continue

        try:
            release_date = datetime.fromisoformat(
                raw_date.replace("Z", "+00:00")
            ).date()
        except ValueError:
            continue

        if start_date <= release_date <= end_date:
            possible_dates.append((release_type, release_date))

    if not possible_dates:
        return None

    possible_dates.sort(
        key=lambda entry: (
            0 if entry[0] == 3 else 1,
            entry[1]
        )
    )

    verified = dict(item)
    verified["release_date"] = possible_dates[0][1].isoformat()
    verified["_media_type"] = "movie"
    verified["_source"] = "tmdb"

    return verified


async def verify_us_tv_relevance(item: dict) -> dict | None:

    tmdb_id = item.get("id")

    if not tmdb_id:
        return None

    details = await get_details("tv", tmdb_id)

    origin_countries = (
        details.get("origin_country")
        or item.get("origin_country")
        or []
    )

    is_us_origin = "US" in origin_countries
    us_providers = get_us_provider_names(details)

    if not is_us_origin and not us_providers:
        return None

    verified = dict(item)
    verified["_details"] = details
    verified["_media_type"] = "tv"
    verified["_source"] = "tmdb"

    return verified


async def get_upcoming_tmdb(
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
            "with_release_type": "3|2",
            "release_date.gte": today.isoformat(),
            "release_date.lte": end_date.isoformat(),
            "sort_by": "release_date.asc",
            "include_adult": "false",
        }

    else:

        endpoint = "discover/tv"
        date_field = "first_air_date"

        params = {
            "first_air_date.gte": today.isoformat(),
            "first_air_date.lte": end_date.isoformat(),
            "sort_by": "first_air_date.asc",
            "include_null_first_air_dates": "false",
            "include_adult": "false",
        }

    data = await fetch_tmdb(endpoint, params)
    candidates = []

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

        if today <= item_date <= end_date:
            item["_media_type"] = media_type
            item["_source"] = "tmdb"
            candidates.append(item)

    if media_type == "movie":
        checks = [
            verify_us_movie_release(item, today, end_date)
            for item in candidates
        ]
    else:
        checks = [
            verify_us_tv_relevance(item)
            for item in candidates
        ]

    checked_results = await asyncio.gather(
        *checks,
        return_exceptions=True
    )

    results = []

    for result in checked_results:

        if isinstance(result, Exception):
            print(f"Filtering error: {result}")
            continue

        if result is not None:
            results.append(result)

    results.sort(
        key=lambda item: (
            item.get(date_field, ""),
            -float(item.get("popularity") or 0)
        )
    )

    return results


async def build_upcoming_tmdb_embed(
    item: dict,
    media_type: str
) -> discord.Embed:

    tmdb_id = item.get("id")
    details = item.get("_details")

    if not details:
        details = await get_details(media_type, tmdb_id)

    if media_type == "movie":
        title = (
            details.get("title")
            or item.get("title")
            or "Untitled"
        )
        date_string = item.get("release_date")
        media_label = "MOVIE"
    else:
        title = (
            details.get("name")
            or item.get("name")
            or "Untitled"
        )
        date_string = item.get("first_air_date")
        media_label = "SERIES"

    page_url = f"{TMDB_WEB_URL}/{media_type}/{tmdb_id}"
    genre_text = format_genres(details)
    cast_text = format_cast(details)

    overview = (
        details.get("overview")
        or item.get("overview")
        or "No synopsis is currently available."
    ).strip()

    if len(overview) > 650:
        overview = overview[:647].rstrip() + "..."

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
        runtime_text = format_runtime(details, "movie")
        metadata_lines = [
            f"ð·ï¸ *{genre_text}*",
            f"ð­ **{cast_text}**",
            f"ð **{runtime_text}**",
        ]
    else:
        metadata_lines = [
            f"ð·ï¸ *{genre_text}*",
            f"ð­ **{cast_text}**",
        ]

        availability = format_tv_availability(details)

        if availability:
            metadata_lines.append(
                f"ðº **{availability}**"
            )

    metadata = "\n".join(metadata_lines)

    description = (
        f"{metadata}\n\n"
        f"{overview}\n\n"
        f"ð **{format_release_date(date_string)}**\n"
        f"â³ **{format_countdown(date_string)}**\n"
        f"{score_meter(rating, vote_count)}"
    )

    embed = discord.Embed(
        title=title,
        url=page_url,
        description=description,
        color=discord.Color.from_rgb(40, 105, 150)
    )

    embed.set_author(
        name=f"RELEASEBOT | {media_label}"
    )

    poster_path = (
        details.get("poster_path")
        or item.get("poster_path")
    )

    if poster_path:
        embed.set_image(
            url=f"{TMDB_IMAGE_URL}{poster_path}"
        )

    if media_type == "tv" and get_us_provider_names(details):
        embed.set_footer(
            text=(
                "Data provided by TMDb "
                "| Availability powered by JustWatch"
            )
        )
    else:
        embed.set_footer(text="Data provided by TMDb")

    return embed


async def search_tmdb_titles(
    name: str,
    media_type: str
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

        for item in data.get("results", []):
            item["_media_type"] = "movie"
            item["_source"] = "tmdb"
            results.append(item)

    else:

        data = await fetch_tmdb(
            "search/tv",
            {
                "query": name,
                "include_adult": "false",
            }
        )

        for item in data.get("results", []):
            item["_media_type"] = "tv"
            item["_source"] = "tmdb"
            results.append(item)

    query_norm = normalize_title(name)
    relevant = []

    for item in results:

        title = item.get("title") or item.get("name") or ""
        original_title = (
            item.get("original_title")
            or item.get("original_name")
            or ""
        )

        title_norm = normalize_title(title)
        original_norm = normalize_title(original_title)

        if (
            title_norm == query_norm
            or original_norm == query_norm
            or title_norm.startswith(query_norm + " ")
            or original_norm.startswith(query_norm + " ")
            or query_norm in title_norm
            or query_norm in original_norm
        ):
            relevant.append(item)

    relevant.sort(
        key=lambda item: search_relevance(item, name)
    )

    collection_results = []

    if media_type == "movie" and relevant:

        try:
            collection_results = await get_movie_collection_parts(
                relevant[0]
            )
        except Exception as error:
            print(f"Collection lookup error: {error}")

    final_results = []
    seen = set()

    def add_unique(item: dict):

        key = (
            item.get("_media_type"),
            item.get("id")
        )

        if item.get("id") is not None and key not in seen:
            seen.add(key)
            final_results.append(item)

    if relevant:
        add_unique(relevant[0])

    for item in collection_results:
        add_unique(item)

    for item in relevant:
        add_unique(item)

    return final_results[:10]


async def build_search_tmdb_embed(item: dict) -> discord.Embed:

    media_type = item.get("_media_type")
    tmdb_id = item.get("id")
    details = await get_details(media_type, tmdb_id)

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
        media_label = "SERIES"

    year = date_string[:4] if date_string else ""

    display_title = (
        f"{title} ({year})"
        if year
        else title
    )

    page_url = f"{TMDB_WEB_URL}/{media_type}/{tmdb_id}"
    genre_text = format_genres(details)
    cast_text = format_cast(details)
    runtime_text = format_runtime(details, media_type)
    availability = format_search_availability(details)

    overview = (
        details.get("overview")
        or item.get("overview")
        or "No synopsis is currently available."
    ).strip()

    if len(overview) > 650:
        overview = overview[:647].rstrip() + "..."

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
        f"ð·ï¸ *{genre_text}*",
        f"ð­ **{cast_text}**",
        f"ð **{runtime_text}**",
    ]

    if availability:
        metadata_lines.append(
            f"ðº **{availability}**"
        )

    metadata = "\n".join(metadata_lines)

    description = (
        f"{metadata}\n\n"
        f"{overview}\n\n"
        f"ð **{format_release_date(date_string)}**\n"
        f"{score_meter(rating, vote_count)}"
    )

    embed = discord.Embed(
        title=display_title,
        url=page_url,
        description=description,
        color=discord.Color.from_rgb(40, 105, 150)
    )

    embed.set_author(
        name=f"RELEASEBOT | {media_label}"
    )

    poster_path = (
        details.get("poster_path")
        or item.get("poster_path")
    )

    if poster_path:
        embed.set_image(
            url=f"{TMDB_IMAGE_URL}{poster_path}"
        )

    if availability:
        embed.set_footer(
            text=(
                "Data provided by TMDb "
                "| Availability powered by JustWatch"
            )
        )
    else:
        embed.set_footer(text="Data provided by TMDb")

    return embed


async def get_future_tmdb_countdown_item(
    results: list[dict]
) -> tuple[dict, str] | None:

    today = datetime.now(timezone.utc).date()

    for item in results:

        media_type = item.get("_media_type")
        tmdb_id = item.get("id")

        if not tmdb_id:
            continue

        try:

            details = await get_details(
                media_type,
                tmdb_id
            )

            if media_type == "movie":

                original_date_string = (
                    details.get("release_date")
                    or item.get("release_date")
                )

                if not original_date_string:
                    continue

                original_release_date = datetime.strptime(
                    original_date_string,
                    "%Y-%m-%d"
                ).date()

                if original_release_date < today:
                    continue

                date_string = await get_us_movie_release_date(
                    tmdb_id
                )

                if not date_string:
                    date_string = original_date_string

            else:

                date_string = (
                    details.get("first_air_date")
                    or item.get("first_air_date")
                )

                if not date_string:
                    continue

                first_air_date = datetime.strptime(
                    date_string,
                    "%Y-%m-%d"
                ).date()

                if first_air_date < today:
                    continue

            countdown_date = datetime.strptime(
                date_string,
                "%Y-%m-%d"
            ).date()

            if countdown_date < today:
                continue

            return item, date_string

        except Exception as error:
            print(f"Countdown filter error: {error}")
            continue

    return None


async def build_countdown_tmdb_embed(
    item: dict,
    date_string: str
) -> discord.Embed:

    media_type = item.get("_media_type")
    tmdb_id = item.get("id")
    details = await get_details(media_type, tmdb_id)

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
        media_label = "SERIES"

    page_url = f"{TMDB_WEB_URL}/{media_type}/{tmdb_id}"

    embed = discord.Embed(
        title=title,
        url=page_url,
        description=(
            f"ð **{format_release_date(date_string)}**\n"
            f"â³ **{format_exact_countdown(date_string)}**"
        ),
        color=discord.Color.from_rgb(40, 105, 150)
    )

    embed.set_author(
        name=f"RELEASEBOT | {media_label} COUNTDOWN"
    )

    poster_path = (
        details.get("poster_path")
        or item.get("poster_path")
    )

    if poster_path:
        embed.set_thumbnail(
            url=f"{TMDB_THUMBNAIL_URL}{poster_path}"
        )

    embed.set_footer(text="Data provided by TMDb")

    return embed


# ============================================================
# IGDB ENGINE
# Completely separate from the TMDB engine above.
# ============================================================

async def get_igdb_token(force_refresh: bool = False) -> str:

    now = datetime.now(timezone.utc)

    if (
        not force_refresh
        and client.igdb_token
        and now < client.igdb_token_expires_at
    ):
        return client.igdb_token

    async with client.igdb_token_lock:

        now = datetime.now(timezone.utc)

        if (
            not force_refresh
            and client.igdb_token
            and now < client.igdb_token_expires_at
        ):
            return client.igdb_token

        timeout = aiohttp.ClientTimeout(total=15)

        async with aiohttp.ClientSession(timeout=timeout) as session:

            async with session.post(
                TWITCH_TOKEN_URL,
                params={
                    "client_id": TWITCH_CLIENT_ID,
                    "client_secret": TWITCH_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                }
            ) as response:

                body = await response.text()

                if response.status != 200:
                    raise RuntimeError(
                        f"Twitch token HTTP {response.status}: "
                        f"{body[:300]}"
                    )

                data = await response.json()

        token = data.get("access_token")
        expires_in = int(data.get("expires_in") or 0)

        if not token:
            raise RuntimeError(
                "Twitch did not return an access token."
            )

        client.igdb_token = token
        client.igdb_token_expires_at = (
            datetime.now(timezone.utc)
            + timedelta(seconds=max(expires_in - 300, 60))
        )

        print("IGDB token acquired.")
        return token


async def fetch_igdb(
    endpoint: str,
    body: str,
    retry_auth: bool = True
) -> list[dict]:

    token = await get_igdb_token()

    timeout = aiohttp.ClientTimeout(total=15)

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "text/plain",
    }

    async with aiohttp.ClientSession(timeout=timeout) as session:

        async with session.post(
            f"{IGDB_BASE_URL}/{endpoint}",
            data=body,
            headers=headers
        ) as response:

            text = await response.text()

            if response.status == 401 and retry_auth:
                await get_igdb_token(force_refresh=True)
                return await fetch_igdb(
                    endpoint,
                    body,
                    retry_auth=False
                )

            if response.status != 200:
                raise RuntimeError(
                    f"IGDB HTTP {response.status}: {text[:400]}"
                )

            return await response.json()


def escape_igdb_string(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .strip()
    )


async def resolve_igdb_platform(
    platform_text: str | None
) -> dict | None:

    if not platform_text:
        return None

    raw = platform_text.strip()

    aliases = {
        "steam": "PC (Microsoft Windows)",
        "pc": "PC (Microsoft Windows)",
        "windows": "PC (Microsoft Windows)",
        "switch": "Nintendo Switch",
        "switch 1": "Nintendo Switch",
        "switch2": "Nintendo Switch 2",
        "switch 2": "Nintendo Switch 2",
        "ps1": "PlayStation",
        "ps2": "PlayStation 2",
        "ps3": "PlayStation 3",
        "ps4": "PlayStation 4",
        "ps5": "PlayStation 5",
        "snes": "Super Nintendo Entertainment System",
        "nes": "Nintendo Entertainment System",
        "n64": "Nintendo 64",
    }

    search_name = aliases.get(
        raw.lower(),
        raw
    )

    escaped = escape_igdb_string(search_name)

    results = await fetch_igdb(
        "platforms",
        (
            f'search "{escaped}"; '
            f"fields id,name,abbreviation,alternative_name; "
            f"limit 10;"
        )
    )

    if not results:
        return None

    target_norm = normalize_title(search_name)

    def rank(item: dict):

        names = [
            item.get("name") or "",
            item.get("abbreviation") or "",
            item.get("alternative_name") or "",
        ]

        normalized = [
            normalize_title(value)
            for value in names
            if value
        ]

        exact = target_norm in normalized
        starts = any(
            value.startswith(target_norm)
            for value in normalized
        )

        return (
            0 if exact else 1 if starts else 2,
            len(item.get("name") or "")
        )

    results.sort(key=rank)
    return results[0]


async def platform_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:

    try:

        media = getattr(
            interaction.namespace,
            "media",
            None
        )

        if media and media != "game":
            return []

        current = current.strip()

        if not current:

            defaults = [
                "Steam",
                "PlayStation 5",
                "Xbox Series X|S",
                "Nintendo Switch",
                "Nintendo Switch 2",
                "PC (Microsoft Windows)",
                "PlayStation 4",
                "Xbox One",
                "Super Nintendo Entertainment System",
                "Nintendo 64",
            ]

            return [
                app_commands.Choice(name=name, value=name)
                for name in defaults
            ]

        lookup_text = (
            "PC (Microsoft Windows)"
            if current.lower() == "steam"
            else current
        )

        escaped = escape_igdb_string(lookup_text)

        results = await fetch_igdb(
            "platforms",
            (
                f'search "{escaped}"; '
                f"fields name,abbreviation; "
                f"limit 10;"
            )
        )

        choices = []

        if "steam".startswith(current.lower()):
            choices.append(
                app_commands.Choice(
                    name="Steam",
                    value="Steam"
                )
            )

        for item in results:

            name = item.get("name")

            if (
                name
                and all(choice.value != name for choice in choices)
            ):
                choices.append(
                    app_commands.Choice(
                        name=name[:100],
                        value=name[:100]
                    )
                )

            if len(choices) >= 10:
                break

        return choices

    except Exception as error:
        print(f"Platform autocomplete error: {error}")
        return []


IGDB_GAME_FIELDS = (
    "id,name,slug,summary,url,"
    "first_release_date,rating,rating_count,"
    "total_rating,total_rating_count,"
    "cover.image_id,"
    "genres.name,"
    "platforms.id,platforms.name,platforms.abbreviation,"
    "game_modes.name,"
    "involved_companies.company.name,"
    "involved_companies.developer,"
    "involved_companies.publisher,"
    "release_dates.date,"
    "release_dates.human,"
    "release_dates.platform.id,"
    "release_dates.platform.name"
)


def igdb_game_relevance(
    item: dict,
    query: str
) -> tuple:

    query_norm = normalize_title(query)
    name_norm = normalize_title(item.get("name") or "")

    if name_norm == query_norm:
        match_rank = 0
    elif name_norm.startswith(query_norm + " "):
        match_rank = 1
    elif query_norm in name_norm:
        match_rank = 2
    else:
        match_rank = 3

    rating_count = int(
        item.get("total_rating_count")
        or item.get("rating_count")
        or 0
    )

    return (match_rank, -rating_count)


async def search_igdb_games(
    title: str,
    platform_text: str | None = None
) -> list[dict]:

    platform = await resolve_igdb_platform(platform_text)

    if platform_text and not platform:
        return []

    escaped = escape_igdb_string(title)

    results = await fetch_igdb(
        "games",
        (
            f'search "{escaped}"; '
            f"fields {IGDB_GAME_FIELDS}; "
            f"where version_parent = null; "
            f"limit 25;"
        )
    )

    filtered = []

    for item in results:

        if platform:

            platform_ids = [
                p.get("id")
                for p in item.get("platforms") or []
            ]

            if platform.get("id") not in platform_ids:
                continue

            item["_selected_platform_id"] = platform.get("id")
            item["_selected_platform_name"] = (
                "Steam"
                if (
                    platform_text
                    and platform_text.lower().strip() == "steam"
                )
                else platform.get("name")
            )

        item["_source"] = "igdb"
        item["_media_type"] = "game"
        filtered.append(item)

    filtered.sort(
        key=lambda item:
            igdb_game_relevance(item, title)
    )

    return filtered[:10]


def unix_to_date_string(
    unix_time: int | float | None
) -> str | None:

    if not unix_time:
        return None

    return datetime.fromtimestamp(
        int(unix_time),
        tz=timezone.utc
    ).date().isoformat()


def get_game_release(
    item: dict,
    future_only: bool = False,
    start_date=None,
    end_date=None
) -> dict | None:

    selected_platform_id = item.get(
        "_selected_platform_id"
    )

    today = datetime.now(timezone.utc).date()
    matches = []

    for release in item.get("release_dates") or []:

        unix_time = release.get("date")

        if not unix_time:
            continue

        platform = release.get("platform") or {}

        if (
            selected_platform_id
            and platform.get("id") != selected_platform_id
        ):
            continue

        date_value = datetime.fromtimestamp(
            int(unix_time),
            tz=timezone.utc
        ).date()

        if future_only and date_value < today:
            continue
        if start_date and date_value < start_date:
            continue
        if end_date and date_value > end_date:
            continue

        matches.append((date_value, release))

    if not matches:
        return None

    matches.sort(key=lambda entry: entry[0])
    return matches[0][1]


def get_game_display_date(item: dict) -> str | None:

    release = get_game_release(item)

    if release:
        return unix_to_date_string(release.get("date"))

    return unix_to_date_string(item.get("first_release_date"))


def game_genres_text(item: dict) -> str:

    names = [
        genre.get("name")
        for genre in item.get("genres") or []
        if genre.get("name")
    ]

    return " / ".join(names[:3]) if names else "Genre unavailable"


def game_platforms_text(item: dict) -> str:

    names = []

    for platform in item.get("platforms") or []:
        name = platform.get("name")
        if name and name not in names:
            names.append(name)

    return (
        " / ".join(names[:6])
        if names
        else "Platforms unavailable"
    )


def game_modes_text(item: dict) -> str | None:

    names = [
        mode.get("name")
        for mode in item.get("game_modes") or []
        if mode.get("name")
    ]

    return " / ".join(names[:4]) if names else None


def game_companies_text(item: dict) -> str | None:

    developers = []
    publishers = []

    for involved in item.get("involved_companies") or []:

        company = involved.get("company") or {}
        name = company.get("name")

        if not name:
            continue

        if involved.get("developer") and name not in developers:
            developers.append(name)

        if involved.get("publisher") and name not in publishers:
            publishers.append(name)

    names = developers[:2]

    for name in publishers:
        if name not in names:
            names.append(name)

        if len(names) >= 3:
            break

    return " / ".join(names) if names else None


def game_rating_meter(item: dict) -> str:

    rating = float(
        item.get("total_rating")
        or item.get("rating")
        or 0
    )

    count = int(
        item.get("total_rating_count")
        or item.get("rating_count")
        or 0
    )

    if count <= 0:
        return "â­ï¸ **Not Rated Yet**\n`â±â±â±â±â±â±â±â±â±â±`"

    rating = max(0, min(rating, 100))
    filled = round(rating / 10)
    empty = 10 - filled
    bar = "â°" * filled + "â±" * empty

    return f"â­ï¸ **{rating:.0f}/100**\n`{bar}`"


def igdb_cover_url(
    image_id: str | None,
    size: str = "cover_big"
) -> str | None:

    if not image_id:
        return None

    return (
        f"{IGDB_IMAGE_URL}/t_{size}/{image_id}.jpg"
    )


async def build_search_igdb_embed(
    item: dict
) -> discord.Embed:

    title = item.get("name") or "Untitled"
    date_string = get_game_display_date(item)
    year = date_string[:4] if date_string else ""

    display_title = (
        f"{title} ({year})"
        if year
        else title
    )

    metadata_lines = [
        f"ð·ï¸ *{game_genres_text(item)}*",
        f"ð® **{game_platforms_text(item)}**",
    ]

    selected = item.get("_selected_platform_name")

    if selected:
        metadata_lines.insert(
            1,
            f"ð¹ï¸ **Selected: {selected}**"
        )

    companies = game_companies_text(item)

    if companies:
        metadata_lines.append(
            f"ð¢ **{companies}**"
        )

    modes = game_modes_text(item)

    if modes:
        metadata_lines.append(
            f"ð¥ **{modes}**"
        )

    overview = (
        item.get("summary")
        or "No synopsis is currently available."
    ).strip()

    if len(overview) > 650:
        overview = overview[:647].rstrip() + "..."

    description = (
        f"{chr(10).join(metadata_lines)}\n\n"
        f"{overview}\n\n"
        f"ð **{format_release_date(date_string)}**\n"
        f"{game_rating_meter(item)}"
    )

    embed = discord.Embed(
        title=display_title,
        url=item.get("url"),
        description=description,
        color=discord.Color.from_rgb(40, 105, 150)
    )

    embed.set_author(name="RELEASEBOT | GAME")

    cover = item.get("cover") or {}
    cover_url = igdb_cover_url(cover.get("image_id"))

    if cover_url:
        embed.set_image(url=cover_url)

    embed.set_footer(text="Game data provided by IGDB")

    return embed


async def get_future_igdb_countdown_item(
    results: list[dict]
) -> tuple[dict, str] | None:

    for item in results:

        release = get_game_release(
            item,
            future_only=True
        )

        if not release:
            continue

        date_string = unix_to_date_string(
            release.get("date")
        )

        if not date_string:
            continue

        item["_countdown_release"] = release
        return item, date_string

    return None


async def build_countdown_igdb_embed(
    item: dict,
    date_string: str
) -> discord.Embed:

    release = item.get("_countdown_release") or {}
    release_platform = release.get("platform") or {}

    platform_name = (
        item.get("_selected_platform_name")
        or release_platform.get("name")
    )

    lines = []

    if platform_name:
        lines.append(f"ð® **{platform_name}**")

    lines.append(
        f"ð **{format_release_date(date_string)}**"
    )
    lines.append(
        f"â³ **{format_exact_countdown(date_string)}**"
    )

    embed = discord.Embed(
        title=item.get("name") or "Untitled",
        url=item.get("url"),
        description="\n".join(lines),
        color=discord.Color.from_rgb(40, 105, 150)
    )

    embed.set_author(
        name="RELEASEBOT | GAME COUNTDOWN"
    )

    cover = item.get("cover") or {}
    cover_url = igdb_cover_url(
        cover.get("image_id"),
        "cover_small"
    )

    if cover_url:
        embed.set_thumbnail(url=cover_url)

    embed.set_footer(text="Game data provided by IGDB")

    return embed


async def get_upcoming_igdb(
    timeframe: str,
    platform_text: str | None = None
) -> list[dict]:

    platform = await resolve_igdb_platform(platform_text)

    if platform_text and not platform:
        return []

    today = datetime.now(timezone.utc).date()
    days = 7 if timeframe == "week" else 30
    end_date = today + timedelta(days=days)

    start_unix = int(
        datetime.combine(
            today,
            datetime.min.time(),
            tzinfo=timezone.utc
        ).timestamp()
    )

    end_unix = int(
        datetime.combine(
            end_date,
            datetime.max.time(),
            tzinfo=timezone.utc
        ).timestamp()
    )

    where_parts = [
        f"date >= {start_unix}",
        f"date <= {end_unix}",
    ]

    if platform:
        where_parts.append(
            f"platform = {platform['id']}"
        )

    releases = await fetch_igdb(
        "release_dates",
        (
            f"fields date,human,"
            f"platform.id,platform.name,"
            f"game.id,game.name,game.slug,game.url,"
            f"game.summary,game.first_release_date,"
            f"game.rating,game.rating_count,"
            f"game.total_rating,game.total_rating_count,"
            f"game.cover.image_id,"
            f"game.genres.name,"
            f"game.platforms.id,game.platforms.name,"
            f"game.game_modes.name,"
            f"game.involved_companies.company.name,"
            f"game.involved_companies.developer,"
            f"game.involved_companies.publisher; "
            f"where {' & '.join(where_parts)}; "
            f"sort date asc; "
            f"limit 50;"
        )
    )

    results = []
    seen = set()

    for release in releases:

        game = release.get("game") or {}
        game_id = game.get("id")

        if not game_id or game_id in seen:
            continue

        seen.add(game_id)

        game["_source"] = "igdb"
        game["_media_type"] = "game"
        game["_upcoming_release"] = release

        if platform:
            game["_selected_platform_id"] = platform.get("id")
            game["_selected_platform_name"] = (
                "Steam"
                if (
                    platform_text
                    and platform_text.lower().strip() == "steam"
                )
                else platform.get("name")
            )

        results.append(game)

    return results


async def build_upcoming_igdb_embed(
    item: dict
) -> discord.Embed:

    release = item.get("_upcoming_release") or {}
    date_string = unix_to_date_string(release.get("date"))

    platform_name = (
        item.get("_selected_platform_name")
        or (release.get("platform") or {}).get("name")
    )

    metadata_lines = [
        f"ð·ï¸ *{game_genres_text(item)}*",
        f"ð® **{game_platforms_text(item)}**",
    ]

    if platform_name:
        metadata_lines.insert(
            1,
            f"ð¹ï¸ **Release: {platform_name}**"
        )

    companies = game_companies_text(item)

    if companies:
        metadata_lines.append(
            f"ð¢ **{companies}**"
        )

    overview = (
        item.get("summary")
        or "No synopsis is currently available."
    ).strip()

    if len(overview) > 650:
        overview = overview[:647].rstrip() + "..."

    description = (
        f"{chr(10).join(metadata_lines)}\n\n"
        f"{overview}\n\n"
        f"ð **{format_release_date(date_string)}**\n"
        f"â³ **{format_countdown(date_string)}**\n"
        f"{game_rating_meter(item)}"
    )

    embed = discord.Embed(
        title=item.get("name") or "Untitled",
        url=item.get("url"),
        description=description,
        color=discord.Color.from_rgb(40, 105, 150)
    )

    embed.set_author(name="RELEASEBOT | GAME")

    cover = item.get("cover") or {}
    cover_url = igdb_cover_url(cover.get("image_id"))

    if cover_url:
        embed.set_image(url=cover_url)

    embed.set_footer(text="Game data provided by IGDB")

    return embed


# ============================================================
# SHARED DISCORD UI
# ============================================================

async def build_search_embed(item: dict) -> discord.Embed:

    if item.get("_source") == "igdb":
        return await build_search_igdb_embed(item)

    return await build_search_tmdb_embed(item)


async def build_upcoming_embed(item: dict) -> discord.Embed:

    if item.get("_source") == "igdb":
        return await build_upcoming_igdb_embed(item)

    return await build_upcoming_tmdb_embed(
        item,
        item.get("_media_type")
    )


class ReleaseBrowser(discord.ui.View):

    def __init__(
        self,
        results: list[dict],
        requester_id: int
    ):
        super().__init__(timeout=300)

        self.results = results
        self.requester_id = requester_id
        self.page = 0
        self.total_pages = len(results)
        self.update_buttons()

    def update_buttons(self):

        has_multiple_pages = self.total_pages > 1
        self.previous_button.disabled = not has_multiple_pages
        self.next_button.disabled = not has_multiple_pages
        self.page_button.label = (
            f"{self.page + 1} / {self.total_pages}"
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Run `/upcoming` to open your own ReleaseBot browser.",
                ephemeral=True
            )
            return False

        return True

    async def get_current_embed(self) -> discord.Embed:
        return await build_upcoming_embed(
            self.results[self.page]
        )

    @discord.ui.button(
        label="Previous",
        emoji="âï¸",
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
        emoji="â¶ï¸",
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


class SearchBrowser(discord.ui.View):

    def __init__(
        self,
        results: list[dict],
        requester_id: int
    ):
        super().__init__(timeout=300)

        self.results = results
        self.requester_id = requester_id
        self.page = 0
        self.total_pages = len(results)
        self.update_buttons()

    def update_buttons(self):

        has_multiple_pages = self.total_pages > 1
        self.previous_button.disabled = not has_multiple_pages
        self.next_button.disabled = not has_multiple_pages
        self.page_button.label = (
            f"{self.page + 1} / {self.total_pages}"
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Run `/search` to open your own ReleaseBot search.",
                ephemeral=True
            )
            return False

        return True

    async def get_current_embed(self) -> discord.Embed:
        return await build_search_embed(
            self.results[self.page]
        )

    @discord.ui.button(
        label="Previous",
        emoji="âï¸",
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
        emoji="â¶ï¸",
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


MEDIA_CHOICES = [
    app_commands.Choice(name="Movie", value="movie"),
    app_commands.Choice(name="Series", value="tv"),
    app_commands.Choice(name="Game", value="game"),
]

TIME_CHOICES = [
    app_commands.Choice(name="Week", value="week"),
    app_commands.Choice(name="Month", value="month"),
]


def validate_platform(
    media: str,
    platform: str | None
) -> str | None:

    if media != "game" and platform:
        return (
            "`platform` only applies to Game. "
            "Leave it blank for Movie or Series."
        )

    return None


# ============================================================
# COMMAND ROUTER
# ============================================================

@client.tree.command(
    name="search",
    description="Search for a movie, series, or game."
)
@app_commands.describe(
    media="Choose Movie, Series, or Game.",
    title="Title to search for.",
    platform="Optional game platform or console."
)
@app_commands.choices(media=MEDIA_CHOICES)
@app_commands.autocomplete(platform=platform_autocomplete)
async def search(
    interaction: discord.Interaction,
    media: app_commands.Choice[str],
    title: str,
    platform: str | None = None
):

    error = validate_platform(media.value, platform)

    if error:
        await interaction.response.send_message(
            error,
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:

        if media.value == "game":
            results = await search_igdb_games(
                title,
                platform
            )
        else:
            results = await search_tmdb_titles(
                title,
                media.value
            )

    except Exception as error:
        print(f"Search error: {error}")
        await interaction.followup.send(
            "ReleaseBot couldn't complete that search right now."
        )
        return

    if not results:
        await interaction.followup.send(
            f"No relevant results found for **{title}**."
        )
        return

    view = SearchBrowser(
        results=results,
        requester_id=interaction.user.id
    )

    try:
        embed = await view.get_current_embed()
    except Exception as error:
        print(f"Search detail error: {error}")
        await interaction.followup.send(
            "ReleaseBot found a result, but couldn't load its details."
        )
        return

    await interaction.followup.send(
        embed=embed,
        view=view
    )


@client.tree.command(
    name="countdown",
    description="Countdown to an upcoming movie, series, or game."
)
@app_commands.describe(
    media="Choose Movie, Series, or Game.",
    title="Upcoming title to search for.",
    platform="Optional game platform or console."
)
@app_commands.choices(media=MEDIA_CHOICES)
@app_commands.autocomplete(platform=platform_autocomplete)
async def countdown(
    interaction: discord.Interaction,
    media: app_commands.Choice[str],
    title: str,
    platform: str | None = None
):

    error = validate_platform(media.value, platform)

    if error:
        await interaction.response.send_message(
            error,
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:

        if media.value == "game":

            results = await search_igdb_games(
                title,
                platform
            )

            future_match = await get_future_igdb_countdown_item(
                results
            )

        else:

            results = await search_tmdb_titles(
                title,
                media.value
            )

            future_match = await get_future_tmdb_countdown_item(
                results
            )

    except Exception as error:
        print(f"Countdown search error: {error}")
        await interaction.followup.send(
            "ReleaseBot couldn't search for that title right now."
        )
        return

    if not future_match:
        await interaction.followup.send(
            f"No unreleased title matching **{title}** was found."
        )
        return

    result, date_string = future_match

    try:

        if media.value == "game":
            embed = await build_countdown_igdb_embed(
                result,
                date_string
            )
        else:
            embed = await build_countdown_tmdb_embed(
                result,
                date_string
            )

    except Exception as error:
        print(f"Countdown detail error: {error}")
        await interaction.followup.send(
            "ReleaseBot found an upcoming title, "
            "but couldn't load its countdown."
        )
        return

    await interaction.followup.send(embed=embed)


@client.tree.command(
    name="upcoming",
    description="Browse upcoming movie, series, or game releases."
)
@app_commands.describe(
    media="Choose Movie, Series, or Game.",
    timeframe="Choose week or month.",
    platform="Optional game platform or console."
)
@app_commands.rename(timeframe="time")
@app_commands.choices(
    media=MEDIA_CHOICES,
    timeframe=TIME_CHOICES
)
@app_commands.autocomplete(platform=platform_autocomplete)
async def upcoming(
    interaction: discord.Interaction,
    media: app_commands.Choice[str],
    timeframe: app_commands.Choice[str],
    platform: str | None = None
):

    error = validate_platform(media.value, platform)

    if error:
        await interaction.response.send_message(
            error,
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:

        if media.value == "game":
            results = await get_upcoming_igdb(
                timeframe.value,
                platform
            )
        else:
            results = await get_upcoming_tmdb(
                media.value,
                timeframe.value
            )

    except Exception as error:
        print(f"Upcoming error: {error}")
        await interaction.followup.send(
            "ReleaseBot couldn't retrieve release information right now."
        )
        return

    if not results:
        await interaction.followup.send(
            "No releases were found for that period."
        )
        return

    view = ReleaseBrowser(
        results=results,
        requester_id=interaction.user.id
    )

    try:
        embed = await view.get_current_embed()
    except Exception as error:
        print(f"Upcoming detail error: {error}")
        await interaction.followup.send(
            "ReleaseBot found releases, but couldn't load their details."
        )
        return

    await interaction.followup.send(
        embed=embed,
        view=view
    )


client.run(DISCORD_TOKEN)
