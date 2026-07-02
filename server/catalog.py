"""Catalog endpoints — MovieBox's full catalog with pagination."""

import json
import base64
import re
import asyncio
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

TMDB_API_KEY = "e779f44db85aedbffe2dfcf252b372dc"
MOVIEBOX_API = "https://h5-api.aoneroom.com/wefeed-h5api-bff/ranking-list/content"

# ALL MovieBox catalog sections from homepage
SECTIONS = {
    # Movies
    "trending":     {"name": "🔥 Trending Now",    "gid": "4516404531735022304", "type": "movie"},
    "cinema":       {"name": "🎬 Cinema",           "gid": "5692654647815587592", "type": "movie"},
    "hollywood":    {"name": "🇺🇸 Hollywood",       "gid": "8019599703232971616", "type": "movie"},
    "bollywood":    {"name": "🇮🇳 Bollywood",       "gid": "414907768299210008",  "type": "movie"},
    "south_indian": {"name": "🇮🇳 South Indian",    "gid": "3859721901924910512", "type": "movie"},
    "asian":        {"name": "🌏 Asian Movies",     "gid": "5429170738815291968", "type": "movie"},
    "turkish":      {"name": "🇹🇷 Turkish Drama",   "gid": "5177200225164885656", "type": "movie"},
    # Series
    "top_series":   {"name": "📺 Top Series",       "gid": "4741626294545400336", "type": "series"},
    "indian_drama": {"name": "🇮🇳 Indian Drama",    "gid": "4903182713986896328", "type": "series"},
    "asian_series": {"name": "🌏 Asian Series",     "gid": "1976033493293449744", "type": "series"},
    "western_tv":   {"name": "🇺🇸 Western TV",      "gid": "3910636007619709856", "type": "series"},
    "anime":        {"name": "🎌 Anime",            "gid": "8434602210994128512", "type": "series"},
}

HEADERS = {
    "Referer": "https://h5.aoneroom.com/",
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
}


def parse_config(s: str) -> dict:
    try:
        p = 4 - (len(s) % 4)
        if p != 4: s += "=" * p
        return json.loads(base64.urlsafe_b64decode(s))
    except: return {}


def clean_title(title: str) -> str:
    """Remove [Hindi], [CAM], quality markers etc."""
    t = re.sub(r'\s*\[.*?\]\s*', '', title).strip()
    t = re.sub(r'\s*\(.*?\)\s*$', '', t).strip()
    t = re.sub(r'\s*(CAM|HDCAM|HDTS|WEBRip|WEB-DL|BluRay|HDRip|DVDRip)\s*$', '', t, flags=re.I).strip()
    for s in [' Hindi', ' Tamil', ' Telugu', ' Spanish', ' French', ' German', ' Arabic', ' Dubbed', ' Dual Audio']:
        if t.lower().endswith(s.lower()):
            t = t[:-len(s)].strip()
    return t


async def fetch_page(client: httpx.AsyncClient, gid: str, page: int, per_page: int = 50):
    """Fetch one page from MovieBox."""
    try:
        r = await client.get(MOVIEBOX_API, params={"id": gid, "page": page, "perPage": per_page}, headers=HEADERS, timeout=12)
        if r.status_code == 200:
            d = r.json().get("data", {})
            return d.get("subjectList", []), d.get("pager", {})
    except: pass
    return [], {}


async def resolve_title(client: httpx.AsyncClient, title: str, year: str) -> str | None:
    """Title → TMDB → IMDB ID. Returns tt... or None."""
    try:
        r = await client.get("https://api.themoviedb.org/3/search/movie",
            params={"api_key": TMDB_API_KEY, "query": title, "year": year}, timeout=8)
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                tid = results[0]["id"]
                e = await client.get(f"https://api.themoviedb.org/3/movie/{tid}/external_ids",
                    params={"api_key": TMDB_API_KEY}, timeout=8)
                if e.status_code == 200:
                    imdb = e.json().get("imdb_id")
                    if imdb: return imdb
        # Fallback without year
        r2 = await client.get("https://api.themoviedb.org/3/search/movie",
            params={"api_key": TMDB_API_KEY, "query": title}, timeout=8)
        if r2.status_code == 200:
            results2 = r2.json().get("results", [])
            if results2:
                tid2 = results2[0]["id"]
                e2 = await client.get(f"https://api.themoviedb.org/3/movie/{tid2}/external_ids",
                    params={"api_key": TMDB_API_KEY}, timeout=8)
                if e2.status_code == 200:
                    return e2.json().get("imdb_id")
    except: pass
    return None


@router.get("/{config}/catalog/{type}/{catalog_id}.json")
async def cat_with_config(request: Request, config: str, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, config)

@router.get("/catalog/{type}/{catalog_id}.json")
async def cat_no_config(request: Request, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, "")


async def handle_catalog(request: Request, type: str, catalog_id: str, config_str: str):
    skip = int(request.query_params.get("skip", "0"))
    per_page = 50
    page = (skip // per_page) + 1

    section = catalog_id.replace("moviebox_", "")
    info = SECTIONS.get(section, SECTIONS["trending"])

    client = request.app.state.http_client
    subjects, pager = await fetch_page(client, info["gid"], page, per_page)

    if not subjects:
        return JSONResponse({"metas": [], "cacheMaxAge": 1800})

    # Resolve ALL titles to IMDB in parallel (fast!)
    tasks = []
    for item in subjects:
        title = clean_title(item.get("title", ""))
        year = (item.get("releaseDate") or "")[:4]
        tasks.append(resolve_title(client, title, year))

    imdb_ids = await asyncio.gather(*tasks)

    metas = []
    for item, imdb_id in zip(subjects, imdb_ids):
        if not imdb_id:
            continue
        title = clean_title(item.get("title", ""))
        year = (item.get("releaseDate") or "")[:4]
        cover = item.get("cover", {})
        cover_url = cover.get("url") if isinstance(cover, dict) else cover
        desc = item.get("description", "")
        genre = item.get("genre", [])
        rating = item.get("imdbRatingValue", 0)

        metas.append({
            "id": imdb_id,
            "type": type,
            "name": title,
            "releaseInfo": year,
            "poster": f"https://api.ratingposterdb.com/t0-free-rpdb/imdb/poster-default/{imdb_id}.jpg",
            "background": cover_url if isinstance(cover_url, str) else None,
            "description": desc[:300] if desc else "",
            "imdbRating": str(rating) if rating else None,
            "genres": genre if genre else None,
        })

    has_more = pager.get("hasMore", False) if isinstance(pager, dict) else getattr(pager, 'hasMore', False)

    return JSONResponse({
        "metas": metas,
        "cacheMaxAge": 1800,
    })
