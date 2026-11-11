#!/bin/bash
set -e

# martin/config.yaml declares a second postgres connection via MAPS_DATABASE_URL. In prod
# that points at a separate maps database; locally it resolves to this postgres service.
# Without the database present martin fails its whole startup ("Failed to create postgres
# pool") and the tiles container crash-loops, taking the datastore connection down with it.
# An empty postgis-enabled database is enough to let martin start; it publishes nothing
# until tables exist.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE "maps" OWNER "$CKAN_DB_USER" ENCODING 'utf-8';
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d "maps" <<-EOSQL
  CREATE EXTENSION postgis;

  GRANT CONNECT ON DATABASE "maps" TO "$DATASTORE_READONLY_USER";
  GRANT USAGE ON SCHEMA public TO "$DATASTORE_READONLY_USER";
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO "$DATASTORE_READONLY_USER";

  ALTER DEFAULT PRIVILEGES FOR USER "$CKAN_DB_USER" IN SCHEMA public
     GRANT SELECT ON TABLES TO "$DATASTORE_READONLY_USER";
EOSQL
