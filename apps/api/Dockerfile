FROM python:3.12-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV UV_CACHE_DIR=/tmp/uv-cache

WORKDIR /app

RUN pip install --no-cache-dir uv==0.8.15

COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev \
    && uv run --no-sync playwright install --with-deps chromium \
    && groupadd --gid 10001 geo \
    && useradd --uid 10001 --gid geo --create-home --home-dir /home/geo geo \
    && mkdir -p /data /app/private_artifacts \
    && chown -R geo:geo /data /app /ms-playwright /home/geo

COPY --chown=geo:geo apps/api ./

USER 10001:10001

CMD ["sh", "-c", "uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
