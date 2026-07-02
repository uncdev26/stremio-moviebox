"""Simple catalog — direct MovieBox API, no TMDB resolution, instant loading."""

import json
import base64
import re
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

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


def parse_config(s: str) -> dict:
    try:
        p = 4 - (len(s) % 4)
        if p != 4: s += "=" * p
        return json.loads(base64.urlsafe_b64decode(s))
    except: return {}


def clean_title(t: str) -> str:
    t = re.sub(r'\s*\[.*?\]\s*', '', t).strip()
    t = re.sub(r'\s*(CAM|HDCAM|HDTS|WEBRip|WEB-DL|BluRay)\s*$', '', t, flags=re.I).strip()
    for s in [' Hindi', ' Tamil', ' Telugu', ' Dubbed']:
        if t.lower().endswith(s.lower()): t = t[:-len(s)].strip()
    return t


@router.get("/{config}/catalog/{type}/{catalog_id}.json")
async def cat1(request: Request, config: str, type: str, catalog_id: str):
    return await handle(request, type, catalog_id)

@router.get("/catalog/{type}/{catalog_id}.json")
async def cat2(request: Request, type: str, catalog_id: str):
    return await handle(request, type, catalog_id)


async def handle(request: Request, type: str, catalog_id: str):
    section = catalog_id.replace("moviebox_", "")
    info = SECTIONS.get(section, SECTIONS["trending"])

    skip = int(request.query_params.get("skip", "0"))
    per_page = 50
    page = (skip // per_page) + 1

    client = request.app.state.http_client

    try:
        r = await client.get(MOVIEBOX_API,
            params={"id": info["gid"], "page": page, "perPage": per_page},
            headers=HEADERS, timeout=12)
        data = r.json().get("data", {}) if r.status_code == 200 else {}
        subjects = data.get("subjectList", [])
    except:
        subjects = []

    metas = []
    for item in subjects:
        title = clean_title(item.get("title", ""))
        year = (item.get("releaseDate") or "")[:4]
        cover = item.get("cover", {})
        cover_url = cover.get("url") if isinstance(cover, dict) else str(cover) if cover else None
        desc = item.get("description", "")
        genre = item.get("genre", [])
        rating = item.get("imdbRatingValue")
        sid = item.get("subjectId", "")

        metas.append({
            "id": f"mb:{sid}",
            "type": type,
            "name": title,
            "releaseInfo": year,
            "poster": cover_url,
            "background": cover_url,
            "description": desc[:300] if desc else "",
            "imdbRating": str(rating) if rating else None,
            "genres": genre if genre else None,
        })

    return JSONResponse({"metas": metas, "cacheMaxAge": 3600})
