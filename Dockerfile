# syntax=docker/dockerfile:1

FROM aquasec/trivy:latest AS trivy

FROM python:3.11-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

EXPOSE 8080

VOLUME ["/var/run/docker.sock", "/root/.config/dockwatch"]

CMD ["dockwatch", "serve", "--host", "0.0.0.0", "--port", "8080"]
