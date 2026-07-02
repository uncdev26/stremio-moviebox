from pydantic import BaseModel

RPDB_KEY = "t0-free-rpdb"


class Manifest(BaseModel):
    id: str
    version: str
    name: str
    description: str
    resources: list[str]
    types: list[str]
    catalogs: list
    idPrefixes: list[str]
    logo: str | None = None
    behaviorHints: dict | None = None


def get_manifest() -> Manifest:
    return Manifest(
        id="com.moviebox.addon",
        version="1.0.0",
        name="MovieBox",
        description="Universal streaming — 1000+ movies & series from every corner of the world.",
        resources=["stream", "catalog", "meta"],
        types=["movie", "series"],
        catalogs=[
            {"id": "moviebox_trending",     "type": "movie",  "name": "🔥 Trending"},
            {"id": "moviebox_cinema",       "type": "movie",  "name": "🎬 Cinema"},
            {"id": "moviebox_hollywood",    "type": "movie",  "name": "🇺🇸 Hollywood"},
            {"id": "moviebox_bollywood",    "type": "movie",  "name": "🇮🇳 Bollywood"},
            {"id": "moviebox_south_indian", "type": "movie",  "name": "🇮🇳 South Indian"},
            {"id": "moviebox_asian",        "type": "movie",  "name": "🌏 Asian"},
            {"id": "moviebox_turkish",      "type": "movie",  "name": "🇹🇷 Turkish"},
            {"id": "moviebox_top_series",   "type": "series", "name": "📺 Top Series"},
            {"id": "moviebox_indian_drama", "type": "series", "name": "🇮🇳 Indian Drama"},
            {"id": "moviebox_asian_series", "type": "series", "name": "🌏 Asian Series"},
            {"id": "moviebox_western_tv",   "type": "series", "name": "🇺🇸 Western TV"},
            {"id": "moviebox_anime",        "type": "series", "name": "🎌 Anime"},
        ],
        idPrefixes=["tt", "mb:"],
        behaviorHints={
            "configurable": True,
            "configurationRequired": False,
        },
    )
