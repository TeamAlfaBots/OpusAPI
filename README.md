# Private YouTube Media API

A production-ready, private YouTube streaming API built for Telegram music bots.
FastAPI + yt-dlp, fully async, tokenized two-step download flow.

## Workflow

```
Bot ──GET /download?url=VIDEO_ID&type=audio──▶ API
Bot ◀── { "download_token": "...", "expires_in": 300 } ──┘

Bot ──GET /stream/VIDEO_ID?type=audio
      Header: X-Download-Token: <token> ──▶ API
Bot ◀────────── audio byte stream ─────────┘
```

## Endpoints

### `GET /health`
```json
{ "status": "online", "uptime_seconds": 12.3 }
```

### `GET /download?url=<video_id>&type=<audio|video>`
Optional header `X-API-Key` (required if `API_KEY` env is set).

```json
{
  "download_token": "kJ8xL...secure...",
  "expires_in": 300,
  "video_id": "dQw4w9WgXcQ",
  "type": "audio",
  "title": "Rick Astley - Never Gonna Give You Up",
  "duration": 213
}
```

Also warms the media-URL cache so the follow-up `/stream` starts instantly.
`url` accepts a bare 11-char video ID **or** any full YouTube URL.

### `GET /stream/{video_id}?type=<audio|video>`
Headers:
- `X-Download-Token: <token>` — **required**
- `Range: bytes=...` — optional, passed through (seek/resume supported)

Returns the media stream (`audio/mp4` m4a for audio by default).

Errors:
- `401` — missing/expired token
- `403` — invalid, reused, or wrong-video token
- `502` — upstream/YouTube failure

## Security

- Tokens: `secrets.token_urlsafe(32)` (256-bit entropy), constant-time comparison
- TTL expiry (`TOKEN_TTL`, default 300 s) + background janitor purging expired tokens
- One-time use (`ONE_TIME_TOKENS=true`): a token dies after its first stream
- Tokens are **bound to the video ID and media type** they were issued for
- Optional master `API_KEY` gate on `/download`
- No public Swagger/OpenAPI docs

## Performance

- Fully async; yt-dlp extraction offloaded to threads with a concurrency semaphore
- Resolved direct media URLs cached per `(video_id, type)` for `URL_CACHE_TTL` (default 30 min)
- Shared pooled `httpx.AsyncClient` proxies bytes in 256 KiB chunks — no disk writes
- Automatic one-shot re-resolve + retry if the upstream URL has gone stale

## Run locally

```bash
cp .env.example .env       # edit API_KEY etc.
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Run with Docker

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f
```

`restart: unless-stopped` + container healthcheck give automatic crash recovery.

## Deploy to Render (recommended path for this repo)

A `render.yaml` blueprint is included.

1. Push this folder to a GitHub/GitLab repo:
   ```bash
   cd yt-api
   git init && git add . && git commit -m "YouTube media API"
   git remote add origin https://github.com/<you>/yt-music-api.git
   git push -u origin main
   ```
2. In the [Render dashboard](https://dashboard.render.com): **New + → Blueprint**, pick the repo.
   Render reads `render.yaml`, builds the Dockerfile, and auto-generates a secure `API_KEY`
   (find it under *Environment* in the service settings).
3. Wait for the deploy to go live — your URL will be `https://yt-music-api.onrender.com`
   (or similar).
4. **Verify** with the included script:
   ```bash
   ./verify_deployment.sh https://yt-music-api.onrender.com <API_KEY>
   ```

Automatic restarts: Render restarts the container on crash and also uses
`healthCheckPath: /health` to detect and replace unhealthy instances. `autoDeploy: true`
redeploys on every git push.

> ⚠️ **Free-tier note:** the free plan sleeps after 15 min idle (first request then takes
> ~50 s) — use the `starter` plan for a music bot. Also, Render's shared IPs occasionally
> trigger YouTube's "confirm you're not a bot" check; if that happens, add a `COOKIES_FILE`
> (secret file in Render) or set `YTDLP_PROXY`.

## Deploy (any Docker host / VPS)

1. Copy the project to the server (`git clone` / `scp`).
2. `cp .env.example .env` and set a strong `API_KEY`.
3. `docker compose up -d --build`
4. Put it behind a reverse proxy with TLS (Caddy example):
   ```
   api.yourdomain.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```
5. Verify: `curl https://api.yourdomain.com/health`

### Notes for production
- YouTube sometimes requires cookies for age-restricted content — mount a
  `cookies.txt` and set `COOKIES_FILE=/srv/api/cookies.txt`.
- Datacenter IPs can get bot-checked by YouTube; if so, set `YTDLP_PROXY`
  to a residential/rotating proxy.
- Keep `yt-dlp` updated (`pip install -U yt-dlp` / rebuild image) — YouTube
  changes frequently.

## Telegram bot usage example (aiohttp)

```python
async def get_audio(session, base, api_key, video_id):
    async with session.get(f"{base}/download",
                           params={"url": video_id, "type": "audio"},
                           headers={"X-API-Key": api_key}) as r:
        token = (await r.json())["download_token"]
    async with session.get(f"{base}/stream/{video_id}",
                           params={"type": "audio"},
                           headers={"X-Download-Token": token}) as r:
        return await r.read()   # or stream to disk / Telegram
```

## Environment variables

See `.env.example` — every setting is overridable via env vars.
