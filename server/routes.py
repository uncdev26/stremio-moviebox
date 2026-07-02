import re
import base64
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from server.manifest import Manifest, get_manifest, RPDB_KEY

router = APIRouter()

TMDB_KEY = "e779f44db85aedbffe2dfcf252b372dc"


def parse_config(config_str: str) -> dict:
    try:
        padding = 4 - (len(config_str) % 4)
        if padding != 4:
            config_str += "=" * padding
        decoded = base64.urlsafe_b64decode(config_str).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


def classify_quality(text: str) -> str:
    t = text.lower()
    if "2160" in t or "4k" in t or "uhd" in t: return "4k"
    if "1080" in t or "fhd" in t: return "1080p"
    if "720" in t or "hd" in t: return "720p"
    return "other"


# ─── MANIFEST ─────────────────────────────────────────────────

@router.get("/{config}/manifest.json")
async def manifest_with_config(request: Request, config: str) -> Manifest:
    manifest = get_manifest()
    base = str(request.base_url)
    manifest.logo = base + "logo.png"
    return manifest


@router.get("/manifest.json")
async def manifest_no_config(request: Request) -> Manifest:
    manifest = get_manifest()
    base = str(request.base_url)
    manifest.logo = base + "logo.png"
    return manifest


# ─── META ─────────────────────────────────────────────────────

@router.get("/meta/{type}/{id}.json")
async def meta_endpoint(request: Request, type: str, id: str):
    """Return metadata for a single item."""
    import httpx as _httpx
    try:
        tmdb_id = None
        if id.startswith("tmdb_"):
            tmdb_id = id.replace("tmdb_", "")
        elif id.startswith("tt"):
            async with _httpx.AsyncClient(timeout=_httpx.Timeout(10), follow_redirects=True) as c:
                r = await c.get(f"https://api.themoviedb.org/3/find/{id}",
                    params={"api_key": TMDB_KEY, "external_source": "imdb_id"}, timeout=8)
                if r.status_code == 200:
                    results = r.json().get("movie_results", []) or r.json().get("tv_results", [])
                    if results:
                        tmdb_id = str(results[0]["id"])

        if not tmdb_id:
            return JSONResponse({"meta": {"id": id, "type": type, "name": "Unknown"}})

        tmdb_type = "tv" if type == "series" else "movie"
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(10), follow_redirects=True) as c:
            r = await c.get(f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_id}",
                params={"api_key": TMDB_KEY, "language": "en-US"}, timeout=8)
            if r.status_code == 200:
                d = r.json()
                title = d.get("title") or d.get("name", "")
                year = (d.get("release_date") or d.get("first_air_date") or "")[:4]
                poster = d.get("poster_path")
                backdrop = d.get("backdrop_path")
                return JSONResponse({"meta": {
                    "id": id, "type": type, "name": title, "releaseInfo": year,
                    "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                    "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                    "description": (d.get("overview") or "")[:500],
                    "genres": [g["name"] for g in d.get("genres", [])],
                    "imdbRating": str(round(d.get("vote_average", 0), 1)) if d.get("vote_average") else None,
                }})
    except Exception as e:
        print(f"[Meta] Error: {e}")

    return JSONResponse({"meta": {"id": id, "type": type, "name": "Unknown"}})


# ─── STREAM ───────────────────────────────────────────────────

@router.get("/{config}/stream/{type}/{id}.json")
async def stream_with_config(request: Request, config: str, type: str, id: str):
    return await handle_stream(request, type, id, config)


@router.get("/stream/{type}/{id}.json")
async def stream_no_config(request: Request, type: str, id: str):
    return await handle_stream(request, type, id, "")


