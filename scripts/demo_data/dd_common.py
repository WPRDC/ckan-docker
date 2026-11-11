"""Shared helpers for the demo-data pull/load scripts.

Not a package meant for `pip install` -- these are operational scripts, run
in-container (the host has neither PyYAML nor ckanapi):

    bin/pull_demo_data [slug ...]
    bin/load_demo_data [slug ...]

Both wrap `docker compose exec ckan-dev python3 /srv/app/scripts/demo_data/<script>.py`.
`demo-data.yaml`, `demo-data/` and this directory are bind-mounted into
ckan-dev at the paths below (see docker-compose.dev.yml), so nothing here
needs an image rebuild to change.

Named `dd_common` rather than `common`: one of the editable-installed
extensions registers a PEP 660 meta path finder that intercepts the bare
name `common` ahead of normal sys.path resolution and redirects it to
`ckan.common`, regardless of import order. Not worth fighting.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

DEMO_DATA_YAML = Path("/srv/app/demo-data.yaml")
DEMO_DATA_DIR = Path("/srv/app/demo-data")

_DEFAULTS: dict[str, Any] = {
    "row_limit": None,
    "skip_formats": [],
    "exclude_resources": [],
    "fetch_external_links": False,
}


def load_manifest(path: Path = DEMO_DATA_YAML) -> dict[str, Any]:
    """Parse demo-data.yaml and merge each dataset entry over `defaults`.

    A bare string in `datasets:` is shorthand for `{slug: <string>}`. Every
    dataset dict in the returned list carries the full set of `_DEFAULTS`
    keys, so callers never need to fall back to the manifest-level defaults
    themselves.
    """
    raw = yaml.safe_load(path.read_text()) or {}

    defaults = dict(_DEFAULTS)
    defaults.update(raw.get("defaults") or {})

    datasets = []
    for item in raw.get("datasets") or []:
        if isinstance(item, str):
            item = {"slug": item}
        if "slug" not in item:
            raise ValueError(f"dataset entry missing required `slug`: {item!r}")
        merged = dict(defaults)
        merged.update(item)
        merged["skip_formats"] = [f.upper() for f in merged["skip_formats"]]
        datasets.append(merged)

    return {
        "source": (raw.get("source") or "").rstrip("/"),
        "defaults": defaults,
        "datasets": datasets,
    }


def select_datasets(
    datasets: list[dict[str, Any]], slugs: list[str]
) -> list[dict[str, Any]]:
    """Filter to the requested slugs, raising if any is not in the manifest."""
    if not slugs:
        return datasets
    wanted = set(slugs)
    selected = [d for d in datasets if d["slug"] in wanted]
    missing = wanted - {d["slug"] for d in selected}
    if missing:
        raise ValueError(f"not in demo-data.yaml: {', '.join(sorted(missing))}")
    return selected


def setup_logging() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger("demo_data")
