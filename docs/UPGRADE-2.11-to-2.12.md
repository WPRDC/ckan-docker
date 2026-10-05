# CKAN 2.11 → 2.12 production upgrade — gameplan

Status: draft / not yet executed. Written 2026-09-09 against the `upgrade-to-2.12` branch,
informed by the prod facts in §1.

Prod today: **CKAN 2.11.6** from this compose repo (earlier commit), on a **managed Postgres
16.11**, behind an **external reverse proxy** at **https://data.wprdc.org** (the prod
`docker-compose.yml` ships no `db` and no `nginx` service). DataPusher+ is the **pre-3.x**
release: ingest runs as **`ckan jobs worker` inside the `ckan` container** (RQ on Redis), job
state in the **`datapusher_jobs`** database, **no Prefect**.

This branch moves to **CKAN 2.12.0 on Python 3.14** + **DataPusher+ 3.x**, which replaces the
in-container RQ worker with a **Prefect** server + a dedicated **`ckan-worker`** container.

The single one-way step is `ckan db upgrade` against the prod database. Everything below is
built around a restorable backup taken immediately before it, and rehearsing on a clone.

---

## 0. Scope

In: CKAN core 2.11.6→2.12.0, DataPusher+ 2.x→3.x, the compose stack, the new `prefect`
database, Solr reindex, rollback.

Out (separate windows): OS bumps, proxy/TLS changes. **Postgres is already 16.11 — no PG
work needed.**

---

## 1. Prod facts (confirmed 2026-09-09)

| # | Fact | Consequence for this upgrade |
|---|---|---|
| 1 | Current version **2.11.6** → target **2.12.0** | Short hop; few core alembic revisions. `ckan db pending-migrations` to preview. |
| 2 | Managed Postgres **16.11** | Above CKAN 2.12's floor. **No PG upgrade.** |
| 3 | Current prod image Python **3.10.21**; 2.12 image is **3.14.7** | 4-minor jump. See §2.1. The `home_dir` **and** `site_packages` volumes **must be wiped** at cutover — §8.2. |
| 4 | DPP today = **`docker exec -d <ckan> ckan jobs worker …` into the running `ckan` container** (no sidecar, no `:8800`, no supervision — dies on any container bounce) | Replaced wholesale by the supervised `ckan-worker` container. Cutover action = just stop running the exec. Record its **exact args** (queue name, if any) for rollback. Optionally backport a real `ckan-worker` service to the 2.11 compose first — see §2.2. |
| 5 | **`datapusher_jobs` DB/role is in use today** | DPP **3.x does not use it** (verified: `config.py` reads only `ckan.datastore.write_url`; no jobs-DB key; `init_db()` commented out). It becomes orphaned historical data — keep for records, drop in §7. No migration. |
| 6 | **`martin`/`tiles` is in prod use; the `maps` DB exists** | Keep `tiles` in the stack. `maps` already present → **not** in the "create by hand" list. Only the `tiles` healthcheck fix (§8.3) applies. |
| 7 | Harvester **not running** (`harvest` absent from `CKAN__PLUGINS`; `CKAN__HARVEST__MQ__*` is dead config) | No harvest workers, no harvest migrations, no harvest smoke tests. Optionally strip the `CKAN__HARVEST__*` keys from `.env`. |
| 8 | prod host **x86_64** | `platform: linux/amd64` is **native** in prod — no emulation. (Only the Mac rehearsal is emulated.) |
| 9 | `ckandbuser` has **no `CREATEDB`**; a separate admin account does | §2.4. Create the `prefect` DB once with the admin account, `OWNER ckandbuser`. Nothing else in the upgrade needs `CREATEDB` — `ckan db upgrade` and `datastore set-permissions` operate on DBs `ckandbuser` already owns. |
| 10 | Site URL **https://data.wprdc.org** | `.env` reconciliation, §8.1. |

Still worth a look before the window: how `ckan jobs worker` is started in the live 2.11
container (so you know exactly what stops); confirm the live 2.11 stack mounts
`home_dir`/`site_packages` as named volumes the same way this repo does (same repo, so almost
certainly yes); confirm the admin account can `CREATE DATABASE … OWNER ckandbuser` (on
managed Postgres the admin is usually a member of every created role, so it can — if not,
`GRANT ckandbuser TO <admin>` first, or create it then `ALTER DATABASE prefect OWNER TO ckandbuser`).

