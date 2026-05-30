# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Shared Elasticsearch reachability probe + skip marker for integration tests.

Extracted from ``backend/tests/integration/test_seed_es.py`` so test-helper
modules can depend on a stable fixture path rather than importing from a
test-collected module (which is brittle under pytest's collection order
and would silently break if the test file were ever renamed).

Lands with ``infra_study_preflight_real_engine_integration`` Story 1.1 (D-11).
The behavior is byte-equivalent to the original definitions at
``test_seed_es.py:37-57`` before this refactor — same 2.0s timeout, same
``localhost:9200`` -> ``elasticsearch:9200`` probe order, same skip-reason
wording.
"""

from __future__ import annotations

import httpx
import pytest


def _es_base_url() -> str:
    """Probe localhost:9200 first (host-shell), fall back to elasticsearch:9200 (in-container)."""
    for candidate in ("http://localhost:9200", "http://elasticsearch:9200"):
        try:
            with httpx.Client(timeout=2.0) as c:
                r = c.get(f"{candidate}/")
                if r.status_code == 200 and "version" in r.json():
                    return candidate
        except Exception:
            continue
    return ""


es_required = pytest.mark.skipif(
    not _es_base_url(),
    reason=(
        "Elasticsearch not reachable on localhost:9200 or elasticsearch:9200 — "
        "see docs/03_runbooks/local-dev.md."
    ),
)
