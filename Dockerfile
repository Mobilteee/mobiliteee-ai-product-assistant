# Production image for the FastAPI backend (SSE streaming needs a long-lived
# process, so run this as a container/VM, NOT on serverless function runtimes).
#
# Build:      docker build -t ai-rag-backend .
# Run:        docker run --rm -p 8000:8000 -v ai-rag-data:/app/data ai-rag-backend
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first (better layer caching).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code. `backend.main:app` imports top-level `core.*`, and `backend/` is
# imported as a namespace package — both must live under /app.
COPY backend/  backend/
COPY core/     core/
# Seed corpus so a fresh deploy can bootstrap the demo KB on first boot.
COPY producttext/ producttext/
COPY .env.example .env.example

# Runtime data dir (SQLite by default). Create + own it so the non-root user
# can persist app.db (seed) and later uploads; mount a volume here in prod.
RUN mkdir -p /app/data && chown -R nobody:nogroup /app

USER nobody

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

# `python -m uvicorn` guarantees /app lands on sys.path so both the `backend`
# namespace package and the top-level `core` package import cleanly.
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
