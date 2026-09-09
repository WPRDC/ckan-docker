#!/usr/bin/env python3
"""Clone datasets listed in demo-data.yaml from a remote CKAN into demo-data/.

    bin/pull_demo_data [slug ...]

With no arguments, pulls every dataset in demo-data.yaml. One or more slugs
restrict the pull to just those. Safe to re-run: each dataset's files are
refetched and overwritten, and fetch-manifest.json is merged rather than
replaced, so pulling one slug does not erase the record of previous pulls.

This is the *only* part of the demo-data workflow that talks to the network
or to the remote CKAN (`source` in demo-data.yaml, e.g. data.wprdc.org) --
bin/load_demo_data is entirely offline against demo-data/. Nothing here
touches the local CKAN instance either.

Anonymous, read-only API calls throughout: the datasets this is meant for
are public, and pulling demo data has no business holding credentials for
the source instance.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from ckanapi import RemoteCKAN

from dd_common import DEMO_DATA_DIR, DEMO_DATA_YAML, load_manifest, select_datasets, setup_logging

log = setup_logging()

HTTP_TIMEOUT = 120


def _resource_ext(resource: dict[str, Any]) -> str:
    """Best-effort file extension for a saved resource, preferring `format`."""
    fmt = (resource.get("format") or "").strip().lower()
    if fmt and fmt.isalnum():
        return "." + fmt
    guessed = mimetypes.guess_extension(resource.get("mimetype") or "") or ""
    if guessed:
        return guessed
    suffix = Path(resource.get("url", "")).suffix
    return suffix or ".bin"


def _strip_id_column(csv_bytes: bytes) -> bytes:
    """Drop a leading literal `_id` column from a datastore dump.

    `_id` is the datastore's own auto-generated serial primary key, not
    part of the original data. DataPusher+ recreates it on the next ingest
    (see phase 0 notes in the plan); keeping it in the saved file would
    just fight with that regeneration and leave a redundant column behind
    after load_demo_data re-ingests it.
    """
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows or rows[0][:1] != ["_id"]:
        return csv_bytes
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in rows:
        writer.writerow(row[1:])
    return out.getvalue().encode("utf-8")


def _fetch_datastore_fields(site: RemoteCKAN, resource_id: str) -> list[dict[str, Any]]:
    """The data dictionary (column labels/notes) for a datastore resource.

    Excludes `_id` to match `_strip_id_column` -- see its docstring.
    """
    result = site.action.datastore_search(resource_id=resource_id, limit=0)
    return [f for f in result["fields"] if f["id"] != "_id"]


def _pull_resource(
    site: RemoteCKAN,
    source: str,
    resource: dict[str, Any],
    dest_dir: Path,
    row_limit: int | None,
    fetch_external_links: bool,
) -> dict[str, Any]:
    rid = resource["id"]
    url_type = resource.get("url_type") or ""
    entry: dict[str, Any] = {
        "id": rid,
        "name": resource.get("name"),
        "url_type": url_type,
        "format": resource.get("format"),
        "fetched": False,
    }

    if url_type == "upload":
        resp = requests.get(resource["url"], timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        file_path = dest_dir / f"{rid}{_resource_ext(resource)}"
        file_path.write_bytes(resp.content)
        entry.update(fetched=True, file=file_path.name, bytes=len(resp.content))

    elif url_type == "datapusher":
        # No file exists for these -- the data lives only in the source's
        # datastore (see the plan's "verified findings"). The dump endpoint
        # is the only way to get it back out.
        params = {"limit": row_limit} if row_limit is not None else {}
        resp = requests.get(
            f"{source}/datastore/dump/{rid}", params=params, timeout=HTTP_TIMEOUT
        )
        resp.raise_for_status()
        content = _strip_id_column(resp.content)
        file_path = dest_dir / f"{rid}.csv"
        file_path.write_bytes(content)
        entry.update(
            fetched=True,
            file=file_path.name,
            bytes=len(content),
            row_limit_applied=row_limit,
        )

        fields = _fetch_datastore_fields(site, rid)
        fields_path = dest_dir / f"{rid}.fields.json"
        fields_path.write_text(json.dumps(fields, indent=2))
        entry["fields_file"] = fields_path.name

    else:
        # Plain external link: no file behind it that belongs to this
        # dataset (could be an arbitrary third-party URL). Record it by
        # default; only fetch if the manifest opts in.
        entry["url"] = resource.get("url")
        if fetch_external_links and resource.get("url"):
            try:
                resp = requests.get(resource["url"], timeout=HTTP_TIMEOUT)
                resp.raise_for_status()
                file_path = dest_dir / f"{rid}{_resource_ext(resource)}"
                file_path.write_bytes(resp.content)
                entry.update(fetched=True, file=file_path.name, bytes=len(resp.content))
            except requests.RequestException as e:
                log.warning("  external link fetch failed for %s: %s", rid, e)
                entry["fetch_error"] = str(e)

    return entry


def pull_dataset(
    site: RemoteCKAN,
    source: str,
    spec: dict[str, Any],
    root: Path,
    org_cache: set[str],
    group_cache: set[str],
) -> dict[str, Any]:
    slug = spec["slug"]
    log.info("Pulling %s...", slug)
    package = site.action.package_show(id=slug)

    org = package.get("organization")
    if org and org["name"] not in org_cache:
        org_cache.add(org["name"])
        full = site.action.organization_show(id=org["name"], include_datasets=False)
        (root / "organizations" / f"{org['name']}.json").write_text(
            json.dumps(full, indent=2)
        )

    for group in package.get("groups") or []:
        if group["name"] in group_cache:
            continue
        group_cache.add(group["name"])
        full = site.action.group_show(id=group["name"], include_datasets=False)
        (root / "groups" / f"{group['name']}.json").write_text(json.dumps(full, indent=2))

    dataset_dir = root / "datasets" / slug
    resources_dir = dataset_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "package.json").write_text(json.dumps(package, indent=2))

    exclude = set(spec["exclude_resources"])
    skip_formats = set(spec["skip_formats"])
    row_limit = spec["row_limit"]
    fetch_links = spec["fetch_external_links"]

    fetched, skipped = [], []
    for resource in package["resources"]:
        name = resource.get("name") or resource["id"]
        fmt = (resource.get("format") or "").upper()
        if name in exclude:
            log.info("  skip (excluded): %s", name)
            skipped.append({"id": resource["id"], "name": name, "reason": "excluded"})
            continue
        if fmt in skip_formats:
            log.info("  skip (format %s): %s", fmt, name)
            skipped.append({"id": resource["id"], "name": name, "reason": f"format {fmt}"})
            continue
        log.info("  fetching: %s (%s)", name, resource.get("url_type") or "link")
        fetched.append(
            _pull_resource(site, source, resource, resources_dir, row_limit, fetch_links)
        )

    return {
        "slug": slug,
        "package_id": package["id"],
        "organization": org["name"] if org else None,
        "resources_fetched": fetched,
        "resources_skipped": skipped,
    }


def _merge_manifest(source: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    manifest_path = DEMO_DATA_DIR / "fetch-manifest.json"
    existing_by_slug: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text())
            existing_by_slug = {d["slug"]: d for d in existing.get("datasets", [])}
        except (json.JSONDecodeError, KeyError):
            log.warning("existing fetch-manifest.json is unreadable; overwriting it")
    for r in results:
        existing_by_slug[r["slug"]] = r
    return {
        "source": source,
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "datasets": list(existing_by_slug.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("slugs", nargs="*", help="restrict the pull to these dataset slugs")
    args = parser.parse_args(argv)

    manifest = load_manifest(DEMO_DATA_YAML)
    if not manifest["source"]:
        log.error("demo-data.yaml is missing a top-level `source`")
        return 1

    try:
        datasets = select_datasets(manifest["datasets"], args.slugs)
    except ValueError as e:
        log.error(str(e))
        return 1

    if not datasets:
        log.warning("nothing to pull (empty dataset list in demo-data.yaml)")
        return 0

    for sub in ("organizations", "groups", "datasets"):
        (DEMO_DATA_DIR / sub).mkdir(parents=True, exist_ok=True)

    site = RemoteCKAN(manifest["source"], user_agent="ckan-docker-demo-data-puller/1.0")
    org_cache: set[str] = set()
    group_cache: set[str] = set()

    results = []
    for spec in datasets:
        try:
            results.append(
                pull_dataset(site, manifest["source"], spec, DEMO_DATA_DIR, org_cache, group_cache)
            )
        except Exception:
            log.exception("failed to pull %s", spec["slug"])
            return 1

    manifest_out = _merge_manifest(manifest["source"], results)
    (DEMO_DATA_DIR / "fetch-manifest.json").write_text(json.dumps(manifest_out, indent=2))

    total_resources = sum(len(r["resources_fetched"]) for r in results)
    log.info(
        "Done. %d dataset(s), %d resource(s) pulled into %s",
        len(results), total_resources, DEMO_DATA_DIR,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
