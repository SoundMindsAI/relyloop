"""Hermetic source-presence contract for the chore_e2e_test_rows_isolation
DELETE endpoints. Mirrors the precedent at
``test_judgments_api_contract.py:test_all_spec_error_codes_referenced_in_router_source``.

Reads ``backend/app/api/v1/_test.py`` as a string and asserts every error
code that spec §7.5 declares appears as a literal in the router source.

Why hermetic-source-presence and not just integration-envelope tests?
The integration suite (``test_test_endpoints.py``) covers runtime
behavior under DB load — but a refactor that *renames* an error-code
literal without updating callers could silently break the contract for
any path the integration tests don't exercise. The source-presence
check is the cheap defense-in-depth — runs in any environment, no DB
required.
"""

from __future__ import annotations

from pathlib import Path

_ROUTER_SOURCE = Path("backend/app/api/v1/_test.py").read_text(encoding="utf-8")

# 11 strictly new error codes from spec §7.5 + 3 reused NOT_FOUND codes that
# the new DELETE handlers also raise. RESOURCE_NOT_FOUND is the env-guard
# envelope and is already covered by the existing seed-completed test.
_NEW_ERROR_CODES = [
    # 3 strictly new NOT_FOUND codes (resources without prior /api/v1 DELETE).
    "PROPOSAL_NOT_FOUND",
    "DIGEST_NOT_FOUND",
    "STUDY_NOT_FOUND",
    # 8 strictly new HAS_DEPENDENT codes (one per non-cascade FK relationship).
    "STUDY_HAS_DEPENDENT_PROPOSAL",
    "STUDY_HAS_DEPENDENT_DIGEST",
    "JUDGMENT_LIST_HAS_DEPENDENT_STUDY",
    "QUERY_SET_HAS_DEPENDENT_STUDY",
    "QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST",
    "QUERY_TEMPLATE_HAS_DEPENDENT_STUDY",
    "QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL",
    "QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST",
]

_REUSED_ERROR_CODES = [
    # Already present in studies.py / judgments.py; reused without modification.
    "JUDGMENT_LIST_NOT_FOUND",
    "QUERY_SET_NOT_FOUND",
    "TEMPLATE_NOT_FOUND",
]


def test_test_router_declares_strictly_new_error_codes() -> None:
    """Every strictly-new error code from spec §7.5 appears in the router source."""
    missing = [code for code in _NEW_ERROR_CODES if f'"{code}"' not in _ROUTER_SOURCE]
    assert not missing, (
        f"backend/app/api/v1/_test.py is missing these strictly-new error code "
        f"literals: {missing!r}. Either the implementation drifted from spec §7.5 "
        f"or this test's allowlist needs updating."
    )


def test_test_router_declares_reused_error_codes() -> None:
    """Reused NOT_FOUND codes appear in the new DELETE handlers."""
    missing = [code for code in _REUSED_ERROR_CODES if f'"{code}"' not in _ROUTER_SOURCE]
    assert not missing, (
        f"backend/app/api/v1/_test.py is missing these reused error code "
        f"literals: {missing!r}. The new DELETE handlers should raise them "
        f"in the 404 path."
    )
