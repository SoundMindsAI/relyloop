# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Idempotent seed of the local Apache Solr ``products`` collection.

infra_adapter_solr Story A10. Creates the products + ubi_queries + ubi_events
collections using the checked-in configsets (so ``solr.UBIComponent`` + LTR
land enabled), then bulk-indexes ``samples/products.json``.

Auth: BasicAuth using the bootstrap-security.sh-generated admin credentials
mounted as ``/run/secrets/solr_admin_*`` (Compose) or read from
``./secrets/solr_admin_*`` (host).

Idempotent: existing collections are not re-created; existing docs are
overwritten by id (Solr's update handler is upsert-by-uniqueKey).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


def _read_secret(env_name: str, default_path: str) -> str:
    """Resolve a Docker-secrets-style ``*_FILE`` env var or fall back to a path."""
    file_path = os.environ.get(env_name) or default_path
    return Path(file_path).read_text(encoding="utf-8").strip()


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def _ensure_collection(client: httpx.Client, collection: str, configset_name: str) -> None:
    """Create ``collection`` from the checked-in configset if it doesn't exist.

    Solr's /admin/collections?action=CREATE is idempotent only insofar as
    "already exists" returns 400; we treat that as success.
    """
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

    username = _read_secret("SOLR_ADMIN_USERNAME_FILE", "./secrets/solr_admin_username")
    password = _read_secret("SOLR_ADMIN_PASSWORD_FILE", "./secrets/solr_admin_password")

    base_url = f"http://{args.solr_host}:{args.solr_port}"
    headers = {"Authorization": _basic_auth_header(username, password)}

    with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
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
