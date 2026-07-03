# Local Validation Test Results

**Date:** 2026-07-02 · **Server:** uvicorn on 127.0.0.1:8000 (plus a TTL=3s instance on :8001 for expiry testing)
**Real video used:** `dQw4w9WgXcQ` (Rick Astley — Never Gonna Give You Up)

| # | Test | Expected | Actual | Result |
|---|------|----------|--------|--------|
| 1 | `GET /health` | 200 `{"status":"online"}` | 200 `{"status":"online","uptime_seconds":…}` | ✅ |
| 2 | `GET /download` without `X-API-Key` | 401 | 401 `Invalid or missing API key` | ✅ |
| 3 | `GET /download?url=dQw4w9WgXcQ&type=audio` with key | 200 + token | 200, 43-char urlsafe token, `expires_in: 300`, title + duration returned, **1.7 s** cold | ✅ |
| 4 | `GET /stream/dQw4w9WgXcQ` with valid token + `Range: bytes=0-524287` | 206 + audio bytes | 206 Partial Content, `content-type: audio/mp4`, `content-range: bytes 0-524287/11829048`, file verified as **ISO Media MP4** (m4a) | ✅ |
| 5 | Full stream (no Range) | 200 + complete file | 200, **11,829,048 bytes** in 0.51 s (~23 MB/s), valid MP4 container | ✅ |
| 6 | Reuse same token (one-time use) | reject | 403 `Invalid download token` | ✅ |
| 7 | Garbage token | reject | 403 `Invalid download token` | ✅ |
| 8 | Missing `X-Download-Token` header | reject | 401 `Missing X-Download-Token header` | ✅ |
| 9 | **Expired token** (TTL=3 s instance, waited 5 s) | reject | 401 `Download token has expired` | ✅ |
| 10 | Token issued for video A used on video B | reject | 403 `Token is not valid for this video` | ✅ |
| 11 | Unavailable video ID `aaaaaaaaaaa` | clean error | 404 `Video unavailable` *(fixed during testing — was 502)* | ✅ |
| 12 | Malformed video ID `not_a_video` | 400/404 | handled | ✅ |
| 13 | `type=exe` (invalid enum) | 422 | 422 validation error | ✅ |
| 14 | Full YouTube URL as `url` param (`https://youtu.be/…`) | normalized to ID | `video_id: dQw4w9WgXcQ` extracted correctly | ✅ |
| 15 | `type=video` flow | 206 + mp4 | 206, `content-type: video/mp4`, valid ISO Media MP4 | ✅ |
| 16 | **10 concurrent** download→stream flows | all succeed | all 10 succeeded in **0.17 s total**; /download 31–38 ms warm (URL cache), /stream 62–127 ms | ✅ |
| 17 | Cache effectiveness | few extractions | only **3** yt-dlp extractions across the entire test session | ✅ |

## Issues found & fixed during testing

1. **Unavailable videos returned 502** — misleading for bots. Fixed: `ExtractionError` now carries a
   status code, mapping to 404 (unavailable), 403 (private), 451 (age-restricted/sign-in), 502 (other).

## Performance summary

- Cold `/download` (first extraction): ~1.7 s
- Warm `/download` (URL cache hit): ~30 ms
- `/stream` first byte: ~60–120 ms
- Full 11.3 MB audio streamed in 0.51 s
- 10 concurrent full flows: 0.17 s wall time