---

## 2. What actually changes

### 2.1 CKAN core 2.11.6 → 2.12.0

- **Python 3.10 → 3.14 — the top technical risk.** Four minor versions in one jump.
  `distutils` was removed in 3.12; other stdlib modules (`cgi`, `imp`, `asynchat`, …) are
  gone too. The 2.12 image *builds* fine — the full dependency tree resolves on 3.14
  (CKAN 2.12.0, Flask 3.1.3, Werkzeug 3.1.8, SQLAlchemy 2.0.51, psycopg2 2.9.12, lxml 6.1.1,
  cryptography 50.0.1, fiona 1.10.1, shapely 2.1.0, pandas 2.2.3, Babel 2.18, jsonschema
  4.26 after §8.3) — so the residual risk is **runtime imports**, especially in the WPRDC
  fork extensions (`ckanext-wprdctheme`, `ckanext-datajson`, `ckanext-odata`,
  `ckanext-spatialdata`). The rehearsal must load every plugin in `CKAN__PLUGINS` and
  exercise each. This is upstream's official `ckan/ckan-base:2.12` image — pinning an older
  Python means leaving the official image, so don't; retire the risk with rehearsal instead.
- **`ckan db upgrade`**: core + per-extension alembic revisions (datastore via core; dcat
  has a couple). One-way. Preview with `ckan db pending-migrations`. Point of no return.
- **Solr**: switch the core to `ckan/ckan-solr:2.12-solr9` (already `SOLR_IMAGE_VERSION` in
  `.env`) and **full reindex** (`ckan search-index rebuild`). Old index not forward-compatible.
- **Flask 3 / Werkzeug 3 / SQLAlchemy 2.0**: extensions importing framework internals or
  removed `toolkit`/`c` shims can fail at import. Again — rehearsal.
- **Sessions**: everyone gets logged out once at cutover. Keep `CKAN__SECRET_KEY` /
  `CKAN___BEAKER__SESSION__SECRET` / JWT secrets **identical to 2.11** so it happens exactly
  once and API tokens survive.
- **Config**: unknown keys now warn in the log. Scan startup for `Unknown config option`.
- **Theme** (`ckanext-wprdctheme`): template/Bootstrap drift between minors. Click-through
  vs current prod (home, dataset, resource, org, group, search, admin).

### 2.2 DataPusher+ 2.x → 3.x

DPP 3.x drops RQ. Ingest is now a **Prefect flow** on a **process work pool**, run in-process
by a dedicated worker.

Goes away:
- the **`docker exec -d <ckan> ckan jobs worker …`** invocation (§1.4). The 2.12 `ckan`
  container runs uWSGI only; nothing consumes the old RQ datapusher queue. Don't port the
  exec — the supervised `ckan-worker` service replaces it.
- the **`datapusher_jobs`** database stops being written (§1.5) — orphaned, not migrated.
- Redis **stays** (CKAN core still uses it for sessions / `ckan.redis.url`); only the RQ
  queue usage ends.

**Optional de-risk before the window:** if the cutover is more than a few weeks out, add a
real `ckan-worker` service to the *current* 2.11 `docker-compose.yml` now — same image and
`env_file`/`volumes`/`networks` as the 2.11 `ckan` service, `restart: unless-stopped`,
`command: ckan -c /srv/app/ckan.ini jobs worker <same queue args as the exec>`. That kills
the "worker not running after a container bounce / deploy" failure mode immediately and
proves the split-worker topology, shrinking the cutover to "swap the command + add `prefect`
+ create the `prefect` DB".

Arrives (already wired in `docker-compose.yml` on this branch):
- **`prefect`** service — API + UI, built from the CKAN image so client/server can't drift.
  Binds `127.0.0.1:${PREFECT_PORT_HOST}:4200`. Needs its own Postgres DB (`prefect`, §2.4).
  Runs as `root` to unpack its bundled UI.
- **`ckan-worker`** service — same image as `ckan`, shares the `home_dir` volume (same
  `/srv/app/ckan.ini`). On start: waits for a fully-written `ckan.ini`, creates the
  `datapusher-plus` process work pool, runs `ckan datapusher_plus prefect-deploy`, then
  `prefect worker start --pool datapusher-plus`.
