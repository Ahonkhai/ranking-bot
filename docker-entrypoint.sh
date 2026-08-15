#!/bin/sh
# Make the data volume writable, then drop privileges.
#
# Railway (and Kubernetes, and Fly) attach persistent volumes at *runtime*,
# owned by root. A `chown` in the Dockerfile happens at build time and is
# invisible to that mount — and Docker only copies image ownership into a
# brand-new empty volume, never an existing one. So a container that starts
# life as a non-root USER cannot create its database on a volume that already
# holds data from a previous deployment, and dies on boot.
#
# Starting as root and dropping down here fixes the ownership on the real
# mount, whatever its history.
set -e

DB_DIR=$(dirname "${DB_PATH:-/data/rankbot.db}")
mkdir -p "$DB_DIR" 2>/dev/null || true

if [ "$(id -u)" = "0" ]; then
    chown -R rankbot:rankbot "$DB_DIR" 2>/dev/null || true

    # Fall back to running as root rather than refusing to boot: an
    # unprivileged process is a nice-to-have, a running bot is not.
    if command -v setpriv >/dev/null 2>&1; then
        exec setpriv --reuid=rankbot --regid=rankbot --init-groups "$@"
    fi
    echo "entrypoint: setpriv unavailable, continuing as root" >&2
fi

exec "$@"
