# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Curated engine image-tag matrix for install-time version selection.

feat_engine_version_selection FR-2. The matrix is the source of truth for
which engine versions ``scripts/install.sh`` will accept via the
``RELYLOOP_ES_VERSION`` / ``RELYLOOP_OS_VERSION`` / ``RELYLOOP_SOLR_VERSION``
env vars; the entry at index ``[0]`` for each engine is also the default
that ``docker-compose.yml`` substitutes into ``${X_IMAGE_TAG:-<default>}``
when the corresponding env var is unset.

**Matrix bound.** One entry per *supported major* in the adapter
compatibility window documented at ``docs/01_architecture/adapters.md``:

* Elasticsearch 8.11+ and 9.x (per ``adapters.md`` line 147)
* OpenSearch 2.x and 3.x (per ``adapters.md`` line 148)
* Solr 9.x and 10.x (per ``adapters.md`` line 232 — runtime-enforced by
  ``SOLR_MIN_VERSION`` at ``backend/app/adapters/solr.py``)

Today the window yields exactly 2 entries per engine. When the adapter
window changes (a major is added or dropped), this matrix changes in
lockstep — NOT a fixed "last 2" count. Per-minor versions within a single
major are NOT offered: the adapter behaves identically across minors, so
extra minor rows are pure maintenance cost.

**Maintainer release-update process.** When upstream releases a new latest
patch for a supported major:

1. Update the corresponding tuple entry below.
2. If the major changed, bump the matching Compose
   ``${X_IMAGE_TAG:-<default>}`` literal in ``docker-compose.yml``.
3. Regenerate the bash mirror at
   ``scripts/lib/relyloop_engine_versions_matrix.sh`` to match.
4. Verify the smoke job passes against the new tag.

The CI guard at ``scripts/ci/verify_engine_version_matrix_parity.sh``
enforces sync between (a) this matrix and the Compose ``:-`` defaults,
and (b) this matrix and the bash mirror, on every PR.
"""

from __future__ import annotations

from typing import Final

ENGINE_VERSION_MATRIX: Final[dict[str, tuple[str, ...]]] = {
    "elasticsearch": ("9.4.1", "8.15.3"),  # latest patch of each supported major
    "opensearch": ("3.6.0", "2.18.0"),
    "solr": ("10.0", "9.7"),
}
"""Maintainer-curated valid image tags per engine.

Keys MUST stay aligned with ``backend.app.api.v1.schemas.EngineTypeWire``
— enforced by a unit test at
``backend/tests/unit/core/test_engine_versions_matrix.py``.

Tuple ``[0]`` element MUST match the corresponding
``${X_IMAGE_TAG:-<default>}`` literal in ``docker-compose.yml`` —
enforced by the matrix-parity CI guard.
"""