- **`PREFECT_API_URL=http://prefect:4200/api`** on `ckan` and `ckan-worker`.
- **A sysadmin API token** for the sysadmin-only `datapusher_hook` callback. **Prod:** set
  `CKANEXT__DATAPUSHER_PLUS__API_TOKEN` in `.env` (ckanext-envvars maps it into both `ckan`
  and `ckan-worker`; §8.1). **Fallback** (env var unset):
  `ckan/docker-entrypoint.d/15_datapusher_plus_token.sh` mints one into `ckan.ini` on `ckan`
  startup and `ckan-worker` reads it from the shared `ckan.ini` — but that mints a fresh,
  never-revoked sysadmin token every time `home_dir` is recreated (i.e. at cutover). If jobs
  finish but stay "pending" in the UI, this token is wrong.
- **`qsvdp`** — installed in `ckan/Dockerfile`; build fails early if missing/too old.
- Worker env quirks: `HOME=/tmp`, `PREFECT_HOME=/tmp/prefect` (defaults aren't writable by
  the `ckan` user; without this the Prefect result-storage block silently fails to register
  and the datastore write rolls back even though the run logs "JOB DONE!").
- **`CKAN__DATAPUSHER__CALLBACK_URL_BASE` must be `http://ckan:5000`** — the in-network prod
  service name. Not `ckan-dev`, not `localhost`, not the public URL.

Config keys stay `ckanext.datapusher_plus.*`; `ckan/docker-entrypoint.d/10_datapusher_plus_prep.sh`
writes the `.env` set into `ckan.ini` on startup. Newer keys (spatial simplification,
auto-unzip, dedup, summary stats, AI suggestions) are already in `.env`.

Pending jobs at cutover: DPP 3.x won't pick up old RQ jobs. Let them finish before cutover or
re-trigger after.

### 2.3 This repo's compose stack

- Deploy = this branch's `docker-compose.yml` + a reconciled prod `.env` on the box that runs
  the stack, still pointed at the managed Postgres, still behind the external proxy. x86_64 →
  `platform: linux/amd64` runs native.
- The three fixes in §8.3 are committed (`48a6769`); build the prod image from that commit or later.
- Services after: `ckan`, `ckan-worker`, `prefect`, `solr`, `redis`, `tiles`. No `db`, no
  `nginx`.

### 2.4 New Postgres object to create by hand

Only one is new (the local dev stack makes it via
`postgresql/docker-entrypoint-initdb.d/60_create_prefect.sh`). **Run it as the admin account**
(`ckandbuser` has no `CREATEDB`), and make `ckandbuser` the owner so Prefect — which connects
as `ckandbuser` — can run its schema migrations and write the `public` schema (PG 15+ locks
`public` to the DB owner):

```sql
-- as the admin account:
CREATE DATABASE prefect OWNER ckandbuser ENCODING 'utf-8';
```

If the admin can't set `OWNER` directly (not a member of `ckandbuser`): `GRANT ckandbuser TO
<admin>;` first, or `CREATE DATABASE prefect;` then `ALTER DATABASE prefect OWNER TO ckandbuser;`.

`.env` then gets `PREFECT_DATABASE_URL=postgresql+asyncpg://ckandbuser:<pw>@<pg-host>/prefect`
(asyncpg driver, mandatory).

`ckandb`, `datastore`, `maps` already exist and are owned by `ckandbuser`, so `ckan db
upgrade` and the idempotent `ckan datastore set-permissions` (re-run on `ckan` boot) need no
elevated rights. `datapusher_jobs` DB/roles already exist and are left alone (orphaned).

---

## 3. Backups & rollback

Immediately before §5's `ckan db upgrade`:

1. **Postgres** — managed snapshot **and** logical dumps:
   `pg_dump -Fc -d ckandb -f ckandb-preupgrade.dump`
   `pg_dump -Fc -d datastore -f datastore-preupgrade.dump` (large — size the window for it)
2. **FileStore** — `/data/ckan` on the host: `tar czf ckan-storage-preupgrade.tgz -C /data ckan`.
3. **Git** — `git tag prod-2.11.6-preupgrade <sha> && git push --tags`; copy the live `.env`
   to a secrets store as `env.2.11.bak`.
