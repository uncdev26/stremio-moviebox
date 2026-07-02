import re
import base64
import json

from fastapi import APIRouter, Request

from server.manifest import Manifest, get_manifest, RPDB_KEY

router = APIRouter()


def parse_config(config_str: str) -> dict:
    try:
        padding = 4 - (len(config_str) % 4)
        if padding != 4:
            config_str += "=" * padding
        decoded = base64.urlsafe_b64decode(config_str).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


# ─── META ENDPOINT ────────────────────────────────────────────
@router.get("/meta/{type}/{id:path}.json")
async def meta_endpoint(request: Request, type: str, id: str):
    """Return metadata for a single item. Handles tmdb_ and tt prefixes."""
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(10), follow_redirects=True) as client:
            tmdb_id = None

            if id.startswith("tmdb_"):
                tmdb_id = id.replace("tmdb_", "")
            elif id.startswith("tt"):
                r = await client.get(f"https://api.themoviedb.org/3/find/{id}",
                    params={"api_key": "e779f44db85aedbffe2dfcf252b372dc", "external_source": "imdb_id"},
                    timeout=8)
                if r.status_code == 200:
                    results = r.json().get("movie_results", []) or r.json().get("tv_results", [])
                    if results:
                        tmdb_id = str(results[0]["id"])

            if not tmdb_id:
                return JSONResponse({"meta": {"id": id, "type": type, "name": "Unknown"}})

            tmdb_type = "tv" if type == "series" else "movie"
            r = await client.get(f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_id}",
                params={"api_key": "e779f44db85aedbffe2dfcf252b372dc", "language": "en-US"},
                timeout=8)
            if r.status_code == 200:
                d = r.json()
                title = d.get("title") or d.get("name", "")
                year = (d.get("release_date") or d.get("first_air_date") or "")[:4]
                overview = d.get("overview", "")
                poster = d.get("poster_path")
                backdrop = d.get("backdrop_path")
                genres = [g["name"] for g in d.get("genres", [])]
                rating = d.get("vote_average")

                return JSONResponse({"meta": {
                    "id": id, "type": type, "name": title, "releaseInfo": year,
                    "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                    "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                    "description": overview[:500] if overview else "",
                    "genres": genres,
                    "imdbRating": str(round(rating, 1)) if rating else None,
                }})
    except Exception as e:
        print(f"[Meta] Error: {e}")

    return JSONResponse({"meta": {"id": id, "type": type, "name": "Unknown"}})

@router.get("/{config}/manifest.json")
async def manifest_endpoint(request: Request, config: str) -> Manifest:
    manifest = get_manifest()
    base = str(request.base_url)
    manifest.logo = base + "logo.png"
    return manifest


@router.get("/manifest.json")
async def manifest_endpoint_no_config(request: Request) -> Manifest:
    manifest = get_manifest()
    manifest.logo = str(request.base_url) + "logo.png"
    return manifest


import asyncio
import re
from typing import Annotated
from urllib.parse import quote

from fastapi import HTTPException, Path

from streaming.helpers import (
    generate_stream_description,
    generate_stream_title,
    get_stream_filename,
)
from streaming.metadata import resolve_imdb_id
from streaming.provider import extract_streams, find_all_matches, find_fast_matches


@router.get("/{config}/stream/{type}/{id}.json")
async def stream_endpoint_with_config(
    request: Request,
    config: str,
    type: Annotated[str, Path(...)],
    id: Annotated[str, Path(...)],
):
    return await handle_stream(request, type, id, config)


@router.get("/stream/{type}/{id}.json")
async def stream_endpoint(
    request: Request,
    type: Annotated[str, Path(...)],
    id: Annotated[str, Path(...)],
):
    return await handle_stream(request, type, id, "")


def detect_platform(request: Request) -> str:
    """Detect Stremio client platform from User-Agent."""
    ua = (request.headers.get("user-agent") or "").lower()
    if "android tv" in ua or "fire tv" in ua or "stremio/tv" in ua:
        return "tv"
    elif "android" in ua or "iphone" in ua or "ipad" in ua or "mobile" in ua:
        return "mobile"
    return "desktop"

