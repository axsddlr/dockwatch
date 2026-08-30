#!/bin/sh
# Entrypoint for the dockwatch container.
#
# Runs as root so it can (1) correct any ownership drift caused by a previous
# root-level `docker exec` (e.g. config set-password / recover-admin) and
# (2) auto-detect the Docker socket's group so the unprivileged `appuser` can
# reach the daemon without needing DOCKER_GID in .env. It then drops to
# `appuser` and execs the supplied command (the image CMD or a compose
# override).
set -eu

# Runtime dirs must be owned by appuser for the app to write config/db/cache.
chown -R appuser:appuser /home/appuser/.config/dockwatch 2>/dev/null || true
chown appuser:appuser /home/appuser/.cache/trivy 2>/dev/null || true

# Auto-detect the docker.sock group. Works on native Linux (docker group),
# Docker Desktop (root group, GID 0), and hosts where the GID is unknown
# (e.g. Portainer-only access). If the socket isn't mounted, the local source
# simply returns zero containers and Portainer remains available.
SOCK=/var/run/docker.sock

if [ -S "$SOCK" ]; then
  SOCK_GID=$(stat -c '%g' "$SOCK" 2>/dev/null || true)

  if [ -n "$SOCK_GID" ]; then
    # Reuse an existing group for this GID, or create one.
    GRP=$(getent group "$SOCK_GID" | cut -d: -f1 2>/dev/null || true)
    if [ -z "$GRP" ]; then
      if groupadd -g "$SOCK_GID" dockersock 2>/dev/null; then
        GRP=dockersock
      fi
    fi

    if [ -n "$GRP" ]; then
      usermod -aG "$GRP" appuser 2>/dev/null || true
    fi
  fi
fi

# Run as the unprivileged user with its supplementary groups (including the
# detected Docker group). setpriv doesn't touch the environment, so point HOME
# at the appuser home dir — otherwise Path.home() resolves to /root and the
# app can't write its config.
export HOME=/home/appuser
export USER=appuser
exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
