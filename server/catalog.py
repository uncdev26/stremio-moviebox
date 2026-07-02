"""Pre-resolved MovieBox catalog — loads all content on startup, serves instantly."""

import json
import re
import asyncio
import time
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

TMDB_API_KEY = "e779f44db85aedbffe2dfcf252b372dc"
MOVIEBOX_API = "https://h5-api.aoneroom.com/wefeed-h5api-bff/ranking-list/content"
HEADERS = {
    "Referer": "https://h5.aoneroom.com/",
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
}

SECTIONS = {
    "trending":     {"name": "🔥 Trending",        "gid": "4516404531735022304", "type": "movie"},
    "cinema":       {"name": "🎬 Cinema",           "gid": "5692654647815587592", "type": "movie"},
    "hollywood":    {"name": "🇺🇸 Hollywood",       "gid": "8019599703232971616", "type": "movie"},
    "bollywood":    {"name": "🇮🇳 Bollywood",       "gid": "414907768299210008",  "type": "movie"},
    "south_indian": {"name": "🇮🇳 South Indian",    "gid": "3859721901924910512", "type": "movie"},
    "asian":        {"name": "🌏 Asian",            "gid": "5429170738815291968", "type": "movie"},
    "turkish":      {"name": "🇹🇷 Turkish",         "gid": "5177200225164885656", "type": "movie"},
    "top_series":   {"name": "📺 Top Series",       "gid": "4741626294545400336", "type": "series"},
    "indian_drama": {"name": "🇮🇳 Indian Drama",    "gid": "4903182713986896328", "type": "series"},
    "asian_series": {"name": "🌏 Asian Series",     "gid": "1976033493293449744", "type": "series"},
    "western_tv":   {"name": "🇺🇸 Western TV",      "gid": "3910636007619709856", "type": "series"},
    "anime":        {"name": "🎌 Anime",            "gid": "8434602210994128512", "type": "series"},
}

# Global cache
_catalog_cache = {}
_cache_time = 0
CACHE_TTL = 3600  # 1 hour


def clean_title(t: str) -> str:
    t = re.sub(r'\s*\[.*?\]\s*', '', t).strip()
    t = re.sub(r'\s*(CAM|HDCAM|HDTS|WEBRip|WEB-DL|BluRay|HDRip|DVDRip)\s*$', '', t, flags=re.I).strip()
    for s in [' Hindi', ' Tamil', ' Telugu', ' Spanish', ' French', ' German', ' Arabic', ' Dubbed', ' Dual Audio']:
        if t.lower().endswith(s.lower()): t = t[:-len(s)].strip()
    return t


async def fetch_all_pages(client, gid: str, max_pages: int = 10):
    """Fetch ALL pages from a MovieBox category."""
    all_items = []
    page = 1
    while page <= max_pages:
        try:
            r = await client.get(MOVIEBOX_API,
                params={"id": gid, "page": page, "perPage": 50},
                headers=HEADERS, timeout=12)
            if r.status_code != 200:
                break
            data = r.json().get("data", {})
            items = data.get("subjectList", [])
            if not items:
                break
            all_items.extend(items)
            has_more = data.get("pager", {}).get("hasMore", False)
            if not has_more:
                break
            page += 1
        except:
            break
    return all_items


async def resolve_batch(client, titles_years: list[tuple[str, str]]) -> list[str | None]:
    """Batch resolve titles to TMDB IDs."""
    async def resolve_one(title, year):
        try:
            r = await client.get("https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": title, "year": year}, timeout=8)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    return str(results[0]["id"])
            # Fallback without year
            r2 = await client.get("https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": title}, timeout=8)
            if r2.status_code == 200:
                results2 = r2.json().get("results", [])
                if results2:
                    return str(results2[0]["id"])
        except:
            pass
        return None

    # Run in parallel batches of 20
    results = []
    for i in range(0, len(titles_years), 20):
        batch = titles_years[i:i+20]
        batch_results = await asyncio.gather(*[resolve_one(t, y) for t, y in batch])
        results.extend(batch_results)
    return results


async def build_catalog(client, section_key: str, section_info: dict) -> list[dict]:
    """Build a resolved catalog for one section."""
    gid = section_info["gid"]
    item_type = section_info["type"]

    # Fetch all pages
    raw_items = await fetch_all_pages(client, gid)
    if not raw_items:
        return []

    # Clean titles and prepare for resolution
    titles_years = []
    for item in raw_items:
        title = clean_title(item.get("title", ""))
        year = (item.get("releaseDate") or "")[:4]
        titles_years.append((title, year))

    # Batch resolve to TMDB IDs
    tmdb_ids = await resolve_batch(client, titles_years)

    # Build metas
    metas = []
    for item, tmdb_id in zip(raw_items, tmdb_ids):
        if not tmdb_id:
            continue

        title = clean_title(item.get("title", ""))
        year = (item.get("releaseDate") or "")[:4]
        cover = item.get("cover", {})
        poster = cover.get("url") if isinstance(cover, dict) else None
        genre = item.get("genre", [])
        rating = item.get("imdbRatingValue")

        metas.append({
            "id": f"tmdb_{tmdb_id}",
            "type": item_type,
            "name": title,
            "releaseInfo": year,
            "poster": poster,
            "imdbRating": str(rating) if rating else None,
            "genres": genre if genre else None,
        })

    return metas


async def refresh_catalog():
    """Refresh all catalog sections."""
    global _catalog_cache, _cache_time

    import httpx
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15),
        limits=httpx.Limits(max_connections=30),
        follow_redirects=True,
    ) as client:
        # Build all sections in parallel
        tasks = {k: build_catalog(client, k, v) for k, v in SECTIONS.items()}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        new_cache = {}
        total = 0
        for key, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                print(f"[Catalog] Error building {key}: {result}")
                new_cache[key] = []
            else:
                new_cache[key] = result
                total += len(result)

        _catalog_cache = new_cache
        _cache_time = time.time()
        print(f"[Catalog] Refreshed: {total} total items across {len(SECTIONS)} sections")


@router.on_event("startup")
async def startup_refresh():
    """Pre-build catalog on startup."""
    asyncio.create_task(refresh_catalog())


# ─── Catalog endpoints ──────────────────────────────────────

@router.get("/{config}/catalog/{type}/{catalog_id}.json")
async def cat1(request: Request, config: str, type: str, catalog_id: str):
    return await handle(type, catalog_id)

@router.get("/catalog/{type}/{catalog_id}.json")
async def cat2(request: Request, type: str, catalog_id: str):
    return await handle(type, catalog_id)


async def handle(type: str, catalog_id: str):
    global _cache_time

    section = catalog_id.replace("moviebox_", "")

    # Check if cache needs refresh
    if time.time() - _cache_time > CACHE_TTL:
        asyncio.create_task(refresh_catalog())

    metas = _catalog_cache.get(section, [])

    if not metas and not _catalog_cache:
        # First request before cache is ready — build on-demand
        if section in SECTIONS:
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(15), follow_redirects=True) as client:
                metas = await build_catalog(client, section, SECTIONS[section])
                _catalog_cache[section] = metas

    return JSONResponse({"metas": metas, "cacheMaxAge": 3600})
