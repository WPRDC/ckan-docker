#!/usr/bin/env python3
"""Replay demo-data/ into the local dev CKAN as real uploads that trigger DataPusher+.

    bin/load_demo_data [--replace] [--wait[=SECONDS]] [slug ...]

Offline against demo-data/ (populated by bin/pull_demo_data) -- the only network
this touches is the local CKAN API. Every tabular resource is pushed as a
multipart file upload to `resource_create`, exactly the way the browser uploader
does it, so ckanext-datapusher_plus's `after_resource_create` hook fires and
queues a Prefect ingest run -- the same path a user hits on prod. PNGs and
external links are created as plain resources (DataPusher+ ignores them by
format), so nothing is faked: what ends up in the datastore got there through
DataPusher+.

Auth: uses CKAN_LOAD_API_TOKEN if set, otherwise mints a throwaway sysadmin
token with `ckan user token add` (works because this runs inside the ckan-dev
container). Target API is CKAN_LOAD_API_URL or http://localhost:5000.

With no slugs, loads every dataset in demo-data.yaml. Existing datasets are
skipped unless --replace (which `dataset_purge`s them first). --wait blocks
after the uploads until each DataPusher+ job finishes, then restores the saved
data dictionary (column labels/notes) from <resource-id>.fields.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ckanapi import CKANAPIError, NotFound, RemoteCKAN, ValidationError

from dd_common import DEMO_DATA_DIR, DEMO_DATA_YAML, load_manifest, select_datasets, setup_logging

log = setup_logging()

DEFAULT_API_URL = os.environ.get("CKAN_LOAD_API_URL", "http://localhost:5000")
UPLOAD_TIMEOUT = 600  # seconds; the 311 CSV is a few MB, localhost, so this is slack
POLL_INTERVAL = 4

# Formats ckanext-datapusher_plus auto-submits on resource create (config.py
# FORMATS default). Kept in sync by hand -- it changes about once a year.
DPP_FORMATS = {
    "csv", "tsv", "tab", "ssv", "xls", "xlsx", "xlsm", "xlsb",
    "ods", "geojson", "shp", "qgis", "zip",
}

# Server-managed / derived keys that must not be echoed back into a create call.
PACKAGE_DROP = {
    "id", "revision_id", "metadata_created", "metadata_modified",
    "creator_user_id", "organization", "owner_org", "resources", "groups",
    "tags", "state", "num_resources", "num_tags", "isopen", "license_title",
    "license_url", "tracking_summary", "relationships_as_subject",
    "relationships_as_object",
}
RESOURCE_DROP = {
    "id", "package_id", "revision_id", "created", "last_modified",
    "metadata_created", "metadata_modified", "datastore_active",
    "datastore_contains_all_records_of_resource_file", "cache_url",
    "cache_last_updated", "url_type", "mimetype", "mimetype_inner", "size",
    "hash", "position", "state", "resource_type", "tracking_summary", "url",
}


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
def resolve_token(explicit: str | None) -> str:
    """An API token for the loader: --api-token, then env, then mint one."""
    token = explicit or os.environ.get("CKAN_LOAD_API_TOKEN")
    if token:
        return token.strip()

    user = os.environ.get("CKAN_SYSADMIN_NAME", "ckan_admin")
    ini = os.environ.get("CKAN_INI", "/srv/app/ckan.ini")
    log.info("minting a sysadmin API token for %s via `ckan user token add`", user)
    try:
        out = subprocess.run(
            ["ckan", "-c", ini, "user", "token", "add", user, "demo-data-load", "-q"],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        log.error(
            "`ckan` is not on PATH -- run this in the ckan-dev container "
            "(bin/load_demo_data) or pass --api-token / set CKAN_LOAD_API_TOKEN"
        )
        raise
    except subprocess.CalledProcessError as e:
        log.error("`ckan user token add` failed:\n%s", (e.stderr or "").strip())
        raise

    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    token = lines[-1] if lines else ""
    if not token or " " in token:
        raise RuntimeError(f"could not parse a token from: {out.stdout!r}")
    return token


# --------------------------------------------------------------------------- #
# orgs & groups
# --------------------------------------------------------------------------- #
def _load_holders(site: RemoteCKAN, root: Path, kind: str) -> None:
    """Create organizations/ or groups/ entries that don't exist yet."""
    show = getattr(site.action, f"{kind}_show")
    create = getattr(site.action, f"{kind}_create")
    for path in sorted((root / f"{kind}s").glob("*.json")):
        rec = json.loads(path.read_text())
        name = rec["name"]
        try:
            show(id=name)
            log.info("  %s exists: %s", kind, name)
            continue
        except NotFound:
            pass
        create(
            name=name,
            title=rec.get("title") or name,
            description=rec.get("description") or "",
            image_url=rec.get("image_display_url") or rec.get("image_url") or "",
        )
        log.info("  %s created: %s", kind, name)


