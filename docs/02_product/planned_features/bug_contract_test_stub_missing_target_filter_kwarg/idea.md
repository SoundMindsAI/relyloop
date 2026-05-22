# Two contract tests crash on `target_filter` kwarg the stub doesn't accept

**Date:** 2026-05-22
**Status:** Idea — bug discovered during `feat_orchestrator_zero_streak_abort` phase gate
**Priority:** P2 — `make test-contract` reports `2 failed, 282 passed` so anyone running the full local suite hits it; CI may be passing because the failures are masked, masked, or because the relevant contract suite isn't on the affected lane.
**Origin:** Surfaced 2026-05-22 during the `feat_orchestrator_zero_streak_abort` phase gate (commit chain `ac64a2a..385ec63` on branch `feature/orchestrator-zero-streak-abort`). I ran the full contract suite to confirm the new feature didn't regress anything; 2 tests failed with a `TypeError` that was pre-existing on `main` (confirmed by `git stash` + re-run on a clean tree — the failure reproduces without any of my changes loaded). The new feature did NOT introduce this; capturing as a separate idea per the tangential-discoveries protocol in CLAUDE.md.

## Problem

`backend/tests/contract/test_error_codes.py::TestErrorCodes::test_targets_forbidden` and `::test_targets_unreachable_via_adapter` both define an inline `_Stub` class whose `list_targets` method has the **pre-`feat_cluster_target_filter`** signature:

```python
# backend/tests/contract/test_error_codes.py:195-197 (and again at 238-240)
class _Stub:
    async def list_targets(self, *, request_id: str | None = None):
        raise TargetsForbiddenError(...)
```

But the production code at [`backend/app/api/v1/clusters.py:359`](../../../../backend/app/api/v1/clusters.py) calls:

```python
targets = await adapter.list_targets(target_filter=cluster.target_filter)
```

The `target_filter` kwarg was added by [`feat_cluster_target_filter`](../../00_overview/implemented_features/2026_05_20_feat_cluster_target_filter/feature_spec.md) (PR #168, merged 2026-05-20) and threaded through the adapter Protocol. The contract test stubs were never updated — they crash with `TypeError: _Stub.list_targets() got an unexpected keyword argument 'target_filter'`.

The crash happens BEFORE the test's actual assertion (which is about the `TARGETS_FORBIDDEN` / `CLUSTER_UNREACHABLE` error codes being returned in the standard envelope), so the tests are effectively dead — they no longer verify what they claim to verify.

## Why not fixed inline with feat_orchestrator_zero_streak_abort

Per the inline-fix-vs-idea-file rubric in CLAUDE.md, this fix touches a different subsystem entirely (cluster targets endpoint, adapter Protocol stubs in contract tests) than the orchestrator zero-streak feature. Bundling it would have crossed the subsystem-mixing line and confused the PR's narrative. The fix is bounded — ~6 LOC across one file — and belongs in its own PR.

## Proposed fix

Update both `_Stub` classes in [`backend/tests/contract/test_error_codes.py:194-208`](../../../../backend/tests/contract/test_error_codes.py) and [`backend/tests/contract/test_error_codes.py:237-251`](../../../../backend/tests/contract/test_error_codes.py) to add the `target_filter: str | None = None` kwarg to `list_targets`. The kwarg is unused by the stubs (they raise immediately) — it just needs to be accepted to match the Protocol signature.

```python
class _Stub:
    async def list_targets(
        self,
        *,
        request_id: str | None = None,
        target_filter: str | None = None,
    ):
        raise TargetsForbiddenError(...)
```

## Scope signals

- **Backend:** ~6 LOC across one file. No production code change.
- **Frontend:** none.
- **Migration:** none.
- **Tests:** the 2 failing contract tests start passing once the stub signature matches. Run `uv run pytest backend/tests/contract/test_error_codes.py -v` to verify.
- **Estimated size:** small — 5–10 minutes including the in-container test run.

## Relationship to other work

- Caused by [`feat_cluster_target_filter`](../../00_overview/implemented_features/2026_05_20_feat_cluster_target_filter/feature_spec.md) (PR #168) extending the adapter Protocol without updating the contract test stubs. Not the spec author's fault per se — contract tests with locally-defined stubs are easy to miss when grepping for adapter Protocol consumers; this is a structural fragility worth noting.
- Composes with [`feat_orchestrator_zero_streak_abort`](../feat_orchestrator_zero_streak_abort/feature_spec.md) only in the sense that running its phase gate exposed the pre-existing bug.

## Anti-pattern note

The right systemic fix would be to extract a shared `_BaseStubAdapter` that's automatically kept in sync with the `SearchAdapter` Protocol (e.g., via `typing.Protocol` + `mypy --strict` checking on the stubs in CI). That's larger than this fix and belongs in its own `chore_*` idea (filed only if this kind of drift recurs).
