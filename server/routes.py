import base64
import json

from fastapi import APIRouter, Request

from server.manifest import Manifest, get_manifest

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
    pref_lang = config.get("language", "all")
    layout = config.get("layout", "cinematic")

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

    def sort_key(x):
        res = getattr(x["download"], "resolution", 0)
        lang_match = 0
        audio_lang = x.get("audio_lang")
        if pref_lang != "all":
            if pref_lang == "orig" and not audio_lang:
                lang_match = 1
            elif (
                pref_lang != "orig"
                and audio_lang
                and pref_lang.lower() in audio_lang.lower()
            ):
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

        if pref_lang != "all":
            if pref_lang == "orig" and audio_lang:
                continue
            elif pref_lang != "orig":
                if not audio_lang or pref_lang.lower() not in audio_lang.lower():
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
