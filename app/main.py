"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.logging_config import setup_logging
from app.routers.media import router
from app.security.tokens import TokenManager
from app.services.streamer import StreamerService
from app.services.youtube import YouTubeService

logger = logging.getLogger("api.main")


async def _token_janitor(tokens: TokenManager, interval: int = 60) -> None:
    while True:
        await asyncio.sleep(interval)
        with contextlib.suppress(Exception):
            await tokens.purge_expired()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)

    app.state.tokens = TokenManager(
        ttl=settings.token_ttl,
        one_time=settings.one_time_tokens,
        token_bytes=settings.token_bytes,
    )
    app.state.youtube = YouTubeService(
        cache_ttl=settings.url_cache_ttl,
        max_concurrent=settings.max_extractions,
        video_max_height=settings.video_max_height,
        cookies_file=settings.cookies_file,
        proxy=settings.ytdlp_proxy,
    )
    app.state.streamer = StreamerService()
    await app.state.streamer.start()

    janitor = asyncio.create_task(_token_janitor(app.state.tokens))
    logger.info(
        "%s started (token_ttl=%ss, one_time=%s, api_key=%s)",
        settings.app_name, settings.token_ttl, settings.one_time_tokens,
        "enabled" if settings.api_key else "disabled",
    )
    try:
        yield
    finally:
        janitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await janitor
        await app.state.streamer.stop()
        logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,       # private API: no public swagger
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(router)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


app = create_app()