4. **Images** — record current 2.11 image digests so a rollback `up` can't pull newer.
5. Solr — nothing; rebuilds from Postgres.

**Rollback (only realistic before writes are re-enabled):**
- `docker compose down`
- restore the Postgres snapshot (or `pg_restore` the dumps into a fresh DB and repoint);
  `DROP DATABASE prefect;` (`datapusher_jobs` was untouched — leave it)
- `git checkout prod-2.11.6-preupgrade`; restore the old `.env`
- remove the 2.12 `home_dir` + `site_packages` volumes so the **2.11** images re-seed them
  (3.10 tree); after `ckan` is back up, re-run `docker exec -d <ckan> ckan -c /srv/app/ckan.ini jobs worker <args>`
- `ckan search-index rebuild` on the 2.11 Solr core; repoint the proxy; exit maintenance

Once prod takes writes on 2.12, rollback means losing everything written since cutover.

---

## 4. Rehearsal on a prod clone (do this first — twice; final pass on x86_64)

Runs the **real** `ckan db upgrade` (no `MAINTENANCE_MODE`) against a **copy**. Feeds off the
same restore-a-dump flow as the read-only-prod tooling (`.env.prod-ro`).

1. Restore `ckandb` + `datastore` dumps into a scratch Postgres 16. `CREATE DATABASE prefect`.
   (Restore a `maps` dump too if you want to rehearse tiles.)
2. Build this branch's images (§8.3 fixes are in): `docker compose -f docker-compose.yml build`.
   First pass can be the Mac (emulated, slow, proves the build). **Final pass on an x86_64
   host** matching prod.
3. Point a rehearsal `.env` at the scratch DB. **Wipe `home_dir` + `site_packages` volumes
   first** (§8.2).
4. `docker compose up -d ckan` — watch `ckan db upgrade` in the log. **Time it.** Note
   migration errors and every `Unknown config option`.
5. `docker compose exec ckan ckan -c /srv/app/ckan.ini search-index rebuild` — **time it**
   (this sets the window length, scales with dataset count).
6. `docker compose up -d prefect ckan-worker` — via the Prefect API confirm: work pool
   `datapusher-plus` READY, deployment `datapusher-plus/datapusher-plus` READY, a worker
   ONLINE.
7. `docker compose up -d tiles` — `GET /catalog` lists the expected tile sources.
8. Smoke test:
   - `GET /api/action/status_show` → `ckan_version` 2.12.0, **full** extension list (every
     plugin loaded — the Python 3.14 check)
   - homepage, a known dataset, a resource with a DataStore table + Data Explorer view,
     `/dataset?q=…`
   - **DataPusher+ end-to-end**: replace a small CSV on a test resource → job in the Prefect
     UI → completes → DataStore table populated → view renders → job shows "complete" (not
     stuck "pending")
   - theme click-through vs current prod
   - `/data.json` (datajson), `/catalog.xml` + `/dataset/<id>.jsonld` (dcat), `/dataset/<id>/odata` if used
   - spatialdata: a dataset with a spatial resource
9. Fix, rebuild, **re-rehearse from a fresh restore** until step 8 is clean with zero manual
   fixups.

---

## 5. Cutover runbook (maintenance window)

Pre-window (no downtime):
- [ ] §1 open items closed; §4 rehearsed clean on x86_64
- [ ] prod image built from `48a6769` or later (§8.3) / pushed / pullable on the box
- [ ] DP+ API token minted on **live 2.11** (`ckan -c /srv/app/ckan.ini user token add <sysadmin> datapusher_plus -q | tail -1`), stored in the secrets store, set as `CKANEXT__DATAPUSHER_PLUS__API_TOKEN` in the new `.env`. Tokens survive the upgrade (same `api_token` table, same JWT secrets — §8.1).
- [ ] `CREATE DATABASE prefect OWNER ckandbuser` done on the managed Postgres **via the admin account**; `PREFECT_DATABASE_URL` in the new `.env`
- [ ] new prod `.env` reconciled (§8.1), PR-reviewed, staged on the box
- [ ] window length = measured migration + measured reindex + 100% buffer
- [ ] announce downtime

