#!/bin/sh
# Sets the grafana_reader password from the environment, so it is not hard-coded in SQL.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "ALTER ROLE grafana_reader WITH PASSWORD '${GRAFANA_DB_PASSWORD}';"
