# syntax=docker/dockerfile:1

FROM aquasec/trivy:latest AS trivy

FROM docker:27-cli AS dockercli

FROM node:22-slim AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
COPY --from=frontend-builder /app/dist /app/frontend/dist

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --reinstall-package dockwatch .

RUN useradd -m -s /bin/bash appuser && \
    mkdir -p /home/appuser/.config/dockwatch && \
    chown -R appuser:appuser /app /home/appuser/.config/dockwatch
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:8080/health')" || exit 1

CMD ["dockwatch", "serve", "--host", "0.0.0.0", "--port", "8080"]
