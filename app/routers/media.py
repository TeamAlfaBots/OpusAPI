"""API routes: /download, /stream/{video_id}, /health."""
from __future__ import annotations

import logging
import re
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.security.tokens import ExpiredTokenError, InvalidTokenError
from app.services.streamer import UpstreamError
from app.services.youtube import (
    ExtractionError,
    InvalidVideoIdError,
    normalize_video_id,
)

logger = logging.getLogger("api.routes")

router = APIRouter()

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9 ._-]+")

START_TIME = time.monotonic()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """If API_KEY is configured, require it via X-API-Key header."""
    settings = get_settings()
    if not settings.api_key:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        logger.warning("Rejected request with missing/invalid API key")
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@router.get("/health")
async def health() -> dict:
    return {
        "status": "online",
        "uptime_seconds": round(time.monotonic() - START_TIME, 1),
    }


@router.get("/download", dependencies=[Depends(require_api_key)])
async def download(
    request: Request,
    url: str = Query(..., description="YouTube video ID (or full URL)"),
    type: str = Query("audio", pattern="^(audio|video)$", description="audio or video"),
) -> dict:
    settings = get_settings()
    try:
        video_id = normalize_video_id(url)
    except InvalidVideoIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    yt = request.app.state.youtube
    tokens = request.app.state.tokens

    # Resolve now: fails fast on bad videos and warms the URL cache
    # so /stream is instant.
    try:
        media = await yt.resolve(video_id, type)
    except ExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    token = await tokens.issue(video_id, type)
    return {
        "download_token": token,
        "expires_in": settings.token_ttl,
        "video_id": video_id,
        "type": type,
        "title": media.title,
        "duration": media.duration,
    }


@router.get("/stream/{video_id}")
async def stream(
    video_id: str,
    request: Request,
    type: str = Query("audio", pattern="^(audio|video)$"),
    x_download_token: str | None = Header(default=None, alias="X-Download-Token"),
    range_header: str | None = Header(default=None, alias="Range"),
):
    if not x_download_token:
        raise HTTPException(status_code=401, detail="Missing X-Download-Token header")

    try:
        video_id = normalize_video_id(video_id)
    except InvalidVideoIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tokens = request.app.state.tokens
    yt = request.app.state.youtube
    streamer = request.app.state.streamer

    try:
        record = await tokens.validate(x_download_token, video_id)
    except ExpiredTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except InvalidTokenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    media_type = record.media_type
    try:
        media = await yt.resolve(video_id, media_type)
    except ExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    try:
        status_code, headers, iterator = await streamer.open_stream(media, range_header)
    except UpstreamError:
        # Direct URL may have expired upstream — re-resolve once and retry.
        logger.info("Upstream rejected URL for %s, re-resolving", video_id)
        try:
            media = await yt.resolve(video_id, media_type, force=True)
            status_code, headers, iterator = await streamer.open_stream(media, range_header)
        except (ExtractionError, UpstreamError) as exc:
            raise HTTPException(status_code=502, detail="Upstream media fetch failed") from exc

    ext = "m4a" if media.mime_type == "audio/mp4" else (
        "webm" if "webm" in media.mime_type else "mp4"
    )
    safe_title = _SAFE_FILENAME_RE.sub("", media.title)[:80] or video_id
    headers["content-disposition"] = f'inline; filename="{safe_title}.{ext}"'

    logger.info(
        "Streaming %s/%s -> client (status=%d, range=%s)",
        video_id, media_type, status_code, range_header or "none",
    )
    return StreamingResponse(iterator, status_code=status_code, headers=headers,
                             media_type=media.mime_type)
