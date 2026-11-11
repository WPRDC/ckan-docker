#! /usr/bin/bash
#
# NOTE: the base image's start_ckan.sh runs the /docker-entrypoint.d/*.sh scripts by
# SOURCING them (`. "$f"`), not executing them. A bare `set -euo pipefail` or `exit`
# at this file's top level therefore leaks into (or kills) the parent start_ckan.sh
# shell -- which then dies on the very next unset-var reference (`$EXTRA_UWSGI_OPTS`)
# and CKAN never starts. Keep ALL logic inside the subshell below so its shell options
# and any `exit` stay contained.

(
  set -euo pipefail

  # DataPusher+ 3.x reports job status back to CKAN by POSTing to
  # /api/3/action/datapusher_hook, which is sysadmin-only. The flow authenticates with a
  # CKAN API token read by utils.get_dp_plus_user_apitoken(): first
  # ckanext.datapusher_plus.api_token, then ckan.datapusher.api_token, else it raises.
  # The base image only ever writes a placeholder ("xxx") for the latter, which satisfies
  # the lookup and then 403s: the data still loads (DP+ 3.x writes the datastore
  # in-process) but the job is stuck "pending" in the UI forever, default views are never
  # created, and IDataPusher.after_upload hooks never fire.
  #
  # PREFERRED (production): mint the token once by hand, keep it in your secrets store and
  # set CKANEXT__DATAPUSHER_PLUS__API_TOKEN in the environment. ckanext-envvars maps it to
  # ckanext.datapusher_plus.api_token in both the web container and the Prefect worker
  # subprocess (which bootstraps via make_app -> load_environment, so plugins — including
  # envvars — are loaded). This block then does nothing: the secret stays out of the
  # home_dir volume, is rotatable from outside the container, and no new sysadmin token is
  # minted on every fresh volume.
  #
  #   ckan -c "$CKAN_INI" user token add <sysadmin> datapusher_plus -q | tail -1
  #
  # FALLBACK (dev / zero-touch): with no env var set, mint one for the sysadmin and persist
  # it in ckan.ini, which ckan-worker shares via the home_dir volume (it skips this
  # entrypoint). Regenerate only when the key is absent or still the placeholder, so a
  # persisted ckan.ini is left alone on restart. This mirrors DataPusher+'s own README
  # setup step, automated for containers.

  if [ -n "${CKANEXT__DATAPUSHER_PLUS__API_TOKEN:-}" ]; then
    echo "datapusher_plus: using API token from CKANEXT__DATAPUSHER_PLUS__API_TOKEN"
    exit 0
  fi

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
)