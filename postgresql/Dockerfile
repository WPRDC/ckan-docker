FROM postgis/postgis:17-master

# Include extra setup scripts (eg datastore)
COPY --chown=postgres:postgres docker-entrypoint-initdb.d /docker-entrypoint-initdb.d
