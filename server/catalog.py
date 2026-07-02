"""MovieBox catalog — pre-resolved, NoTorrent format."""

import json
import re
import asyncio
import time
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

TMDB_API_KEY = "e779f44db85aedbffe2dfcf252b372dc"
MOVIEBOX_API = "https://h5-api.aoneroom.com/wefeed-h5api-bff/ranking-list/content"
HEADERS = {"Referer": "https://h5.aoneroom.com/", "User-Agent": "Mozilla/5.0"}

SECTIONS = {
    "trending":     {"name": "🔥 Trending",     "gid": "4516404531735022304", "type": "movie"},
    "cinema":       {"name": "🎬 Cinema",        "gid": "5692654647815587592", "type": "movie"},
    "hollywood":    {"name": "🇺🇸 Hollywood",    "gid": "8019599703232971616", "type": "movie"},
    "bollywood":    {"name": "🇮🇳 Bollywood",    "gid": "414907768299210008",  "type": "movie"},
    "south_indian": {"name": "🇮🇳 South Indian", "gid": "3859721901924910512", "type": "movie"},
    "asian":        {"name": "🌏 Asian",         "gid": "5429170738815291968", "type": "movie"},
    "turkish":      {"name": "🇹🇷 Turkish",      "gid": "5177200225164885656", "type": "movie"},
    "top_series":   {"name": "📺 Top Series",    "gid": "4741626294545400336", "type": "series"},
    "indian_drama": {"name": "🇮🇳 Indian Drama", "gid": "4903182713986896328", "type": "series"},
    "asian_series": {"name": "🌏 Asian Series",  "gid": "1976033493293449744", "type": "series"},
    "western_tv":   {"name": "🇺🇸 Western TV",   "gid": "3910636007619709856", "type": "series"},
    "anime":        {"name": "🎌 Anime",         "gid": "8434602210994128512", "type": "series"},
}

_cache = {}
_cache_time = 0


def clean_title(t):
    t = re.sub(r'\s*\[.*?\]\s*', '', t).strip()
    t = re.sub(r'\s*(CAM|HDCAM|HDTS|WEBRip|WEB-DL|BluRay)\s*$', '', t, flags=re.I).strip()
    for s in [' Hindi', ' Tamil', ' Telugu', ' Dubbed']:
        if t.lower().endswith(s.lower()): t = t[:-len(s)].strip()
    return t


async def resolve_batch(client, titles_years):
    async def one(title, year):
        try:
            r = await client.get("https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": title, "year": year}, timeout=8)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results: return str(results[0]["id"])
            r2 = await client.get("https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": title}, timeout=8)
            if r2.status_code == 200:
                results2 = r2.json().get("results", [])
                if results2: return str(results2[0]["id"])
        except: pass
        return None
    results = []
    for i in range(0, len(titles_years), 20):
        batch = titles_years[i:i+20]
        results.extend(await asyncio.gather(*[one(t, y) for t, y in batch]))
    return results


async def build_section(client, gid, item_type):
    all_items = []
    page = 1
    while page <= 10:
        try:
            r = await client.get(MOVIEBOX_API, params={"id": gid, "page": page, "perPage": 50}, headers=HEADERS, timeout=12)
            if r.status_code != 200: break
            data = r.json().get("data", {})
            items = data.get("subjectList", [])
            if not items: break
            all_items.extend(items)
            if not data.get("pager", {}).get("hasMore", False): break
            page += 1
        except: break

    if not all_items: return []

    ty = [(clean_title(i.get("title", "")), (i.get("releaseDate") or "")[:4]) for i in all_items]
    tmdb_ids = await resolve_batch(client, ty)

    # Resolve TMDB IDs → IMDB IDs (so Stremio/Cinemeta can find metadata)
    async def tmdb_to_imdb(tid):
        try:
            r = await client.get(f"https://api.themoviedb.org/3/movie/{tid}/external_ids",
                params={"api_key": TMDB_API_KEY}, timeout=8)
            if r.status_code == 200:
                return r.json().get("imdb_id")
        except: pass
        return None

    imdb_ids = []
    for i in range(0, len(tmdb_ids), 20):
        batch = tmdb_ids[i:i+20]
        imdb_ids.extend(await asyncio.gather(*[tmdb_to_imdb(t) for t in batch]))

    metas = []
    for item, tid, imdb in zip(all_items, tmdb_ids, imdb_ids):
        if not imdb: continue
        cover = item.get("cover", {})
        poster = cover.get("url") if isinstance(cover, dict) else None
        metas.append({
            "id": imdb,
            "type": item_type,
            "name": clean_title(item.get("title", "")),
            "poster": poster,
        })

    return metas


async def refresh():
    global _cache, _cache_time
    async with httpx.AsyncClient(timeout=httpx.Timeout(15), follow_redirects=True) as client:
        tasks = {k: build_section(client, v["gid"], v["type"]) for k, v in SECTIONS.items()}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        new = {}
        total = 0
        for k, r in zip(tasks.keys(), results):
            if isinstance(r, Exception):
                new[k] = []
            else:
                new[k] = r
                total += len(r)
        _cache = new
        _cache_time = time.time()
        print(f"[Catalog] Built: {total} items across {len(SECTIONS)} sections")


@router.on_event("startup")
async def startup():
    asyncio.create_task(refresh())


@router.get("/{config}/catalog/{type}/{catalog_id}.json")
async def cat1(request: Request, config: str, type: str, catalog_id: str):
    return await handle(catalog_id)

@router.get("/catalog/{type}/{catalog_id}.json")
async def cat2(request: Request, type: str, catalog_id: str):
    return await handle(catalog_id)


async def handle(catalog_id):
    section = catalog_id.replace("moviebox_", "")
    if time.time() - _cache_time > 3600:
        asyncio.create_task(refresh())
    metas = _cache.get(section, [])
    if not metas and not _cache and section in SECTIONS:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15), follow_redirects=True) as client:
            metas = await build_section(client, SECTIONS[section]["gid"], SECTIONS[section]["type"])
            _cache[section] = metas
    return JSONResponse({"metas": metas})
