"""YouTube media resolution via yt-dlp, with an async TTL cache.

yt-dlp's extract_info is blocking, so it runs in a thread pool guarded by a
semaphore. Resolved direct media URLs are cached per (video_id, type) so
repeated requests within the TTL skip extraction entirely.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass

import yt_dlp

logger = logging.getLogger("api.youtube")

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class ExtractionError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class InvalidVideoIdError(Exception):
    pass


@dataclass
class MediaInfo:
    video_id: str
    media_type: str
    url: str            # direct googlevideo URL
    mime_type: str
    title: str
    duration: int | None
    filesize: int | None
    http_headers: dict[str, str]
    resolved_at: float


def normalize_video_id(raw: str) -> str:
    """Accept a bare 11-char ID or a full YouTube URL; return the bare ID."""
    raw = raw.strip()
    if VIDEO_ID_RE.match(raw):
        return raw
    # Try to pull an ID out of common URL shapes
    m = re.search(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([A-Za-z0-9_-]{11})", raw)
    if m:
        return m.group(1)
    raise InvalidVideoIdError(f"Not a valid YouTube video ID or URL: {raw!r}")


class YouTubeService:
    def __init__(
        self,
        cache_ttl: int = 1800,
        max_concurrent: int = 4,
        video_max_height: int = 720,
        cookies_file: str = "",
        proxy: str = "",
    ) -> None:
        self._cache: dict[tuple[str, str], MediaInfo] = {}
        self._cache_ttl = cache_ttl
        self._sem = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()
        self._video_max_height = video_max_height
        self._cookies_file = cookies_file
        self._proxy = proxy

    def _ydl_opts(self, media_type: str) -> dict:
        if media_type == "audio":
            fmt = "bestaudio[ext=m4a]/bestaudio/best"
        else:
            h = self._video_max_height
            fmt = (
                f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
            )
        opts: dict = {
            "format": fmt,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "socket_timeout": 15,
            "retries": 2,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
        if self._cookies_file:
            opts["cookiefile"] = self._cookies_file
        if self._proxy:
            opts["proxy"] = self._proxy
        return opts

    def _extract_sync(self, video_id: str, media_type: str) -> MediaInfo:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(self._ydl_opts(media_type)) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise ExtractionError("yt-dlp returned no info")

        # If a combined format was chosen, `url` is at top level;
        # `requested_formats` appears when video+audio are separate.
        chosen = info
        if "requested_formats" in info and info["requested_formats"]:
            chosen = info["requested_formats"][0]

        direct_url = chosen.get("url")
        if not direct_url:
            raise ExtractionError("No direct media URL found")

        ext = chosen.get("ext", "")
        acodec = (chosen.get("acodec") or "").lower()
        if media_type == "audio":
            if ext == "m4a" or "mp4a" in acodec:
                mime = "audio/mp4"
            elif ext == "webm" or "opus" in acodec:
                mime = "audio/webm"
            else:
                mime = "application/octet-stream"
        else:
            mime = "video/mp4" if ext == "mp4" else ("video/webm" if ext == "webm" else "application/octet-stream")

        return MediaInfo(
            video_id=video_id,
            media_type=media_type,
            url=direct_url,
            mime_type=mime,
            title=info.get("title", video_id),
            duration=info.get("duration"),
            filesize=chosen.get("filesize") or chosen.get("filesize_approx"),
            http_headers=chosen.get("http_headers") or {},
            resolved_at=time.monotonic(),
        )

    async def resolve(self, video_id: str, media_type: str, force: bool = False) -> MediaInfo:
        key = (video_id, media_type)

        if not force:
            cached = self._cache.get(key)
            if cached and (time.monotonic() - cached.resolved_at) < self._cache_ttl:
                logger.debug("Cache hit for %s/%s", video_id, media_type)
                return cached

        async with self._sem:
            # Double-check after acquiring semaphore (another task may have resolved it)
            if not force:
                cached = self._cache.get(key)
                if cached and (time.monotonic() - cached.resolved_at) < self._cache_ttl:
                    return cached

            logger.info("Extracting media info: video=%s type=%s", video_id, media_type)
            t0 = time.monotonic()
            try:
                info = await asyncio.to_thread(self._extract_sync, video_id, media_type)
            except yt_dlp.utils.DownloadError as exc:
                msg = str(exc)
                logger.error("yt-dlp failure for %s: %s", video_id, msg)
                friendly, status = self._friendly_error(msg)
                raise ExtractionError(friendly, status) from exc
            logger.info(
                "Resolved %s/%s ('%s') in %.2fs", video_id, media_type,
                info.title, time.monotonic() - t0,
            )

        async with self._lock:
            self._cache[key] = info
        return info

    def invalidate(self, video_id: str, media_type: str) -> None:
        self._cache.pop((video_id, media_type), None)

    @staticmethod
    def _friendly_error(msg: str) -> tuple[str, int]:
        lowered = msg.lower()
        if "video unavailable" in lowered:
            return "Video unavailable", 404
        if "private video" in lowered:
            return "Video is private", 403
        if "age" in lowered and "confirm" in lowered:
            return "Video is age-restricted (cookies required)", 451
        if "sign in" in lowered:
            return "Video requires sign-in (cookies required)", 451
        return "Failed to extract media info", 502