# --------------------------------------------------------------------------- #
# datasets & resources
# --------------------------------------------------------------------------- #
def build_package_dict(pkg: dict[str, Any]) -> dict[str, Any]:
    data = {k: v for k, v in pkg.items() if k not in PACKAGE_DROP}
    org = pkg.get("organization") or {}
    data["owner_org"] = org.get("name") or pkg.get("owner_org")
    data["tags"] = [_clean_tag(t) for t in pkg.get("tags") or []]
    groups = [{"name": g["name"]} for g in pkg.get("groups") or []]
    if groups:
        data["groups"] = groups
    return data


def _clean_tag(tag: dict[str, Any]) -> dict[str, Any]:
    out = {"name": tag["name"]}
    if tag.get("vocabulary_id"):
        out["vocabulary_id"] = tag["vocabulary_id"]
    return out


def build_resource_dict(res: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in res.items() if k not in RESOURCE_DROP and v is not None}


def _multipart_safe(d: dict[str, Any]) -> dict[str, Any]:
    """Flatten values for a multipart POST (ckanapi encodes each as bytes)."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, (list, dict)):
            v = json.dumps(v)
        out[k] = str(v)
    return out


def find_resource_file(resources_dir: Path, rid: str) -> Path | None:
    hits = [
        p for p in resources_dir.glob(f"{rid}.*")
        if not p.name.endswith(".fields.json")
    ]
    return hits[0] if hits else None


def create_resource(
    site: RemoteCKAN, pkg_id: str, res: dict[str, Any], resources_dir: Path
) -> tuple[dict[str, Any], Path | None]:
    body = build_resource_dict(res)
    body["package_id"] = pkg_id
    fpath = find_resource_file(resources_dir, res["id"])

    if fpath is not None:
        with fpath.open("rb") as fh:
            created = site.call_action(
                "resource_create",
                data_dict=_multipart_safe(body),
                files={"upload": (fpath.name, fh)},
                requests_kwargs={"timeout": UPLOAD_TIMEOUT},
            )
        return created, fpath

    # No local file: recreate as a plain link (external URL) if we have one.
    body["url"] = res.get("url") or ""
    if not body["url"]:
        log.warning("    %s: no file and no url; creating an empty resource", res.get("name"))
    return site.action.resource_create(**body), None


def load_dataset(
    site: RemoteCKAN, root: Path, spec: dict[str, Any], replace: bool
) -> list[tuple[str, str, Path | None]]:
    """Create one dataset and its resources. Returns DataPusher+ poll targets:
    (new_resource_id, display_name, fields_json_path_or_None)."""
    slug = spec["slug"]
    exclude = set(spec.get("exclude_resources") or [])
    skip_formats = {f.upper() for f in spec.get("skip_formats") or []}
    dataset_dir = root / "datasets" / slug
    pkg_path = dataset_dir / "package.json"
    if not pkg_path.exists():
        log.error("%s: not pulled yet (%s missing) -- run bin/pull_demo_data %s",
                  slug, pkg_path, slug)
        return []
    pkg = json.loads(pkg_path.read_text())
    resources_dir = dataset_dir / "resources"

    try:
        existing = site.action.package_show(id=slug)
    except NotFound:
        existing = None
    if existing:
        if not replace:
            log.warning("%s: already exists; skipping (pass --replace to overwrite)", slug)
            return []
        # dataset_purge leaves datastore tables (and their AUTO_ALIAS aliases) behind, so
        # a second --replace would hit "alias already exists" on re-ingest. Drop them first.
        for r in existing.get("resources", []):
            if not r.get("datastore_active"):
                continue
            try:
                site.action.datastore_delete(resource_id=r["id"], force=True)
            except (NotFound, ValidationError, CKANAPIError) as e:
                log.warning("  datastore_delete(%s) failed: %s", r["id"], e)
        log.info("%s: exists -> dropped datastore tables, dataset_purge", slug)
        site.action.dataset_purge(id=existing["id"])

    created = site.action.package_create(**build_package_dict(pkg))
    resources = pkg.get("resources") or []
    log.info("%s: created; adding %d resource(s)", slug, len(resources))

    targets: list[tuple[str, str, Path | None]] = []
    for res in resources:
        name = res.get("name") or res["id"]
        if name in exclude:
            log.info("  skip (excluded in demo-data.yaml): %s", name)
            continue
        if (res.get("format") or "").upper() in skip_formats:
            log.info("  skip (format %s excluded): %s", res.get("format"), name)
            continue
        try:
            new_res, fpath = create_resource(site, created["id"], res, resources_dir)
        except (ValidationError, CKANAPIError) as e:
            log.error("  resource %s failed: %s", name, e)
            continue

        fmt = (res.get("format") or "").lower()
        if fpath is not None and fmt in DPP_FORMATS:
            fields_path = resources_dir / f"{res['id']}.fields.json"
            targets.append((new_res["id"], name, fields_path if fields_path.exists() else None))
            log.info("  + %s  (uploaded %s -> DataPusher+ queued)", name, fpath.name)
        elif fpath is not None:
            log.info("  + %s  (uploaded %s)", name, fpath.name)
        else:
            log.info("  + %s  (link: %s)", name, res.get("url") or "-")
    return targets


# --------------------------------------------------------------------------- #
# --wait: poll DataPusher+ and restore data dictionaries
# --------------------------------------------------------------------------- #
def wait_for_dpp(
    site: RemoteCKAN, targets: list[tuple[str, str, Path | None]], timeout: int
) -> dict[str, tuple[str, str, Path | None]]:
    pending = {rid: (name, fp) for rid, name, fp in targets}
    results: dict[str, tuple[str, str, Path | None]] = {}
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        for rid in list(pending):
            name, fp = pending[rid]
            try:
                state = (site.action.datapusher_status(resource_id=rid) or {}).get("status")
            except NotFound:
                state = None
            if state in ("complete", "error"):
                results[rid] = (state, name, fp)
                del pending[rid]
        if pending:
            time.sleep(POLL_INTERVAL)
    for rid, (name, fp) in pending.items():
        results[rid] = ("timeout", name, fp)
    return results


def apply_data_dictionary(site: RemoteCKAN, rid: str, fields_path: Path) -> None:
    """Merge the saved column labels/notes onto whatever DataPusher+ inferred.

    Types stay as DataPusher+ set them (re-typing a populated column is a
    fight not worth having); only each field's `info` block is restored.
    """
    saved_info = {
        f["id"]: (f.get("info") or {})
        for f in json.loads(fields_path.read_text())
    }
    current = site.action.datastore_search(resource_id=rid, limit=0)
    fields = []
    for f in current["fields"]:
        if f["id"] == "_id":
            continue
        info = dict(f.get("info") or {})
        info.update(saved_info.get(f["id"], {}))
        fields.append({"id": f["id"], "type": f["type"], "info": info})
    site.action.datastore_create(resource_id=rid, fields=fields, force=True)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def _fetch_manifest() -> dict[str, Any]:
    try:
        return json.loads((DEMO_DATA_DIR / "fetch-manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("slugs", nargs="*", help="restrict the load to these dataset slugs")
    parser.add_argument(
        "--replace", action="store_true",
        help="dataset_purge any existing dataset with the same name before loading",
    )
    parser.add_argument(
        "--wait", nargs="?", type=int, const=600, default=None, metavar="SECONDS",
        help="after the uploads, wait up to SECONDS (default 600) for every "
             "DataPusher+ job, then restore saved data dictionaries",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help=f"(default: {DEFAULT_API_URL})")
    parser.add_argument("--api-token", default=None, help="skip token minting; use this token")
    args = parser.parse_args(argv)

    manifest = load_manifest(DEMO_DATA_YAML)
    try:
        datasets = select_datasets(manifest["datasets"], args.slugs)
    except ValueError as e:
        log.error(str(e))
        return 1
    if not datasets:
        log.warning("nothing to load (empty dataset list in demo-data.yaml)")
        return 0

    fetch = _fetch_manifest()
    site = RemoteCKAN(
        args.api_url,
        apikey=resolve_token(args.api_token),
        user_agent="ckan-docker-demo-data-loader/1.0",
    )

    log.info(
        "loading into %s  (source: %s, pulled %s)",
        args.api_url, fetch.get("source") or manifest["source"], fetch.get("pulled_at") or "?",
    )
    log.info("organizations...")
    _load_holders(site, DEMO_DATA_DIR, "organization")
    log.info("groups...")
    _load_holders(site, DEMO_DATA_DIR, "group")

    targets: list[tuple[str, str, Path | None]] = []
    for spec in datasets:
        log.info("dataset: %s", spec["slug"])
        try:
            targets.extend(load_dataset(site, DEMO_DATA_DIR, spec, args.replace))
        except (ValidationError, CKANAPIError) as e:
            log.error("  %s failed: %s", spec["slug"], e)

    if not targets:
        log.info("done -- no DataPusher+ jobs queued")
        return 0

    prefect_port = os.environ.get("PREFECT_PORT_HOST", "4200")
    log.info(
        "%d DataPusher+ job(s) queued -- watch the Prefect UI (http://localhost:%s) "
        "or each resource's DataPusher tab in CKAN",
        len(targets), prefect_port,
    )
    if args.wait is None:
        log.info("re-run with --wait to block until they finish and restore data dictionaries")
        return 0

    log.info("waiting up to %ss for DataPusher+...", args.wait)
    results = wait_for_dpp(site, targets, args.wait)
    ok = bad = 0
    for rid, (state, name, fp) in results.items():
        if state == "complete":
            ok += 1
            if fp is None:
                log.info("  OK  %s -- ingested", name)
                continue
            try:
                apply_data_dictionary(site, rid, fp)
                log.info("  OK  %s -- ingested, data dictionary restored", name)
            except (ValidationError, CKANAPIError, KeyError) as e:
                log.warning("  OK  %s -- ingested, data dictionary NOT restored: %s", name, e)
        elif state == "error":
            bad += 1
            log.error("  ERR %s -- DataPusher+ reported an error (see the Prefect run log)", name)
        else:
            bad += 1
            log.error("  ... %s -- still not finished after %ss", name, args.wait)
    log.info("done -- %d ingested, %d failed/timed out", ok, bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
