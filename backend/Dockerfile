FROM python:3.10-slim AS base
WORKDIR /app

ARG IMAGE_TAG=latest
ARG BUILD_DATE=unknown
ARG GIT_HASH=unknown

LABEL org.opencontainers.image.version="${IMAGE_TAG}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${GIT_HASH}"

ENV IMAGE_TAG=${IMAGE_TAG} BUILD_DATE=${BUILD_DATE} GIT_HASH=${GIT_HASH}

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    pandoc \
    libreoffice-nogui \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
RUN playwright install chromium && playwright install-deps
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "300"]
