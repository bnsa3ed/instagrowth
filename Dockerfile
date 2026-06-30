FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build deps for psycopg2-binary are prebuilt; keep image lean.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# supercronic for the cron service (installed lazily via docker-compose entrypoint
# so the bot service doesn't need it). We install it here to keep one image.
ARG TARGETOS=linux
ARG SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.30/supercronic-linux-amd64
RUN apt-get update && apt-get install -y --no-install-recommends curl tini \
    && curl -fsSLo /usr/local/bin/supercronic ${SUPERCRONIC_URL} \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY . /app

ENTRYPOINT ["/usr/bin/tini", "--"]
