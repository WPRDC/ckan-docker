# CKAN 2.11.6 → 2.12 production upgrade

Prod: https://data.wprdc.org, managed Postgres 16, external reverse proxy. Deploy from the
`upgrade-to-2.12` branch at `48a6769` or later.

The only one-way step is `ckan db upgrade` (cutover step 8). Don't start it without verified
backups.

---

## 1. Rehearse on a prod clone (twice; final pass on x86_64)

1. Restore `ckandb` + `datastore` (+ `maps`) dumps into a scratch Postgres 16, then
   `CREATE DATABASE prefect;`
2. Point a rehearsal `.env` at the scratch DB (same keys as §2).
3. `docker compose down`, then wipe `home_dir`, `site_packages` and `solr_data` volumes.
4. `docker compose build && docker compose up -d ckan`. Time `ckan db upgrade` in the log.
5. `docker compose exec ckan ckan -c /srv/app/ckan.ini search-index rebuild`. Time it.
6. `docker compose up -d prefect ckan-worker tiles`.
7. Run the smoke test (cutover step 12). Fix, rebuild, and re-run from a fresh restore until it
   passes with no manual fixups.

## 2. Prep (before the window, no downtime)

- [ ] Rehearsal passed on x86_64.
- [ ] Images built or pullable on the prod box.
- [ ] As the Postgres **admin** account (`ckandbuser` has no `CREATEDB`):
      `CREATE DATABASE prefect OWNER ckandbuser ENCODING 'utf-8';`
- [ ] On live 2.11, mint the DataPusher+ token and store it in the secrets store:
      `ckan -c /srv/app/ckan.ini user token add <sysadmin> datapusher_plus -q | tail -1`
- [ ] Note the exact `docker exec … ckan jobs worker …` command running today (for rollback).
- [ ] Confirm the live `ckan.ini` has no hand edits that aren't in `.env` (it gets regenerated).
- [ ] New prod `.env` staged on the box:

  | Key | Value |
  |---|---|
  | `CKAN_SITE_URL` | `https://data.wprdc.org` |
  | `CKAN__DATAPUSHER__CALLBACK_URL_BASE` | `http://ckan:5000` |
  | `PREFECT_DATABASE_URL` | `postgresql+asyncpg://ckandbuser:<pw>@<pg-host>/prefect` |
  | `CKANEXT__DATAPUSHER_PLUS__API_TOKEN` | the token minted above |
  | `POSTGRES_HOST` / `POSTGRES_READ_ONLY_HOST` | managed Postgres host(s) |
  | `CKAN__SECRET_KEY`, `CKAN___WTF_CSRF_SECRET_KEY`, `CKAN___BEAKER__SESSION__SECRET`, JWT encode/decode | **copied unchanged from live 2.11** |
  | `CKAN_SYSADMIN_*`, `CKAN__PLUGINS` | prod values (`datapusher_plus` stays) |
  | `PREFECT_PORT_HOST` | bound to `127.0.0.1` only |
  | `MAINTENANCE_MODE` | unset or `false` |

- [ ] Window length = measured migration + measured reindex + 100% buffer. Announce downtime.

## 3. Cutover

1. [ ] Put the maintenance page up at the proxy.
2. [ ] Let running DataPusher+ jobs finish. Pending ones won't carry over.
3. [ ] Back up, and verify each one:
       - managed Postgres snapshot
       - `pg_dump -Fc -d ckandb -f ckandb-preupgrade.dump`
       - `pg_dump -Fc -d datastore -f datastore-preupgrade.dump`
       - `tar czf ckan-storage-preupgrade.tgz -C /data ckan`
       - `git tag prod-2.11.6-preupgrade && git push --tags`
       - copy the live `.env` to the secrets store; record current image digests
4. [ ] `git fetch && git checkout upgrade-to-2.12`; put the new `.env` in place.
5. [ ] `docker compose down`
6. [ ] `docker volume rm <project>_home_dir <project>_site_packages <project>_solr_data`
       **This is required.** Old volumes would mask the new image (Python 3.10 packages under 3.14).
       FileStore (`/data/ckan` bind mount) is untouched.
7. [ ] `docker compose build` (or `pull`)
8. [ ] `docker compose up -d ckan`. Watch `ckan db upgrade` in the logs and wait for healthy.
       On a migration error, stop and roll back (§4).
9. [ ] `docker compose exec ckan ckan -c /srv/app/ckan.ini search-index rebuild`
10. [ ] `docker compose up -d prefect ckan-worker`. In the Prefect UI, check that pool
        `datapusher-plus` and the deployment are READY and a worker is ONLINE.
11. [ ] `docker compose up -d tiles`. Check that `/catalog` responds.
12. [ ] Smoke test behind the proxy:
        - `/api/action/status_show` shows `ckan_version` 2.12.0 and every plugin loaded
        - homepage, a dataset, a DataStore resource and its view, search
        - `/data.json`, `/catalog.xml`, admin login
        - DataPusher+ end to end: replace a small CSV, and the job reaches "complete"
          (if it stays "pending", the API token is wrong)
13. [ ] Take down the maintenance page. Watch logs, the Prefect UI and proxy 5xx for 30–60 min.

## 4. Rollback (only before real writes on 2.12)

1. `docker compose down`
2. Restore the Postgres snapshot (or `pg_restore` the dumps); `DROP DATABASE prefect;`
3. `git checkout prod-2.11.6-preupgrade`; restore the old `.env`
4. `docker volume rm <project>_home_dir <project>_site_packages <project>_solr_data`
5. `docker compose up -d`; restart the old `docker exec -d <ckan> ckan … jobs worker …` command
6. `ckan search-index rebuild`; take down the maintenance page

## 5. After cutover

**First 24–48 h:**
- [ ] A user-driven DataPusher+ ingest completes
- [ ] `ckan` and `ckan-worker` aren't restart-looping (`docker compose ps`)
- [ ] Search counts match pre-upgrade
- [ ] Cron jobs still run (`ckan tracking update`, sitemap, DCAT exports)
- [ ] No `ImportError`, `Unknown config option` or template errors in the logs
- [ ] File upload/download and password-reset email work

**After a stable week:**
- [ ] Drop the `datapusher_jobs` DB/roles (export history first if wanted)
- [ ] `docker image prune` to remove the 2.11 images
- [ ] `git tag prod-2.12.0`; merge `upgrade-to-2.12` → `master`
- [ ] Rotate any secret that has ever been committed to git
