#! /usr/bin/bash


# as of 2025-08-05, datapusher-plus attempts to configure before env vars are set
# in order to get around this, we manually set the relevant vars during init
ckan config-tool $CKAN_INI \
  "ckan.datastore.write_url=$CKAN_DATASTORE_WRITE_URL" \
  "ckanext.datapusher_plus.use_proxy=$CKANEXT__DATAPUSHER_PLUS__USE_PROXY" \
  "ckanext.datapusher_plus.download_proxy=$CKANEXT__DATAPUSHER_PLUS__DOWNLOAD_PROXY" \
  "ckanext.datapusher_plus.ssl_verify=$CKANEXT__DATAPUSHER_PLUS__SSL_VERIFY" \
  "ckanext.datapusher_plus.upload_log_level=$CKANEXT__DATAPUSHER_PLUS__UPLOAD_LOG_LEVEL" \
  "ckanext.datapusher_plus.pii_screening=$CKANEXT__DATAPUSHER_PLUS__PII_SCREENING" \
  "ckanext.datapusher_plus.pii_found_abort=$CKANEXT__DATAPUSHER_PLUS__PII_FOUND_ABORT" \
  "ckanext.datapusher_plus.pii_show_candidates=$CKANEXT__DATAPUSHER_PLUS__PII_SHOW_CANDIDATES" \
  "ckanext.datapusher_plus.pii_quick_screen=$CKANEXT__DATAPUSHER_PLUS__PII_QUICK_SCREEN" \
  "ckanext.datapusher_plus.qsv_bin=$CKANEXT__DATAPUSHER_PLUS__QSV_BIN" \
  "ckanext.datapusher_plus.file_bin=$CKANEXT__DATAPUSHER_PLUS__FILE_BIN" \
  "ckanext.datapusher_plus.preview_rows=$CKANEXT__DATAPUSHER_PLUS__PREVIEW_ROWS" \
  "ckanext.datapusher_plus.download_timeout=$CKANEXT__DATAPUSHER_PLUS__DOWNLOAD_TIMEOUT" \
  "ckanext.datapusher_plus.max_content_length=$CKANEXT__DATAPUSHER_PLUS__MAX_CONTENT_LENGTH" \
  "ckanext.datapusher_plus.chunk_size=$CKANEXT__DATAPUSHER_PLUS__CHUNK_SIZE" \
  "ckanext.datapusher_plus.default_excel_sheet=$CKANEXT__DATAPUSHER_PLUS__DEFAULT_EXCEL_SHEET" \
  "ckanext.datapusher_plus.sort_and_dupe_check=$CKANEXT__DATAPUSHER_PLUS__SORT_AND_DUPE_CHECK" \
  "ckanext.datapusher_plus.dedup=$CKANEXT__DATAPUSHER_PLUS__DEDUP" \
  "ckanext.datapusher_plus.unsafe_prefix=$CKANEXT__DATAPUSHER_PLUS__UNSAFE_PREFIX" \
  "ckanext.datapusher_plus.reserved_colnames=$CKANEXT__DATAPUSHER_PLUS__RESERVED_COLNAMES" \
  "ckanext.datapusher_plus.prefer_dmy=$CKANEXT__DATAPUSHER_PLUS__PREFER_DMY" \
  "ckanext.datapusher_plus.ignore_file_hash=$CKANEXT__DATAPUSHER_PLUS__IGNORE_FILE_HASH" \
  "ckanext.datapusher_plus.auto_index_threshold=$CKANEXT__DATAPUSHER_PLUS__AUTO_INDEX_THRESHOLD" \
  "ckanext.datapusher_plus.auto_index_dates=$CKANEXT__DATAPUSHER_PLUS__AUTO_INDEX_DATES" \
  "ckanext.datapusher_plus.auto_unique_index=$CKANEXT__DATAPUSHER_PLUS__AUTO_UNIQUE_INDEX" \
  "ckanext.datapusher_plus.summary_stats_options=$CKANEXT__DATAPUSHER_PLUS__SUMMARY_STATS_OPTIONS" \
  "ckanext.datapusher_plus.add_summary_stats_resource=$CKANEXT__DATAPUSHER_PLUS__ADD_SUMMARY_STATS_RESOURCE" \
  "ckanext.datapusher_plus.summary_stats_with_preview=$CKANEXT__DATAPUSHER_PLUS__SUMMARY_STATS_WITH_PREVIEW" \
  "ckanext.datapusher_plus.qsv_stats_string_max_length=$CKANEXT__DATAPUSHER_PLUS__QSV_STATS_STRING_MAX_LENGTH" \
  "ckanext.datapusher_plus.qsv_dates_whitelist=$CKANEXT__DATAPUSHER_PLUS__QSV_DATES_WHITELIST" \
  "ckanext.datapusher_plus.qsv_freq_limit=$CKANEXT__DATAPUSHER_PLUS__QSV_FREQ_LIMIT" \
  "ckanext.datapusher_plus.auto_alias=$CKANEXT__DATAPUSHER_PLUS__AUTO_ALIAS" \
  "ckanext.datapusher_plus.auto_alias_unique=$CKANEXT__DATAPUSHER_PLUS__AUTO_ALIAS_UNIQUE" \
  "ckanext.datapusher_plus.copy_readbuffer_size=$CKANEXT__DATAPUSHER_PLUS__COPY_READBUFFER_SIZE" \
  "ckanext.datapusher_plus.auto_spatial_simplication=$CKANEXT__DATAPUSHER_PLUS__AUTO_SPATIAL_SIMPLICATION" \
  "ckanext.datapusher_plus.spatial_simplication_relative_tolerance=$CKANEXT__DATAPUSHER_PLUS__SPATIAL_SIMPLICATION_RELATIVE_TOLERANCE" \
  "ckanext.datapusher_plus.latitude_fields=$CKANEXT__DATAPUSHER_PLUS__LATITUDE_FIELDS" \
  "ckanext.datapusher_plus.longitude_fields=$CKANEXT__DATAPUSHER_PLUS__LONGITUDE_FIELDS" \
  "ckanext.datapusher_plus.jinja2_bytecode_cache_dir=$CKANEXT__DATAPUSHER_PLUS__JINJA2_BYTECODE_CACHE_DIR" \
  "ckanext.datapusher_plus.auto_unzip_one_file=$CKANEXT__DATAPUSHER_PLUS__AUTO_UNZIP_ONE_FILE" \
