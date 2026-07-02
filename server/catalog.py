"""Catalog endpoints using MovieBox's own ranking-list API directly."""

import json
import base64
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

TMDB_API_KEY = "e779f44db85aedbffe2dfcf252b372dc"
MOVIEBOX_API = "https://h5-api.aoneroom.com/wefeed-h5api-bff/ranking-list/content"

# MovieBox's catalog sections mapped from homepage
MOVIEBOX_CATALOGS = {
    "trending":     {"name": "🔥 Trending Now",    "genreTopId": "4516404531735022304", "type": "movie"},
    "cinema":       {"name": "🎬 Cinema",           "genreTopId": "5692654647815587592", "type": "movie"},
    "hollywood":    {"name": "🇺🇸 Hollywood",       "genreTopId": "8019599703232971616", "type": "movie"},
    "bollywood":    {"name": "🇮🇳 Bollywood",       "genreTopId": "414907768299210008",  "type": "movie"},
    "south_indian": {"name": "🇮🇳 South Indian",    "genreTopId": "3859721901924910512", "type": "movie"},
    "asian":        {"name": "🌏 Asian Movies",     "genreTopId": "5429170738815291968", "type": "movie"},
    "turkish":      {"name": "🇹🇷 Turkish Drama",   "genreTopId": "5177200225164885656", "type": "movie"},
    "indian_drama": {"name": "🇮🇳 Indian Drama",    "genreTopId": "4903182713986896328", "type": "series"},
    "top_series":   {"name": "📺 Top Series",       "genreTopId": "4741626294545400336", "type": "series"},
    "asian_series": {"name": "🌏 Asian Series",     "genreTopId": "1976033493293449744", "type": "series"},
    "western_tv":   {"name": "🇺🇸 Western TV",      "genreTopId": "3910636007619709856", "type": "series"},
    "anime":        {"name": "🎌 Anime",            "genreTopId": "8434602210994128512", "type": "series"},
}

HEADERS = {
    "Referer": "https://h5.aoneroom.com/",
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
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


async def fetch_moviebox_page(http_client: httpx.AsyncClient, genre_top_id: str, page: int = 1, per_page: int = 20):
    """Fetch a page of content from MovieBox's ranking-list API."""
    try:
        resp = await http_client.get(
            MOVIEBOX_API,
            params={"id": genre_top_id, "page": page, "perPage": per_page},
            headers=HEADERS,
            timeout=12,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            subjects = data.get("subjectList", [])
            pager = data.get("pager", {})
            return subjects, pager
    except Exception as e:
        print(f"[Catalog] MovieBox API error: {e}")
    return [], {}


async def resolve_to_imdb(http_client: httpx.AsyncClient, title: str, year: str) -> str | None:
    """Resolve a movie/show title to IMDB ID via TMDB."""
    try:
        # Clean title
        clean = title.strip()
        if not clean:
            return None

        # Search TMDB
        resp = await http_client.get(
            "https://api.themoviedb.org/3/search/movie",
            params={"api_key": TMDB_API_KEY, "query": clean, "year": year},
            timeout=8,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                tmdb_id = results[0]["id"]
                ext = await http_client.get(
                    f"https://api.themoviedb.org/3/movie/{tmdb_id}/external_ids",
                    params={"api_key": TMDB_API_KEY},
                    timeout=8,
                )
                if ext.status_code == 200:
                    imdb = ext.json().get("imdb_id")
                    if imdb:
                        return imdb

        # Fallback: without year
        resp2 = await http_client.get(
            "https://api.themoviedb.org/3/search/movie",
            params={"api_key": TMDB_API_KEY, "query": clean},
            timeout=8,
        )
        if resp2.status_code == 200:
            results2 = resp2.json().get("results", [])
            if results2:
                tmdb_id2 = results2[0]["id"]
                ext2 = await http_client.get(
                    f"https://api.themoviedb.org/3/movie/{tmdb_id2}/external_ids",
                    params={"api_key": TMDB_API_KEY},
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

    # Parse catalog section
    section = catalog_id.replace("moviebox_", "")
    catalog_info = MOVIEBOX_CATALOGS.get(section, MOVIEBOX_CATALOGS["trending"])

    http_client = request.app.state.http_client

    # Fetch from MovieBox API
    subjects, pager = await fetch_moviebox_page(http_client, catalog_info["genreTopId"], page=page)

    if not subjects:
        return JSONResponse({"metas": [], "cacheMaxAge": 1800})

    # Resolve titles to IMDB IDs
    metas = []
    for item in subjects:
        title = item.get("title", "")
        release_date = item.get("releaseDate", "")
        year = release_date[:4] if release_date else ""
        cover = item.get("cover", "")
        description = item.get("description", "")

        # Clean title
        name = title
        for suffix in [' Hindi', ' Tamil', ' Telugu', ' Spanish', ' French', ' German', ' Arabic', ' Dubbed']:
            if name.endswith(suffix):
                name = name[:-len(suffix)]

        imdb_id = await resolve_to_imdb(http_client, name, year)
        if not imdb_id:
            continue

        poster = f"https://api.ratingposterdb.com/t0-free-rpdb/imdb/poster-default/{imdb_id}.jpg"

        metas.append({
            "id": imdb_id,
            "type": type,
            "name": name.strip(),
            "releaseInfo": year,
            "poster": poster,
            "background": cover if cover else None,
            "description": description[:200] if description else f"From MovieBox — {catalog_info['name']}",
        })

    return JSONResponse({"metas": metas, "cacheMaxAge": 1800})
