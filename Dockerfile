# syntax=docker/dockerfile:1

FROM aquasec/trivy:0.72.0@sha256:cffe3f5161a47a6823fbd23d985795b3ed72a4c806da4c4df16266c02accdd6f AS trivy

FROM docker:27-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c AS dockercli

FROM node:22-slim@sha256:f32b81066cde10a75dbac96646099533316d94bac4150c55da1636e1f0ffdc46 AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 /uv /uvx /bin/
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
    mkdir -p /home/appuser/.cache/trivy && \
    chown -R appuser:appuser /app /home/appuser/.config/dockwatch /home/appuser/.cache/trivy

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:8080/health')" || exit 1

# The entrypoint runs as root so it can auto-detect the Docker socket's group
# (no DOCKER_GID needed in .env), then drops to the unprivileged appuser via
# setpriv before running the command.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["dockwatch", "serve", "--host", "0.0.0.0", "--port", "8080"]
