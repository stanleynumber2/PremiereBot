import os
import discord
import aiohttp
from discord import app_commands
from discord.ext import commands
from datetime import datetime


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"PremiereBot is online as {bot.user}")


@bot.tree.command(
    name="upcoming",
    description="See upcoming movie releases."
)
async def upcoming(interaction: discord.Interaction):

    await interaction.response.defer()

    url = "https://api.themoviedb.org/3/movie/upcoming"

    params = {
        "api_key": TMDB_API_KEY,
        "language": "en-US",
        "region": "US",
        "page": 1
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:

            if response.status != 200:
                await interaction.followup.send(
                    "I couldn't retrieve upcoming movies right now."
                )
                return

            data = await response.json()

    movies = data.get("results", [])

    if not movies:
        await interaction.followup.send(
            "I couldn't find any upcoming movies."
        )
        return

    # Sort movies by release date
    movies = [
        movie for movie in movies
        if movie.get("release_date")
    ]

    movies.sort(key=lambda movie: movie["release_date"])

    # Show the first 5 upcoming movies
    for movie in movies[:5]:

        title = movie.get("title", "Unknown Movie")
        release_date = movie.get("release_date")
        overview = movie.get("overview") or "No description available."
        poster_path = movie.get("poster_path")

        try:
            date = datetime.strptime(
                release_date,
                "%Y-%m-%d"
            )

            formatted_date = date.strftime("%B %d, %Y")

            days_remaining = (
                date.date() - datetime.now().date()
            ).days

            if days_remaining == 0:
                countdown = "Releases today!"
            elif days_remaining == 1:
                countdown = "Releases tomorrow!"
            elif days_remaining > 1:
                countdown = f"{days_remaining} days until release"
            else:
                countdown = "Now available"

        except ValueError:
            formatted_date = release_date
            countdown = ""

        embed = discord.Embed(
            title=title,
            description=overview[:500]
        )

        embed.add_field(
            name="Release Date",
            value=formatted_date,
            inline=True
        )

        embed.add_field(
            name="Countdown",
            value=countdown,
            inline=True
        )

        if poster_path:
            embed.set_thumbnail(
                url=f"https://image.tmdb.org/t/p/w500{poster_path}"
            )

        embed.set_footer(
            text="Movie data provided by TMDb"
        )

        await interaction.followup.send(embed=embed)


if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

if not TMDB_API_KEY:
    raise RuntimeError("TMDB_API_KEY is missing.")

bot.run(DISCORD_TOKEN)