async def handle_stream(request: Request, type: str, id: str, config_str: str):
    if type not in ["movie", "series"]:
        raise HTTPException(status_code=404, detail="Unsupported type")

    config = parse_config(config_str)
    min_res = config.get("resolution", "all")
    # Support both old "language" string and new "languages" array
    pref_langs = config.get("languages", [config.get("language", "all")])
    if isinstance(pref_langs, str):
        pref_langs = [pref_langs]
    pref_countries = config.get("countries", ["All"])
    if isinstance(pref_countries, str):
        pref_countries = [pref_countries]
    pref_genre = config.get("genre", "All")
    layout = config.get("layout", "cinematic")

    # Map language codes to names for matching
    LANG_MAP = {
        "en": "english", "hi": "hindi", "es": "spanish", "fr": "french",
        "de": "german", "it": "italian", "pt": "portuguese", "ru": "russian",
        "ja": "japanese", "ko": "korean", "zh": "chinese", "ar": "arabic",
        "tr": "turkish", "th": "thai", "pl": "polish", "nl": "dutch",
        "sv": "swedish", "ta": "tamil", "te": "telugu", "ml": "malayalam",
    }
    pref_lang_names = [LANG_MAP.get(l, l) for l in pref_langs]
    all_langs = "all" in pref_langs

    # Platform-aware speed optimization
    platform = detect_platform(request)
    # Config can override auto-detection
    config_platform = config.get("platform", "auto")
    if config_platform and config_platform != "auto":
        platform = config_platform
    fast_mode = platform in ("tv", "mobile")

    parts = id.split(":")
    imdb_id = parts[0]
    season = 1
    episode = 1

    # Handle tmdb_ prefix IDs from pre-resolved catalog
    if id.startswith("tmdb_"):
        tmdb_num = id.replace("tmdb_", "")
        try:
            tmdb_type = "tv" if type == "series" else "movie"
            ext = await request.app.state.http_client.get(
                f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_num}/external_ids",
                params={"api_key": "e779f44db85aedbffe2dfcf252b372dc"},
                timeout=10,
            )
            if ext.status_code == 200:
                imdb_id = ext.json().get("imdb_id", "")
        except Exception:
            pass

    # Handle tmdb: prefix IDs
    elif imdb_id.startswith("tmdb:") or (len(parts) > 1 and parts[0] == "tmdb"):
        tmdb_num = parts[1] if parts[0] == "tmdb" else imdb_id.replace("tmdb:", "")
        try:
            tmdb_type = "tv" if type == "series" else "movie"
            ext = await request.app.state.http_client.get(
                f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_num}/external_ids",
                params={"api_key": "e779f44db85aedbffe2dfcf252b372dc"},
                timeout=10,
            )
            if ext.status_code == 200:
                imdb_id = ext.json().get("imdb_id", "")
        except Exception:
            pass

    if type == "series" and len(parts) >= 3:
        season = int(parts[1])
        episode = int(parts[2])

    meta = await resolve_imdb_id(request.app.state.http_client, type, imdb_id)
    title = meta.get("name")

    if not title:
        return {"streams": []}

    year_match = re.search(
        r"\d{4}", str(meta.get("releaseInfo", ""))
    ) or re.search(r"\d{4}", str(meta.get("year", "")))
    year = year_match.group(0) if year_match else ""

    if fast_mode:
        # FAST MODE: single API, fewer results, faster
        matches = await find_fast_matches(title, year, is_movie=(type == "movie"))
    else:
        matches = await find_all_matches(title, year, is_movie=(type == "movie"))

    if not matches:
        return {"streams": []}

    stream_results = await extract_streams(
        matches, type == "movie", season, episode
    )

    def lang_matches(audio_lang):
        """Check if audio_lang matches any of the preferred languages."""
        if not audio_lang:
            return "orig" in pref_langs
        al = audio_lang.lower()
        for lp in pref_lang_names:
            if lp in al:
                return True
        for lp in pref_langs:
            if lp != "all" and lp != "orig" and lp in al:
                return True
        return False

    def sort_key(x):
        res = getattr(x["download"], "resolution", 0)
        lang_match = 0
        audio_lang = x.get("audio_lang")
        if not all_langs:
            if lang_matches(audio_lang):
                lang_match = 1
        return (lang_match, res)

    stream_results.sort(key=sort_key, reverse=True)

    streams = []
    seen_urls = set()

    for stream_data in stream_results:
        dl = stream_data["download"]
        audio_lang = stream_data["audio_lang"]
        subtitle_langs = stream_data["subtitle_langs"]

        url_str = str(dl.url)
        base_dl_url = url_str.split("?")[0] if "?" in url_str else url_str
        if base_dl_url in seen_urls:
            continue
        seen_urls.add(base_dl_url)

        resolution = getattr(dl, "resolution", 0)
        size = getattr(dl, "size", 0)

        if min_res == "4k" and resolution < 2160:
            continue
        elif min_res == "1080p" and resolution < 1080:
            continue
        elif min_res == "720p" and resolution < 720:
            continue

        if not all_langs:
            if not lang_matches(audio_lang):
                continue

        filename = get_stream_filename(url_str)
        audio_langs_display = [audio_lang] if audio_lang else None

        desc = generate_stream_description(
            resolution,
            size,
            audio_langs=audio_langs_display,
            subtitle_langs=subtitle_langs if subtitle_langs else None,
        )

        if layout == "torrentio":
            desc = desc.replace("\n", " | ")
        elif layout == "badges":
            desc = f"🎥 {resolution}p | 🔊 {audio_lang or 'Unknown'}\n{desc}"

        streams.append(
            {
                "name": "MovieBox",
                "title": desc,
                "url": url_str,
                "poster": f"https://api.ratingposterdb.com/{RPDB_KEY}/imdb/poster-default/{imdb_id}.jpg",
                "behaviorHints": {
                    "notWebReady": True,
                    "filename": filename,
                    "proxyHeaders": {
                        "request": {
                            "Referer": "https://fmoviesunblocked.net/",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        }
                    },
                },
            }
        )

    return {"streams": streams}



