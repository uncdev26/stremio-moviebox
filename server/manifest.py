from pydantic import BaseModel

RPDB_KEY = "t0-free-rpdb"


class CatalogExtra(BaseModel):
    name: str
    isRequired: bool = False
    options: list[str] = []
    optionsLimit: int = 1


class Catalog(BaseModel):
    id: str
    type: str
    name: str
    extra: list[CatalogExtra] = []


class Manifest(BaseModel):
    id: str
    version: str
    name: str
    description: str
    resources: list[str]
    types: list[str]
    catalogs: list
    idPrefixes: list[str]
    logo: str | None = None


def get_manifest() -> Manifest:
    return Manifest(
        id="com.moviebox.addon",
        version="1.0.0",
        name="MovieBox",
        description="Universal streaming with RPDB ratings. Multi-language, multi-country, genre filter.",
        resources=["stream", "catalog"],
        types=["movie", "series"],
        catalogs=[
            {
                "id": "moviebox_catalog",
                "type": "movie",
                "name": "MovieBox",
                "extra": [
                    {"name": "genre", "options": [
                        "Action", "Adventure", "Animation", "Comedy", "Crime",
                        "Documentary", "Drama", "Family", "Fantasy", "History",
                        "Horror", "Mystery", "Romance", "Science Fiction", "Thriller", "War"
                    ], "optionsLimit": 1},
                    {"name": "skip", "options": [], "optionsLimit": 1},
                ],
            },
            {
                "id": "moviebox_catalog_series",
                "type": "series",
                "name": "MovieBox Series",
                "extra": [
                    {"name": "genre", "options": [
                        "Action", "Animation", "Comedy", "Crime", "Drama",
                        "Family", "Mystery", "Romance", "Science Fiction"
                    ], "optionsLimit": 1},
                    {"name": "skip", "options": [], "optionsLimit": 1},
                ],
            },
        ],
        idPrefixes=["tt", "tmdb:"],
    )
