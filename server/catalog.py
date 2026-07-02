"""Catalog endpoints using MovieBox's own genreTopId catalog system."""

import json
import base64
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

# MovieBox's catalog sections mapped from homepage
MOVIEBOX_CATALOGS = {
    "trending":     {"name": "🔥 Trending",        "genreTopId": "4516404531735022304", "type": "movie"},
    "cinema":       {"name": "🎬 Cinema",           "genreTopId": "5692654647815587592", "type": "movie"},
    "hollywood":    {"name": "🇺🇸 Hollywood",       "genreTopId": "8019599703232971616", "type": "movie"},
    "bollywood":    {"name": "🇮🇳 Bollywood",       "genreTopId": "414907768299210008",  "type": "movie"},
    "south_indian": {"name": "🇮🇳 South Indian",    "genreTopId": "3859721901924910512", "type": "movie"},
    "asian":        {"name": "🌏 Asian",            "genreTopId": "5429170738815291968", "type": "movie"},
    "turkish":      {"name": "🇹🇷 Turkish Drama",   "genreTopId": "5177200225164885656", "type": "movie"},
    "indian_drama": {"name": "🇮🇳 Indian Drama",    "genreTopId": "4903182713986896328", "type": "series"},
    "top_series":   {"name": "📺 Top Series",       "genreTopId": "4741626294545400336", "type": "series"},
    "asian_series": {"name": "🌏 Asian Series",     "genreTopId": "1976033493293449744", "type": "series"},
    "western_tv":   {"name": "🇺🇸 Western TV",      "genreTopId": "3910636007619709856", "type": "series"},
    "anime":        {"name": "🎌 Anime",            "genreTopId": "8434602210994128512", "type": "series"},
}


def parse_config(config_str: str) -> dict:
    try:
        padding = 4 - (len(config_str) % 4)
        if padding != 4:
            config_str += "=" * padding
        decoded = base64.urlsafe_b64decode(config_str).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


async def fetch_moviebox_catalog(request: Request, genre_top_id: str, page: int = 1):
    """Fetch catalog from MovieBox's ContentCategory API using the app's httpx client."""
    from moviebox.web.core import ContentCategory
    from moviebox.web.requests import Session

    try:
        # Create a session that uses our httpx client
        s = Session()
        cat = ContentCategory(
            genre_top_id=genre_top_id,
            session=s,
            per_page=20,
            page=page,
        )
        res = await cat.get_content_model()
        items = []
        for item in res.items:
            detail_path = getattr(item, 'detailPath', '') or ''
            name = getattr(item, 'name', '') or detail_path.replace('-', ' ').title()
            date = getattr(item, 'releaseDate', None)
            year = str(date.year) if date and hasattr(date, 'year') else ''
            subject_id = str(getattr(item, 'subjectId', ''))

            # Clean up name - remove language suffixes
            for suffix in [' hindi', ' tamil', ' telugu', ' spanish', ' french', ' german', ' arabic', ' dubbed']:
                if name.lower().endswith(suffix):
                    name = name[:-(len(suffix))]

            items.append({
                "name": name.strip().title(),
                "detailPath": detail_path,
                "subjectId": subject_id,
                "year": year,
            })
        return items
    except Exception as e:
        print(f"[Catalog] Error: {e}")
        return []


async def resolve_name_to_imdb(http_client, name: str, year: str) -> str | None:
    """Resolve movie name to IMDB ID via TMDB."""
    try:
        # Clean name for search
        clean = name.strip()
        resp = await http_client.get(
            "https://api.themoviedb.org/3/search/movie",
            params={"api_key": "e779f44db85aedbffe2dfcf252b372dc", "query": clean, "year": year},
            timeout=8,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                tmdb_id = results[0]["id"]
                ext = await http_client.get(
                    f"https://api.themoviedb.org/3/movie/{tmdb_id}/external_ids",
                    params={"api_key": "e779f44db85aedbffe2dfcf252b372dc"},
                    timeout=8,
                )
                if ext.status_code == 200:
                    imdb = ext.json().get("imdb_id")
                    if imdb:
                        return imdb
        # Fallback: search without year
        resp2 = await http_client.get(
            "https://api.themoviedb.org/3/search/movie",
            params={"api_key": "e779f44db85aedbffe2dfcf252b372dc", "query": clean},
            timeout=8,
        )
        if resp2.status_code == 200:
            results2 = resp2.json().get("results", [])
            if results2:
                tmdb_id2 = results2[0]["id"]
                ext2 = await http_client.get(
                    f"https://api.themoviedb.org/3/movie/{tmdb_id2}/external_ids",
                    params={"api_key": "e779f44db85aedbffe2dfcf252b372dc"},
                    timeout=8,
                )
                if ext2.status_code == 200:
                    return ext2.json().get("imdb_id")
    except Exception:
        pass
    return None


# ─── Catalog routes ───────────────────────────────────────────

@router.get("/{config}/catalog/{type}/{catalog_id}.json")
async def catalog_with_config(request: Request, config: str, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, config)


@router.get("/catalog/{type}/{catalog_id}.json")
async def catalog_no_config(request: Request, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, "")


async def handle_catalog(request: Request, type: str, catalog_id: str, config_str: str):
    """Return catalog of movies/shows from MovieBox."""
    skip = int(request.query_params.get("skip", "0"))
    page = (skip // 20) + 1

    section = catalog_id.replace("moviebox_", "").replace("_catalog", "")

    catalog_info = MOVIEBOX_CATALOGS.get(section, MOVIEBOX_CATALOGS["trending"])

    items = await fetch_moviebox_catalog(request, catalog_info["genreTopId"], page=page)

    metas = []
    http_client = request.app.state.http_client

    for item in items:
        imdb_id = await resolve_name_to_imdb(http_client, item["name"], item["year"])
        if not imdb_id:
            continue

        poster_url = f"https://api.ratingposterdb.com/t0-free-rpdb/imdb/poster-default/{imdb_id}.jpg"

        metas.append({
            "id": imdb_id,
            "type": type,
            "name": item["name"],
            "releaseInfo": item["year"],
            "poster": poster_url,
            "description": f"From MovieBox — {catalog_info['name']}",
        })

    return JSONResponse({"metas": metas, "cacheMaxAge": 1800})
