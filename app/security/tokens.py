"""Secure, expiring, optionally one-time download tokens.

Tokens are random (secrets.token_urlsafe) and stored in-memory with
metadata binding them to a specific video_id + media type. Constant-time
comparison is used when validating.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field

logger = logging.getLogger("api.tokens")


@dataclass
class TokenRecord:
    video_id: str
    media_type: str
    expires_at: float
    one_time: bool
    used: bool = False
    created_at: float = field(default_factory=time.monotonic)


class TokenManager:
    """In-memory token store with TTL and one-time-use semantics."""

    def __init__(self, ttl: int, one_time: bool, token_bytes: int = 32) -> None:
        self._ttl = ttl
        self._one_time = one_time
        self._token_bytes = token_bytes
        self._store: dict[str, TokenRecord] = {}
        self._lock = asyncio.Lock()

    @property
    def ttl(self) -> int:
        return self._ttl

    async def issue(self, video_id: str, media_type: str) -> str:
        token = secrets.token_urlsafe(self._token_bytes)
        record = TokenRecord(
            video_id=video_id,
            media_type=media_type,
            expires_at=time.monotonic() + self._ttl,
            one_time=self._one_time,
        )
        async with self._lock:
            self._store[token] = record
        logger.info("Issued token for video=%s type=%s ttl=%ss", video_id, media_type, self._ttl)
        return token

    async def validate(self, token: str, video_id: str) -> TokenRecord:
        """Validate and (if one-time) consume a token.

        Raises TokenError subclasses on failure.
        """
        async with self._lock:
            # Constant-time lookup to avoid timing side channels on token value.
            record = None
            for stored, rec in self._store.items():
                if hmac.compare_digest(stored, token):
                    record = rec
                    break

            if record is None:
                logger.warning("Rejected unknown token for video=%s", video_id)
                raise InvalidTokenError("Invalid download token")

            if time.monotonic() > record.expires_at:
                self._store.pop(token, None)
                logger.warning("Rejected expired token for video=%s", video_id)
                raise ExpiredTokenError("Download token has expired")

            if record.used:
                logger.warning("Rejected already-used token for video=%s", video_id)
                raise InvalidTokenError("Download token already used")

            if record.video_id != video_id:
                logger.warning(
                    "Token/video mismatch: token bound to %s, requested %s",
                    record.video_id, video_id,
                )
                raise InvalidTokenError("Token is not valid for this video")

            if record.one_time:
                record.used = True
                self._store.pop(token, None)

            return record

    async def purge_expired(self) -> int:
        """Remove expired tokens. Returns number purged."""
        now = time.monotonic()
        async with self._lock:
            dead = [t for t, r in self._store.items() if now > r.expires_at]
            for t in dead:
                del self._store[t]
        if dead:
            logger.debug("Purged %d expired tokens", len(dead))
        return len(dead)


class TokenError(Exception):
    pass


class InvalidTokenError(TokenError):
    pass


class ExpiredTokenError(TokenError):
    pass
