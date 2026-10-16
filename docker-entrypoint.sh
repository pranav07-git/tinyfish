#!/bin/sh
# Hosted volumes are often mounted root-owned. Fix ownership of the data directory,
# then drop to the unprivileged "app" user before starting the server.
set -e
DATA_DIR="$(dirname "${DB_PATH:-/data/jobfish.db}")"
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  chown -R app:app "$DATA_DIR"
  exec setpriv --reuid=app --regid=app --init-groups "$@"
fi
exec "$@"
