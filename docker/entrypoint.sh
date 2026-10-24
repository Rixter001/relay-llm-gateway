#!/bin/sh
# Container entrypoint: optionally apply database migrations, then run the given command.
set -eu
if [ "${RELAY_RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "Applying database migrations..."
  alembic upgrade head
fi
exec "$@"
