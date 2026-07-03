"""Async media streaming proxy.

Streams bytes from the resolved googlevideo URL to the client using a shared
httpx.AsyncClient (connection pooling). Supports HTTP Range passthrough so
clients (e.g. Telegram bots downloading in chunks) can seek/resume.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

from app.services.youtube import MediaInfo

logger = logging.getLogger("api.streamer")

CHUNK_SIZE = 256 * 1024  # 256 KiB

PASSTHROUGH_RESPONSE_HEADERS = (
    "content-length",
    "content-range",
    "accept-ranges",
)


class UpstreamError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class StreamerService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=60.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        logger.info("Streamer HTTP client started")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("Streamer HTTP client closed")

    async def open_stream(
        self,
        media: MediaInfo,
        range_header: str | None = None,
    ) -> tuple[int, dict[str, str], AsyncIterator[bytes]]:
        """Open upstream request. Returns (status_code, headers, byte-iterator)."""
        assert self._client is not None, "StreamerService not started"

        headers = dict(media.http_headers)
        if range_header:
            headers["Range"] = range_header

        req = self._client.build_request("GET", media.url, headers=headers)
        resp = await self._client.send(req, stream=True)

        if resp.status_code >= 400:
            body = await resp.aread()
            await resp.aclose()
            logger.error(
                "Upstream error %s for %s (%d bytes body)",
                resp.status_code, media.video_id, len(body),
            )
            raise UpstreamError(resp.status_code, f"Upstream returned {resp.status_code}")

        out_headers: dict[str, str] = {}
        for name in PASSTHROUGH_RESPONSE_HEADERS:
            if name in resp.headers:
                out_headers[name] = resp.headers[name]
        out_headers["content-type"] = media.mime_type

        async def iterator() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                    yield chunk
            finally:
                await resp.aclose()

        return resp.status_code, out_headers, iterator()
