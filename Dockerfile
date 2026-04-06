# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.11-slim AS runtime

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*

EXPOSE 8080

VOLUME ["/var/run/docker.sock", "/root/.config/dockwatch"]

CMD ["dockwatch", "serve", "--host", "0.0.0.0", "--port", "8080"]