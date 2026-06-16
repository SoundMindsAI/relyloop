# infra_pr_yml_split_integration_by_service — Split the integration test lane by required service container

**Date:** 2026-06-16
**Status:** Idea — **deferred (defer-until-binding-constraint, posture preserved)**. Carved out of [`infra_pr_yml_split_backend_test_lanes`](../infra_pr_yml_split_backend_test_lanes/idea.md) at its 2026-06-16 split, after Win 2′ (the 3-way lane split + cov-gate plumbing) shipped as PR #531. The cov-gate infrastructure required to merge per-shard partial coverage data was the prerequisite; that's now in production.
**Priority:** Backlog — operator iteration cost, not a correctness gate. Pick up when the heavy lane's wall-clock dominance once again outweighs the cost of the per-shard service-container topology + pytest-marker pass this requires. Cleaner readout than the parent's "1-1.5 min" estimate: this attacks the new binding constraint (`backend (contract + integration + cov)` at 8m14s post-#531) directly via per-shard parallelism, so the upper-bound win is meaningful (~3 min wall-clock recovery if the shards balance correctly), not asymptotic.
**Origin:** Win 3 of the parent `infra_pr_yml_split_backend_test_lanes` idea. Spun out to its own folder on 2026-06-16 when Win 2′ shipped — the parent file kept its "history of both wins" framing but the implementable surface now lives here.
**Depends on:** [`infra_pr_yml_split_backend_test_lanes`](../infra_pr_yml_split_backend_test_lanes/idea.md) Win 2′ — **shipped** as PR #531 on 2026-06-16. The cov-gate (combine-from-multiple-artifacts) job and the `[tool.coverage.paths]` + per-lane `COVERAGE_FILE` plumbing this idea needs to extend already exist.

## Problem

After PR #531 split the heavy backend test job into three lanes (`backend-unit`, `backend-heavy`, `backend-cov-gate`), the new binding CI constraint is `backend (contract + integration + cov)` at ~8m14s. That single job:

1. Boots Postgres + Redis + Elasticsearch + OpenSearch containers (every run, ~30-60s of wall-clock just for service-container health checks).
2. Runs the full contract + integration suite **serially** (idea D-1: integration's FK-teardown collision under `pytest-xdist -n auto` is non-negotiable).

But **most integration tests don't need most of those containers**. Per a `grep` over `backend/tests/integration/test_*.py`:

| Mentions | File count | % of 139 |
|---|---|---|
| `elasticsearch` | 87 | 63% |
| (no engine — Postgres + Redis only) | 47 | 34% |
| `opensearch` | 14 | 10% |
| `solr` | 6 | 4% |

(Files can mention multiple engines via shared fixtures, so counts overlap.) The Postgres-only suite and the Solr suite both currently wait for the ES + OS containers to become healthy before even starting. That's pure dead weight.

The serialize-on-FK constraint blocks `pytest-xdist -n auto` parallelism *within* a job, but it does **not** block parallelism *across* jobs, because each job runs against its own service-container set (its own Postgres → its own database → no shared FK-state).

## Proposed capabilities

### Shard the integration lane by required service container

Replace the single `backend (contract + integration + cov)` job with a per-engine fleet:

| Shard | What runs | Service containers | Estimated time |
|---|---|---|---|
| `backend-heavy-postgres` | Integration tests that need only Postgres + Redis (47 of 139 files, all `47 mention-NONE` cases) + contract tests that boot `LifespanManager` | Postgres + Redis | ~2-3 min |
| `backend-heavy-elastic` | Integration tests that exercise Elasticsearch (~85 of 139 files, the ES-touching majority) | Postgres + Redis + Elasticsearch | ~4-5 min (new critical path) |
| `backend-heavy-opensearch` | Integration tests that exercise OpenSearch (~14 files) | Postgres + Redis + OpenSearch | ~2 min |
| `backend-heavy-solr` | Integration tests that exercise Solr (~6 files, mostly skip-gated until Solr is in CI properly) | Postgres + Redis + Solr | ~1 min (mostly skips) |

Each shard:

- **Has its own Postgres container** with its own database (no shared mutable state → FK collisions stay isolated within the shard).
- **Has only the engine container(s) its tests actually need** (the ES-only shard doesn't wait for OS to come up, etc.).
- **Writes to `COVERAGE_FILE=.coverage.heavy_<shard>`** (extending the per-lane filename pattern already in production from Win 2′) and uploads as `coverage-data-heavy-<shard>` artifact.

The existing `backend (coverage gate)` job (from Win 2′) gets extended to wait on `[backend-unit, backend-heavy-postgres, backend-heavy-elastic, backend-heavy-opensearch, backend-heavy-solr]` and combine all 5 partial coverage data files. No coverage-plumbing redesign is needed — Win 2′'s `coverage combine` mechanism already merges N inputs.

### Pytest marker pass + selection

Add `@pytest.mark.requires_postgres` (default for all), `@pytest.mark.requires_elasticsearch`, `@pytest.mark.requires_opensearch`, `@pytest.mark.requires_solr` markers. Then `-m` selection drives each shard:

```bash
# postgres shard — tests that need NO engine
pytest backend/tests/integration backend/tests/contract -m "requires_postgres and not requires_elasticsearch and not requires_opensearch and not requires_solr"

# elastic shard
pytest backend/tests/integration -m requires_elasticsearch
# (etc.)
```

The marker pass is the load-bearing implementation work — needs a scan of every integration/contract test to mark which engines it actually uses. Mismarks would cause silently-skipped tests in CI (they'd not run in any shard) or false failures (they'd run in a shard that doesn't have their engine). A `conftest.py`-level safety net could `pytest.skip()` a test that's been routed into the wrong shard, but the safer bet is to mark systematically and verify locally before shipping.

## Decisions (locked from parent idea, carried forward)

- **D-1 (locked).** Integration lane stays serial under `-n auto` — the FK-teardown collision is why. This idea parallelizes integration by **sharding across jobs** (separate DBs per shard), NOT by `-n auto` within a job.
- **D-2 (locked).** Coverage combine across N shards via `coverage combine` — the same mechanism Win 2′ shipped. Adds shards to the cov-gate's `needs:` list and downloads N artifacts instead of 2.
- **D-3 (new locked).** Each shard gets its OWN Postgres container, not a shared Postgres with multiple databases. Reason: simpler topology (existing service-container syntax extends cleanly), full collision isolation, and the per-runner GHA shape doesn't reward shared-state optimization.
- **D-4 (new locked).** Contract tests with `LifespanManager` go in the `backend-heavy-postgres` shard, not their own. They need Postgres + Redis but not any engine; the Postgres shard is already the right home. Avoids creating a fifth distinct topology.

## Open questions for /spec-gen (when revisited)

- **Total CI minutes vs wall-clock tradeoff.** Each shard runs its own Postgres + Redis + 0-1 engine container. If we ship 4 shards, GHA spins up 4× the containers per run vs today's 1× (4 postgres, 4 redis, 1 ES, 1 OS, 1 Solr = 11 containers vs today's 4). Wall-clock drops ~3 min but total CI minutes could double. Worth it? Depends on GHA-minute budget.
- **Marker-mismatch detection.** Should we add a CI guard that fails the build if a test imports `elasticsearch` but isn't marked `requires_elasticsearch`? Static analysis vs runtime detection.
- **Skip-gated Solr tests.** Are the 6 solr-mentioning tests still all skip-gated, or did `infra_solr_ci_readiness` Phase 1 (PR #367) make some of them runnable? If all still skip, the Solr shard wastes a job slot.
- **Shard granularity.** 4 shards (postgres/elastic/opensearch/solr) is the obvious split. Could go to 3 (skip solr, run with opensearch) for simplicity, or 5+ (split elastic into "with seed data" vs "without"). 4 is the sweet spot for first cut.

## Scope signals

- **Backend:** `@pytest.mark.requires_*` marker pass across `backend/tests/integration/test_*.py` + `backend/tests/contract/test_*.py` (~173 files to scan, of which ~120 likely need at least one marker beyond the default `requires_postgres`). No `backend/app/` source. Possible new `conftest.py` shape-check that fails the test if its required engines aren't actually reachable.
- **Frontend:** none.
- **Migration:** none.
- **Config:** `.github/workflows/pr.yml` — split `backend-heavy` into 4 shards, each with its own `services:` block (Postgres + Redis + 0-1 engine); extend `backend-cov-gate`'s `needs:` to 5 jobs (unit + 4 shards) + 5 artifact downloads. `pyproject.toml` may need `[tool.pytest.ini_options] markers = [...]` registration to silence the "unknown marker" warnings. `Makefile` should grow per-shard local-run targets (`make test-integration-postgres`, etc.) so developers can run a single shard locally without booting all engines.
- **Audit events:** N/A.
- **Operator impact:** CI feedback latency. Modest local-dev impact: developers running `make test-integration` locally will continue to boot everything; running a specific shard becomes possible (and faster) via the new Makefile targets.

## Why deferred (the post-Win-2′ rationale)

The Win 2′ idea (parent) flagged this as "the higher-value win if integration dominates." Integration *does* now dominate the new critical path (`backend-heavy` is 8m14s of 8m49s total). But shipping this requires:

1. A pytest-marker pass across ~173 test files — methodical, not trivial.
2. A 4-shard service-container topology in `pr.yml` (vs Win 2′'s 3 simpler lanes).
3. Per-shard local `make` target ergonomics (otherwise the local-dev "run only the postgres tests" path becomes friction).
4. A CI-minute cost analysis — likely doubles or triples total minutes per run even as it cuts wall-clock by ~30-40%.

That blast radius justifies the defer until the operator hits the pain again. Today's session (the prompt for Win 2′) showed the 18-min Gemini-fix-cycle pattern when CI is 9-10 min. Post-Win-2′, that pattern is 8m49s × 2 = ~17m44s — slightly better but still felt. If the operator hits it again and asks, this idea is ready to promote.

## Relationship to other work

- **Parent:** [`infra_pr_yml_split_backend_test_lanes`](../infra_pr_yml_split_backend_test_lanes/idea.md) — shipped Win 2′ on 2026-06-16 (PR #531). This idea extends that PR's `coverage combine` plumbing to N-way fan-out.
- **Sibling:** [`chore_pr_yml_parallelize_backend_job`](../../../implemented_features/2026_06_05_chore_pr_yml_parallelize_backend_job/idea.md) — shipped Win 1 on 2026-06-05 (drop redundant lint/mypy from the heavy job). The three-step compounding sequence is: drop redundant work (#478) → split by layer (#531) → split by service-container (this idea).
- **Sibling:** [`infra_solr_ci_readiness`](../../../implemented_features/2026_05_31_infra_solr_ci_readiness/) Phase 1 — shipped PR #367. May determine whether the `backend-heavy-solr` shard has runnable tests or is purely skip-gated; check before opening this work.
