-- Runs once, when the Postgres volume is first created (docker-entrypoint-initdb.d).
-- Grafana gets a read-only role: a compromised dashboard cannot alter or delete the usage log.
-- The password is set from GRAFANA_DB_PASSWORD by 02-grafana-reader-password.sh.
CREATE ROLE grafana_reader LOGIN;
GRANT CONNECT ON DATABASE relay TO grafana_reader;
GRANT USAGE ON SCHEMA public TO grafana_reader;
-- The usage_log table is created later by Alembic (as the "relay" user), so grant SELECT on
-- tables that "relay" will create in the future too.
ALTER DEFAULT PRIVILEGES FOR ROLE relay IN SCHEMA public GRANT SELECT ON TABLES TO grafana_reader;