Window:
1. [ ] Maintenance page at the proxy (or stop `ckan`).
2. [ ] Let running DPP jobs finish; note any still "pending" (they won't survive). Stopping
       the old `ckan` container stops its in-container `ckan jobs worker`.
3. [ ] **Backups** — §3 items 1–2. Verify the snapshot completed.
4. [ ] On the box: `git checkout upgrade-to-2.12` (or release tag); put the new `.env` in place.
5. [ ] `docker compose down`.
6. [ ] **Wipe the masking volumes** (§8.2):
       `docker volume rm <project>_home_dir <project>_site_packages <project>_solr_data`
       (FileStore is the `/data/ckan` bind mount — untouched.)
7. [ ] `docker compose build` (or ensure images are pulled).
8. [ ] `docker compose up -d ckan` — **watch** `ckan db upgrade` in prerun. Wait for `ckan`
       healthy. Migration error → stop, assess, roll back (§3).
9. [ ] `docker compose exec ckan ckan -c /srv/app/ckan.ini search-index rebuild`.
10. [ ] `docker compose up -d prefect ckan-worker` — pool/deployment READY, worker ONLINE.
11. [ ] `docker compose up -d tiles` — `/catalog` OK.
12. [ ] Smoke test behind the proxy, still in maintenance: `status_show`, homepage, a dataset,
        a DataStore resource + view, search, `/data.json`, `/catalog.xml`, admin re-login,
        one **DataPusher+ ingest end-to-end**.
13. [ ] Exit maintenance. Watch logs, Prefect UI, proxy 5xx for 30–60 min.

---

## 6. Post-cutover verification (24–48 h)

- [ ] A user-driven DataPusher+ ingest completes and shows "complete"
- [ ] `ckan` / `ckan-worker` not restart-looping (`docker compose ps`, `RestartCount`)
- [ ] Prefect DB growing; no "database is locked" (would mean SQLite fallback)
- [ ] Search counts sane vs pre-upgrade
- [ ] cron: `ckan tracking update`, sitemap, any DCAT export jobs
- [ ] log scan: `Unknown config option`, template errors, `DeprecationWarning` floods, 3.14 `ImportError`s
- [ ] resource upload/download (FileStore path), password-reset email

---

## 7. Cleanup (after a stable week)

- [ ] Confirm nothing runs `ckan jobs worker` for datapusher anymore
- [ ] `datapusher_jobs` DB/roles: export the job history if wanted, then drop
- [ ] remove the old Solr core / 2.11 images; `docker image prune`
- [ ] delete the on-disk `.env` backup (keep it only in the secrets store)
- [ ] `git tag prod-2.12.0 <sha>`; merge branch → `master`; update `README.md` for Prefect-based DPP
- [ ] optionally strip dead `CKAN__HARVEST__MQ__*` from `.env`

---

## 8. Appendix

### 8.1 Prod `.env` reconciliation

The `.env` in the repo is a mid-migration working copy with dev values. For prod:

| Key | Set to |
|---|---|
| `CKAN_SITE_URL` | `https://data.wprdc.org` (repo has `http://localhost:5001`) |
| `CKAN__DATAPUSHER__CALLBACK_URL_BASE` | `http://ckan:5000` (repo has `http://ckan-dev:5000`) |
| `PREFECT_DATABASE_URL` | `postgresql+asyncpg://ckandbuser:<pw>@<pg-host>/prefect` (absent in repo `.env`) |
| `POSTGRES_HOST` / `POSTGRES_READ_ONLY_HOST` | managed Postgres host (+ replica if any) |
| `*_PORT_HOST` | prod values; `PREFECT_PORT_HOST` stays bound to `127.0.0.1` only |
| `CKAN__SECRET_KEY`, `CKAN___WTF_CSRF_SECRET_KEY`, `CKAN___BEAKER__SESSION__SECRET`, JWT encode/decode | the **live 2.11 values**, unchanged — repo has `CHANGE_ME` for beaker/JWT; the real values must carry over or every token/session breaks |
| `CKAN_SYSADMIN_*` | real values; rotate the password post-cutover if it's ever been in git |
| `CKANEXT__DATAPUSHER_PLUS__API_TOKEN` | a sysadmin API token minted on live 2.11 before the window (§5 pre-window), kept in the secrets store. Setting it turns `15_datapusher_plus_token.sh` into a no-op, so no token lands in the `home_dir` volume and wiping that volume doesn't mint a new orphaned one. Valid only while the JWT encode/decode secrets above carry over unchanged. |
| `CKAN__PLUGINS` | keep the prod list; `datapusher_plus` **stays** (now Prefect-backed) |
| `MAINTENANCE_MODE` | unset/`false` for the real cutover (only the read-only mirror sets it true) |
| `CKAN__HARVEST__MQ__*` | dead (harvester not run) — leave or delete |

Rotate any secret that has ever been committed as a real value, after cutover.

### 8.2 The masking-volume footgun (updated for the Python jump)

`docker-compose.yml` mounts named volumes over image content:
`home_dir:/srv/app/` and `site_packages:/usr/local/lib/python3.14/site-packages`.

Docker only seeds a named volume from the image when the volume is **brand-new / empty**. An
existing volume is presented as-is. So on an in-place upgrade you **must** remove:

- **`<project>_home_dir`** — else `/srv/app` (CKAN + extension source, `wsgi.py`,
  `start_ckan.sh`, `prerun.py`, `ckan.ini`) stays at 2.11 and the container silently runs old
  code.
- **`<project>_site_packages`** — the 2.11 stack wrote this volume's root while it was mounted
  at `…/python3.10/site-packages`. The 2.12 stack mounts the **same volume** at
  `…/python3.14/site-packages`, so its root (full of 3.10-built packages) is presented at the
  3.14 path — wrong ABI, missing/renamed modules, broken CKAN. The Python change makes wiping
  this **mandatory**, not optional.
- **`<project>_solr_data`** — 2.12 schema; wipe and reindex.

`ckan.ini` lives in `home_dir`; wiping it means prerun regenerates it from `.env` on next
boot (intended). Confirm no hand-edits to the live `ckan.ini` that aren't in `.env`.

FileStore is safe — it's the `/data/ckan` **bind mount**, not a named volume.

### 8.3 Fixes on this branch (committed in `48a6769`)

Found smoke-testing the prod stack locally 2026-09-09 — all dev/prod parity gaps (the fix
existed in the `.dev` twin, not the prod one). Committed 2026-10-05; the prod image must be
built from `48a6769` or later.

1. **`ckan/Dockerfile`** — `RUN pip3 install 'jsonschema>=4.18,<5'` after `ckanext-datajson`.
   datajson pins `jsonschema==2.4.0` (Draft3/4 only); the `prefect` service, built from the
   same image, imports `Draft202012Validator` and crashes without it. `Dockerfile.dev`
   already had the line.
2. **`ckan/docker-entrypoint.d/15_datapusher_plus_token.sh`** — body wrapped in a `( … )`
   subshell. `start_ckan.sh` *sources* entrypoint scripts, so the script's top-level
   `set -euo pipefail` leaked and killed the uWSGI launch on unset `$EXTRA_UWSGI_OPTS` →
   `ckan` crash-loop. Dev dodges it (`ckan run`, not `start_ckan.sh`). Same commit makes the
   script a no-op when `CKANEXT__DATAPUSHER_PLUS__API_TOKEN` is set (§8.1).
3. **`docker-compose.yml`** — `tiles` healthcheck `/solr/` → `/catalog` (matches
   `docker-compose.dev.yml`). Cosmetic.

### 8.4 Verified while writing this

- `ckan/ckan-base:2.12` = Python **3.14.7**, CKAN 2.12.0, Flask 3.1.3, SQLAlchemy 2.0.51,
  lxml 6.1.1, cryptography 50.0.1, fiona 1.10.1, shapely 2.1.0, pandas 2.2.3 — the full tree
  builds on 3.14.
- DataPusher+ 3.x (`wprdc/datapusher-plus@main`) reads only `ckan.datastore.write_url` for DB
  access; **no `datapusher_jobs` / jobs-DB usage** (`init_db()` commented out in `cli.py`).

### 8.5 Reference

- CKAN 2.12 changelog: https://docs.ckan.org/en/2.12/changelog.html
- CKAN upgrade guide: https://docs.ckan.org/en/2.12/maintaining/upgrading/
- `ckan db pending-migrations` — preview without applying
- DataPusher+ (WPRDC fork): https://github.com/wprdc/datapusher-plus