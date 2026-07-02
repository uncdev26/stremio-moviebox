from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from server.routes import router as main_router
from server.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.REQUEST_TIMEOUT),
        limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
        follow_redirects=True,
    )
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="MovieBox Stremio Addon", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(main_router)


@app.get("/")
async def root():
    return RedirectResponse(url="/configure/")


app.mount("/configure", StaticFiles(directory="web", html=True), name="web")


@app.get("/logo.png")
async def get_logo():
    return FileResponse("assets/logo.png", media_type="image/png")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server.main:app", host=settings.HOST, port=settings.PORT, reload=True
    )
