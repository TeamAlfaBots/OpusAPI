"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object. Values come from env vars or the .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Server ---
    app_name: str = "Private YouTube Media API"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # --- Security ---
    # Optional master API key. When set, /download requires header `X-API-Key`.
    api_key: str = ""
    # Seconds a download token stays valid.
    token_ttl: int = 300
    # If true, a token is invalidated after its first successful use.
    one_time_tokens: bool = True
    # Bytes of entropy for tokens (urlsafe -> ~1.3x chars).
    token_bytes: int = 32

    # --- yt-dlp / streaming ---
    # Max media height for video type (keeps responses fast & small).
    video_max_height: int = 720
    # Seconds to cache resolved media URLs per (video_id, type).
    url_cache_ttl: int = 1800
    # Max concurrent yt-dlp extractions.
    max_extractions: int = 4
    # Optional cookies file path for age/region-restricted content.
    cookies_file: str = ""
    # Optional proxy for yt-dlp (e.g. socks5://host:port).
    ytdlp_proxy: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
