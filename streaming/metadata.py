import httpx


async def resolve_imdb_id(
    http_client: httpx.AsyncClient, type_: str, imdb_id: str
) -> dict:
    url = f"https://v3-cinemeta.strem.io/meta/{type_}/{imdb_id}.json"
    try:
        response = await http_client.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get("meta", {})
    except Exception:
        pass
    return {}
