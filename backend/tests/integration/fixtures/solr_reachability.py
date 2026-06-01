# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Shared Apache Solr reachability probe + skip marker for integration tests.

Sibling to :mod:`backend.tests.integration.fixtures.es_reachability` — the Solr
counterpart used by the heavy-lane demo-reseed test so it can skip the Solr
scenario when no Solr is running rather than ``ConnectError``-ing.

Lands with ``infra_solr_ci_readiness`` Story 1.1 (FR-1). Mirrors the ES probe's
shape: 2.0s timeout, ``localhost:8983`` -> ``solr:8983`` probe order, returns the
matching base URL or ``""``. The body-shape check is Solr-specific: a healthy
``GET /solr/admin/info/system`` returns ``responseHeader.status == 0`` and a
``lucene`` block, so an accidental hit on a non-Solr service at the same port
does not false-positive.
"""

from __future__ import annotations

import httpx
import pytest


def _solr_base_url() -> str:
    """Probe localhost:8983 first (host-shell), fall back to solr:8983 (in-container).

    Returns the first reachable base URL whose ``/solr/admin/info/system``
    response is a well-formed Solr system-info envelope, or ``""`` when none
    respond.
    """
    for candidate in ("http://localhost:8983", "http://solr:8983"):
        try:
            with httpx.Client(timeout=2.0) as c:
                r = c.get(f"{candidate}/solr/admin/info/system")
                if r.status_code != 200:
                    continue
                body = r.json()
                if body.get("responseHeader", {}).get("status") == 0 and "lucene" in body:
                    return candidate
        except Exception:
            continue
    return ""


solr_required = pytest.mark.skipif(
    not _solr_base_url(),
    reason=(
        "Apache Solr not reachable on localhost:8983 or solr:8983 — "
        "see docs/03_runbooks/local-dev.md."
    ),
)
