# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Shared OpenSearch reachability probe + skip marker for integration tests.

Sibling to :mod:`backend.tests.integration.fixtures.es_reachability` and
:mod:`backend.tests.integration.fixtures.solr_reachability` — the OpenSearch
counterpart needed by the demo-scenarios headroom test (Epic 2 Story 2.3) so
it can skip OpenSearch-only scenarios when no OpenSearch container is running
rather than ``ConnectError``-ing.

Probe order mirrors the ES fixture's shape (2.0s timeout, prefer host-shell
``localhost:9201`` then fall back to the in-container ``opensearch:9200``).
Body shape uses the same ``version`` key check as the ES probe — both engines
share the ES-compatible REST surface at ``/``. The Compose service binds
OpenSearch to host port 9201 (CLAUDE.md "Ports") to avoid collision with the
Elasticsearch service on 9200.
"""

from __future__ import annotations

import httpx
import pytest


def _opensearch_base_url() -> str:
    """Probe localhost:9201 first (host-shell), fall back to opensearch:9200 (in-container).

    Returns the first reachable base URL whose ``/`` response carries a
    ``version`` key, or ``""`` when none respond.
    """
    for candidate in ("http://localhost:9201", "http://opensearch:9200"):
        try:
            with httpx.Client(timeout=2.0) as c:
                r = c.get(f"{candidate}/")
                if r.status_code == 200 and "version" in r.json():
                    return candidate
        except Exception:
            continue
    return ""


opensearch_required = pytest.mark.skipif(
    not _opensearch_base_url(),
    reason=(
        "OpenSearch not reachable on localhost:9201 or opensearch:9200 — "
        "see docs/03_runbooks/local-dev.md."
    ),
)
