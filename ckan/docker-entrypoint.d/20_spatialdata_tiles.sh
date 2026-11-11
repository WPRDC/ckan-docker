#! /usr/bin/bash
#
# Sourced by the base image's start_ckan.sh (see 15_datapusher_plus_token.sh):
# keep all logic in the subshell so shell options and failures stay contained.

(
  # Installs (or updates) the datastore function that serves the spatialdata
  # Map view's tiles with only the fields it needs; see ckanext-spatialdata's
  # tile_function.sql. CREATE OR REPLACE, so it's safe on every start.
  #
  # Martin only discovers functions when it starts. After the FIRST install on
  # a database, restart the tiles service so it publishes public.spatialdata_tiles;
  # until then the Map view's tiles 404.
  #
  # A failure here mustn't stop CKAN from starting: the Map view is the only
  # thing that needs the function.
  if ckan -c "$CKAN_INI" spatialdata-init-tiles; then
    echo "[spatialdata] tile function installed"
  else
    echo "[spatialdata] WARNING: could not install the tile function; Map views won't load tiles" >&2
  fi
)
