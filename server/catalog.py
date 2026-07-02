"""Catalog endpoints using TMDB Discover API for country/genre browsing."""

import re
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

TMDB_API_KEY = "e779f44db85aedbffe2dfcf252b372dc"

# Country name → ISO code mapping
COUNTRY_CODES = {
    "United States": "US", "United Kingdom": "GB", "France": "FR",
    "Germany": "DE", "Italy": "IT", "Spain": "ES", "Russia": "RU",
    "India": "IN", "Japan": "JP", "Korea": "KR", "China": "CN",
    "Thailand": "TH", "Indonesia": "ID", "Philippines": "PH",
    "Pakistan": "PK", "Bangladesh": "BD", "Malaysia": "MY",
    "Egypt": "EG", "Saudi Arabia": "SA", "Nigeria": "NG",
    "South Africa": "ZA", "Kenya": "KE", "Morocco": "MA",
    "Iraq": "IQ", "Lebanon": "LB", "Syria": "SY", "Mexico": "MX",
    "Ivory Coast": "CI",
}

# Genre name → TMDB genre ID
GENRE_IDS = {
    "Action": 28, "Adventure": 12, "Animation": 16, "Comedy": 35,
    "Crime": 80, "Documentary": 99, "Drama": 18, "Family": 10751,
    "Fantasy": 14, "History": 36, "Horror": 27, "Music": 10402,
    "Mystery": 9648, "Romance": 10749, "Science Fiction": 878,
    "Thriller": 53, "War": 10752, "Western": 37,
}


async def fetch_tmdb_discover(
    http_client, type_: str, countries: list, genre: str, page: int = 1
):
    """Fetch content from TMDB Discover API."""
    params = {
        "api_key": TMDB_API_KEY,
        "sort_by": "popularity.desc",
        "page": page,
        "language": "en-US",
    }

    # Add country filter
    if countries and "All" not in countries:
        codes = [COUNTRY_CODES.get(c, c) for c in countries]
        params["with_origin_country"] = "|".join(codes)

    # Add genre filter
    if genre and genre != "All":
        genre_id = GENRE_IDS.get(genre)
        if genre_id:
            params["with_genres"] = genre_id

    url = f"https://api.themoviedb.org/3/discover/{type_}"
    try:
        resp = await http_client.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"results": []}


def parse_config(config_str: str) -> dict:
    import base64, json
    try:
        padding = 4 - (len(config_str) % 4)
        if padding != 4:
            config_str += "=" * padding
        decoded = base64.urlsafe_b64decode(config_str).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


@router.get("/{config}/catalog/{type}/{id}.json")
async def catalog_with_config(request: Request, config: str, type: str, id: str):
    return await handle_catalog(request, type, id, config)


@router.get("/catalog/{type}/{id}.json")
async def catalog_no_config(request: Request, type: str, id: str):
    return await handle_catalog(request, type, id, "")


async def handle_catalog(request: Request, type: str, id: str, config_str: str):
    """Return catalog of movies/shows based on country/genre config."""
    config = parse_config(config_str)

    countries = config.get("countries", ["All"])
    if isinstance(countries, str):
        countries = [countries]
    genre = config.get("genre", "All")

    # Get page from extra params
    page = int(request.query_params.get("page", "1"))

    data = await fetch_tmdb_discover(
        request.app.state.http_client, type, countries, genre, page
    )

    metas = []
    for item in data.get("results", []):
        tmdb_id = item.get("id")
        title = item.get("title") or item.get("name", "")
        year = (item.get("release_date") or item.get("first_air_date") or "")[:4]
        overview = item.get("overview", "")
        poster_path = item.get("poster_path")
        backdrop_path = item.get("backdrop_path")
        vote = item.get("vote_average", 0)

        # We need IMDB ID for Stremio — use tmdb: prefix
        meta_id = f"tmdb:{tmdb_id}"

        meta = {
            "id": meta_id,
            "type": type,
            "name": title,
            "releaseInfo": year,
            "poster": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
            "background": f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else None,
            "description": overview[:300] if overview else "",
        }
        metas.append(meta)

    return JSONResponse({"metas": metas, "cacheMaxAge": 3600})
