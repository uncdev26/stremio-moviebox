from pydantic import BaseModel


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


RPDB_KEY = "t0-free-rpdb"

def get_manifest() -> Manifest:
    return Manifest(
        id="com.moviebox.addon",
        version="1.0.0",
        name="MovieBox",
        description="Universal streaming with RPDB ratings. Multi-language, multi-country, genre filter.",
        resources=["stream"],
        types=["movie", "series"],
        catalogs=[],
        idPrefixes=["tt"],
    )
