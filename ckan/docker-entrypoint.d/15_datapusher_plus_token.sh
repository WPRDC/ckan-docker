#! /usr/bin/bash
set -euo pipefail

# DataPusher+ 3.x reports job status back to CKAN by POSTing to
# /api/3/action/datapusher_hook, which is sysadmin-only. The flow authenticates with a
# CKAN API token it reads from ckanext.datapusher_plus.api_token (falling back to
# ckan.datapusher.api_token). The base image only ever writes a placeholder ("xxx"), so
# without a real token every hook call 403s: the data still loads (DP+ 3.x writes the
# datastore in-process) but the job is stuck "pending" in the UI forever, default views
# are never created, and IDataPusher.after_upload hooks never fire.
#
# Mint one token for the sysadmin and persist it in ckan.ini. ckan-worker doesn't run
# this (its command skips the entrypoint) but shares ckan.ini via the home_dir volume, so
# it picks the token up from here. Regenerate only when the key is absent or still the
# placeholder, so a persisted ckan.ini is left alone on restart.

sysadmin="${CKAN_SYSADMIN_NAME:-ckan_admin}"

current=$(sed -n 's/^ckanext\.datapusher_plus\.api_token *= *//p' "$CKAN_INI" | head -1)

if [ -z "$current" ] || [ "$current" = "xxx" ]; then
  echo "datapusher_plus: minting an API token for '${sysadmin}'"
  token=$(ckan -c "$CKAN_INI" user token add "$sysadmin" datapusher_plus -q 2>/dev/null | tail -1)
  if [ -z "$token" ]; then
    echo "datapusher_plus: FAILED to mint a token for '${sysadmin}' -- jobs will stay 'pending'" >&2
    exit 0
  fi
  ckan config-tool "$CKAN_INI" "ckanext.datapusher_plus.api_token=${token}"
fi
