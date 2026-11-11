#!/bin/bash
set -e

# The `prefect` service keeps all orchestration state (flow runs, deployments, work
# queues, task runs) in this database. The default is SQLite under PREFECT_HOME, which
# throws "database is locked" the moment `prefect server start`'s background services and
# the DataPusher+ worker write concurrently -- see PREFECT_SERVER_DATABASE_CONNECTION_URL
# on the prefect service in docker-compose.dev.yml. An empty database is enough; Prefect
# runs its own Alembic migrations on start (migrate_on_start defaults on).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE "prefect" OWNER "$CKAN_DB_USER" ENCODING 'utf-8';
EOSQL
