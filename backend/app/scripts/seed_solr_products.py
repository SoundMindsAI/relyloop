# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Idempotent seed of the local Apache Solr ``products`` collection.

infra_adapter_solr Story A10. Creates the products + ubi_queries + ubi_events
collections using the checked-in configsets (so ``solr.UBIComponent`` + LTR
land enabled), then bulk-indexes ``samples/products.json``.

Auth: NONE. The local Compose Solr runs security-disabled (the same posture
as the local elasticsearch / opensearch services — see docker-compose.yml).
There is no ``security.json`` so Solr accepts unauthenticated admin calls.
Production operator clusters that DO enable auth are reached through the
``SolrAdapter`` (which sends solr_basic / solr_apikey), never through this
local-only seed script.

Idempotent: existing collections are not re-created; existing docs are
overwritten by id (Solr's update handler is upsert-by-uniqueKey).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

import httpx

# Configset source dirs (checked into the repo). Each holds a ``conf/``
# subdir Solr expects. In SolrCloud mode (which the local container runs)
# configsets live in ZooKeeper, NOT on the filesystem — so we upload them
# via the Configset UPLOAD API before creating collections. The Compose
# filesystem mount alone is never read by a cloud-mode Solr.
_CONFIGSET_SOURCE_ROOT = Path(__file__).resolve().parents[3] / "docker" / "solr" / "configsets"


def _ensure_configset(client: httpx.Client, configset_name: str) -> None:
    """Upload ``configset_name`` to ZooKeeper via the Configset UPLOAD API.

    Idempotent: skips when the configset is already listed. Zips the
    repo's ``docker/solr/configsets/<name>/conf`` tree in-memory (the zip
    root must be ``conf/...`` for Solr's UPLOAD handler).
    """
    listed = client.get("/solr/admin/configs", params={"action": "LIST"})
    listed.raise_for_status()
    if configset_name in (listed.json().get("configSets") or []):
        print(f"  configset {configset_name!r} already uploaded — skipping")
        return

    conf_dir = _CONFIGSET_SOURCE_ROOT / configset_name / "conf"
    if not conf_dir.is_dir():
        raise RuntimeError(f"configset source dir not found: {conf_dir}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(conf_dir.rglob("*")):
            if path.is_file():
                # Solr's Configset UPLOAD API expects the conf files at the
                # zip ROOT (solrconfig.xml, managed-schema.xml, ...), NOT
                # nested under a conf/ prefix — otherwise core creation fails
                # with "Can't find resource 'solrconfig.xml'". So make the
                # arcname relative to conf_dir itself, not its parent.
                zf.write(path, arcname=str(path.relative_to(conf_dir)))
    buf.seek(0)

    print(f"  uploading configset {configset_name!r} to ZooKeeper")
    resp = client.post(
        "/solr/admin/configs",
        params={"action": "UPLOAD", "name": configset_name},
        content=buf.getvalue(),
        headers={"Content-Type": "application/octet-stream"},
    )
    resp.raise_for_status()


def _ensure_collection(client: httpx.Client, collection: str, configset_name: str) -> None:
    """Create ``collection`` from the checked-in configset if it doesn't exist.

    Uploads the configset to ZooKeeper first (cloud mode requires it).
    Solr's /admin/collections?action=CREATE is idempotent only insofar as
    "already exists" returns 400; we treat that as success.
    """
    _ensure_configset(client, configset_name)
    resp = client.get("/solr/admin/collections", params={"action": "LIST"})
    resp.raise_for_status()
    if collection in (resp.json().get("collections") or []):
        print(f"  collection {collection!r} already exists — skipping CREATE")
        return
    print(f"  creating collection {collection!r} from configset {configset_name!r}")
    create_resp = client.get(
        "/solr/admin/collections",
        params={
            "action": "CREATE",
            "name": collection,
            "numShards": "1",
            "replicationFactor": "1",
            "collection.configName": configset_name,
        },
    )
    if create_resp.status_code == 400 and "already exists" in create_resp.text:
        return
    create_resp.raise_for_status()


def _bulk_index_products(client: httpx.Client, collection: str, docs: list[dict[str, Any]]) -> None:
    """Bulk-index docs via /solr/<collection>/update?commit=true."""
    if not docs:
        print(f"  no docs to index into {collection!r}")
        return
    print(f"  indexing {len(docs)} docs into {collection!r}")
    resp = client.post(
        f"/solr/{collection}/update",
        params={"commit": "true"},
        content=json.dumps(docs).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()


def main() -> int:
    """CLI entrypoint: create demo collections + bulk-index ``samples/products.json``."""
    parser = argparse.ArgumentParser(description="Seed the local Solr products demo collection")
    parser.add_argument(
        "--solr-host",
        default=os.environ.get("SOLR_HOST", "localhost"),
        help="Solr hostname (default: localhost or $SOLR_HOST)",
    )
    parser.add_argument(
        "--solr-port",
        type=int,
        default=int(os.environ.get("SOLR_PORT", "8983")),
        help="Solr port (default: 8983 or $SOLR_PORT)",
    )
    parser.add_argument(
        "--products-json",
        default="samples/products.json",
        help="Path to samples/products.json (default: %(default)s)",
    )
    args = parser.parse_args()

    base_url = f"http://{args.solr_host}:{args.solr_port}"

    # No auth header — the local Compose Solr is security-disabled.
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        print(f"Seeding Solr at {base_url}")
        # 1. Create the products collection from the relyloop_products configset
        #    (enables UBI + LTR).
        _ensure_collection(client, "products", "relyloop_products")
        # 2. Create the UBI collections from the relyloop_ubi configset.
        _ensure_collection(client, "ubi_queries", "relyloop_ubi")
        _ensure_collection(client, "ubi_events", "relyloop_ubi")
        # 3. Bulk-index the demo products.
        products_path = Path(args.products_json)
        if products_path.is_file():
            with products_path.open() as f:
                docs = json.load(f)
            if isinstance(docs, dict) and "products" in docs:
                docs = docs["products"]
            if not isinstance(docs, list):
                raise RuntimeError(
                    f"{products_path} must contain a list of dicts or {{products: [...]}} object"
                )
            _bulk_index_products(client, "products", docs)
        else:
            print(f"  warning: {products_path} not found — skipping product indexing")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