async def handle_stream(request: Request, type: str, id: str, config_str: str):
    config = parse_config(config_str)
    min_res = config.get("resolution", "all")
    pref_langs = config.get("languages", [config.get("language", "all")])
    if isinstance(pref_langs, str):
        pref_langs = [pref_langs]
    layout = config.get("layout", "cinematic")

    LANG_MAP = {
        "en": "english", "hi": "hindi", "es": "spanish", "fr": "french",
        "de": "german", "it": "italian", "pt": "portuguese", "ru": "russian",
        "ja": "japanese", "ko": "korean", "zh": "chinese", "ar": "arabic",
        "tr": "turkish", "th": "thai", "pl": "polish", "ta": "tamil", "te": "telugu",
    }
    pref_lang_names = [LANG_MAP.get(l, l) for l in pref_langs]
    all_langs = "all" in pref_langs

    platform = config.get("platform", "auto")
    if platform == "auto":
        ua = (request.headers.get("user-agent") or "").lower()
        if "android tv" in ua or "fire tv" in ua: platform = "tv"
        elif "android" in ua or "iphone" in ua: platform = "mobile"
        else: platform = "desktop"
    fast_mode = platform in ("tv", "mobile")

    parts = id.split(":")
    imdb_id = parts[0]
    season = 1
    episode = 1

    # Handle tmdb_ prefix IDs
    if id.startswith("tmdb_"):
        tmdb_num = id.replace("tmdb_", "")
        try:
            tmdb_type = "tv" if type == "series" else "movie"
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=_httpx.Timeout(10), follow_redirects=True) as c:
                ext = await c.get(f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_num}/external_ids",
                    params={"api_key": TMDB_KEY}, timeout=10)
                if ext.status_code == 200:
                    imdb_id = ext.json().get("imdb_id", "")
        except:
            pass

    # Handle tmdb: prefix
    elif imdb_id.startswith("tmdb:") or (len(parts) > 1 and parts[0] == "tmdb"):
        tmdb_num = parts[1] if parts[0] == "tmdb" else imdb_id.replace("tmdb:", "")
        try:
            tmdb_type = "tv" if type == "series" else "movie"
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=_httpx.Timeout(10), follow_redirects=True) as c:
                ext = await c.get(f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_num}/external_ids",
                    params={"api_key": TMDB_KEY}, timeout=10)
                if ext.status_code == 200:
                    imdb_id = ext.json().get("imdb_id", "")
        except:
            pass

    if type == "series" and len(parts) >= 3:
        season = int(parts[1])
        episode = int(parts[2])

    # Resolve IMDB to movie info via TMDB
    meta = {}
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(10), follow_redirects=True) as c:
            r = await c.get(f"https://api.themoviedb.org/3/find/{imdb_id}",
                params={"api_key": TMDB_KEY, "external_source": "imdb_id"}, timeout=10)
            if r.status_code == 200:
                results = r.json().get("movie_results", []) or r.json().get("tv_results", [])
                if results:
                    meta = results[0]
    except:
        pass

    title = meta.get("title") or meta.get("name") or ""
    year = (meta.get("release_date") or meta.get("first_air_date") or "")[:4]

    if not title:
        return JSONResponse({"streams": []})

    # Fetch streams from MovieBox
    from streaming.provider import find_fast_matches, find_all_matches, extract_streams

    if fast_mode:
        matches = await find_fast_matches(title, year, is_movie=(type == "movie"))
    else:
        matches = await find_all_matches(title, year, is_movie=(type == "movie"))

    if not matches:
        return JSONResponse({"streams": []})

    stream_results = await extract_streams(matches, type == "movie", season, episode)

    def lang_matches(audio_lang):
        if not audio_lang:
            return "orig" in pref_langs
        al = audio_lang.lower()
        for lp in pref_lang_names:
            if lp in al: return True
        for lp in pref_langs:
            if lp != "all" and lp != "orig" and lp in al: return True
        return False

    def sort_key(x):
        res = getattr(x["download"], "resolution", 0)
        lang_match = 0
        audio_lang = x.get("audio_lang")
        if not all_langs and lang_matches(audio_lang):
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
        if base_dl_url in seen_urls: continue
        seen_urls.add(base_dl_url)

        resolution = getattr(dl, "resolution", 0)
        size = getattr(dl, "size", 0)

        if min_res == "4k" and resolution < 2160: continue
        elif min_res == "1080p" and resolution < 1080: continue
        elif min_res == "720p" and resolution < 720: continue

        if not all_langs and not lang_matches(audio_lang): continue

        res_text = f"{resolution}p" if resolution else "?"
        size_text = f"{size / (1024*1024):.0f} MB" if size else ""
        lang_text = f"🔊 {audio_lang}" if audio_lang else ""

        desc_parts = [f"🎬 {res_text}"]
        if size_text: desc_parts[0] += f" • 💾 {size_text}"
        if lang_text: desc_parts.append(lang_text)
        if subtitle_langs: desc_parts.append(f"💬 {', '.join(subtitle_langs[:3])}")
        desc = "\n".join(desc_parts)

        is_hls = ".m3u8" in url_str
        is_mp4 = ".mp4" in url_str

        streams.append({
            "name": "MovieBox",
            "title": desc,
            "url": url_str,
            "poster": f"https://api.ratingposterdb.com/{RPDB_KEY}/imdb/poster-default/{imdb_id}.jpg",
            "behaviorHints": {
                "notWebReady": True,
                "filename": url_str.split("/")[-1].split("?")[0] if "/" in url_str else None,
                "proxyHeaders": {
                    "request": {
                        "Referer": "https://fmoviesunblocked.net/",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    }
                },
            },
        })

    return JSONResponse({"streams": streams})
