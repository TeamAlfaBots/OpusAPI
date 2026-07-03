FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg is optional (yt-dlp uses it for some merges); curl for healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/api

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Non-root user
RUN useradd -m -u 10001 apiuser
USER apiuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT:-8000}/health || exit 1

# Shell form so ${PORT} (injected by Render/Railway/etc.) is honored; defaults to 8000.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
