# CI-perf: docker-buildx artifact handoff + base-image cache + pytest-xdist

**Date:** 2026-05-28
**Status:** Idea — landed as the next PR after PR #290 (docker-image-bumps)
**Priority:** P1 — addresses the smoke job hitting its `timeout-minutes: 15` ceiling, which was rendering it unmergeable on PR #290 (had to admin-merge)
**Origin:** Operator question during PR #290 CI watch: "we need to optimize these actions ... take a good look at the 2 longest running actions and analyze what we can do to reduce how long these take. This is just way too long." Real-timing analysis showed:
  - `smoke (operator-path tutorial flow)` — 15m 22s, **timing out at the 15min ceiling**
  - `backend (lint + typecheck + tests + coverage)` — 8m 36s
**Depends on:** PR #290 (`414c783f`) — uses the docker-bumped image tags as the cache key.

## Problem

PR #290's smoke job ran for 15m 22s and was killed by `timeout-minutes: 15`. Per-step breakdown:

| Step | Time | Note |
|---|---|---|
| Setup + checkout + uv + deps | ~10s | already fast |
| **`docker compose up -d` (Bring up the stack)** | **10m 5s** | image pulls + API build + UI build inside the step |
| Wait for /healthz | 1s | |
| Migrations + seeds | 12s | |
| Smoke test (LLM round-trip) | 33s | |
| Verify UI + pnpm/Node setup + Playwright install | ~16s | |
| Run Playwright E2E | TBD (~3-5 min historically) | killed at the 15min ceiling |

The dominant cost is the 10-minute `make up` step, of which the API + UI Docker builds are ~5 minutes total. The dedicated `docker buildx (relyloop/api)` job is already building the API image (1m 32s) but smoke duplicates the work.

Similarly, `backend (lint + typecheck + tests + coverage)` runs `pytest backend/tests/ --cov` serially for 6m 1s on a 2-core GitHub-hosted runner. Parallelizing with `pytest-xdist -n auto` cuts this roughly in half.

## Proposed action

Three changes bundled into one CI-perf PR:

### #1 Reuse docker-buildx artifacts in smoke (~5min savings)

- Add a `Export API image as tar for smoke job` step to the existing `docker` job that `docker save`s the built API image as a tar.
- Add a `Upload API image artifact` step that uploads the tar via `actions/upload-artifact@v7` with `compression-level: 0` (the tar is already compressed by `docker save` — re-compressing wastes ~30s with no win).
- Add a parallel `docker-ui` job (symmetric to `docker`) that builds + uploads the UI image as a tar. UI build is its own bottleneck (~2-3min via `next build`) — pre-building in parallel matters as much as API.
- Make smoke `needs: [docker, docker-ui]` so it waits for both artifacts.
- Smoke downloads both artifacts + `docker load`s them into the local Docker daemon BEFORE `make up`.
- Set `RELYLOOP_GIT_SHA=${{ github.sha }}` env on the `Bring up the stack` step so compose picks up the loaded images via the `image: relyloop/api:${RELYLOOP_GIT_SHA:-dev}` references.

### #2 Cache base service-container images (~1-2min savings on cache hit)

- Add an `actions/cache@v5` step keyed on `hashFiles('docker-compose.yml')` (so any image-tag bump in compose = cache miss; otherwise hit).
- On miss: `docker pull` each of `postgres:17`, `redis:8`, `elasticsearch:9.4.1`, `opensearchproject/opensearch:3.6.0`, then `docker save` each tar into `/tmp/docker-base-images/`.
- On hit: iterate the tars and `docker load` each. ~5s for all 4 vs ~60-90s for `docker pull` on miss.

### #3 pytest-xdist + parallel test execution (~3min off backend full)

- Add `pytest-xdist>=3.6` to `[dependency-groups] dev` in pyproject.toml.
- Pass `-n auto --dist worksteal` to the backend full pytest call. `-n auto` runs 1 worker per CPU core (2 on ubuntu-latest); `--dist worksteal` is the modern default for mixed test durations (short tests fill in around long ones).
- Also add `-n auto` to the existing `backend-unit-fast` job for symmetry (~33s → ~15s).

### Supporting change: `RELYLOOP_SKIP_BUILD=1` escape hatch in install.sh

- `scripts/install.sh` step 6 calls `docker compose build` unconditionally to keep operator-pulled code in sync with the running image. In CI we pre-built both images via the buildx jobs, so this would be ~3-5min of pure duplication.
- Add a guard: `if [[ "${RELYLOOP_SKIP_BUILD:-0}" != "1" ]]; then docker compose build; else echo "..."; fi`.
- Smoke sets `RELYLOOP_SKIP_BUILD: "1"` on the `Bring up the stack` step.

## Expected impact

Combined savings:

| Job | Before | After (estimate) |
|---|---|---|
| smoke | 13-15min (timing out at 15min ceiling) | **~7-9 min** |
| backend (lint + typecheck + tests + coverage) | 8m 36s | **~4-5 min** |
| backend-unit-fast | 33s | ~15s |

Total wall-clock saved per PR run: **~7-10 min**.

The smoke job goes from "timing out, cannot merge without admin override" to "comfortably under the 15min ceiling with margin." Subsequent operations stop being held hostage by the slow path.

## Scope signals

- **Backend:** 1 LOC in pyproject.toml (`pytest-xdist>=3.6` dep).
- **Frontend:** 0 LOC.
- **CI workflow:** ~70 lines added across `.github/workflows/pr.yml`:
  - `docker` job: +12 lines (export tar + upload artifact)
  - new `docker-ui` job: +30 lines (parallel buildx + export + upload)
  - smoke job: +35 lines (download artifacts + load + base-image cache + env vars)
  - backend pytest commands: +5 lines (added `-n auto --dist worksteal` flags)
- **`scripts/install.sh`:** ~5 lines (the SKIP_BUILD escape hatch).
- **Migration:** none.
- **Audit events:** N/A.
- **Tests:** the `-n auto` change may surface DB-collision flakes in integration tests that were previously serialized. First CI run on the PR is the validation; mark any specific collisions with `@pytest.mark.xdist_group("group_name")` to serialize within a worker.

## What is NOT changed in this PR (possible follow-ups)

- **Lower `timeout-minutes` on smoke from 15 → 10.** The optimizations should bring smoke well under 10min, but leave the ceiling at 15min for safety during the transition. Lower it in a follow-up after we see 3-5 PR runs come in under target.
- **Shard backend tests across 2 parallel jobs (#5 from the analysis).** Only worth doing if `-n auto` doesn't get us under 5min on backend full. Additional runner-minutes for additional wall-clock savings.
- **Coverage on PRs vs nightly.** Coverage instrumentation adds ~10-15% pytest overhead. Could split: uncovered tests on PRs, full coverage on nightly + main. Trade-off: PR doesn't see coverage delta until merge.
- **Pull Playwright browser binary cache to actions/cache via lockfile hash.** Already cached via the existing `Cache Playwright browsers` step; minor follow-up if any drift surfaces.

## Risks

- **pytest-xdist DB collisions.** Integration tests that share DB state (Optuna RDB co-tenant, shared sequences, fixture-seeded rows) may collide under parallel execution. Mitigation: first CI run is the validation; mark collisions with `@pytest.mark.xdist_group` if they surface.
- **Artifact upload/download overhead.** API + UI tars are ~200-500MB combined. Upload + download adds ~30-60s. Net savings vs in-step build (~5min) is positive but verify on first run.
- **Cache key staleness.** `hashFiles('docker-compose.yml')` rehashes when ANY line of the compose file changes — including non-image-related changes. Acceptable: cache miss = `docker pull` runs once, populates cache. Worst case is a one-run penalty.

## Relationship to other work

- **Follows PR #290** (docker-image-bumps) which surfaced the smoke timeout by adding new image tags that invalidated the implicit Docker layer cache.
- **Closes the timeout-related portion of `bug_smoke_followup_clone_e2e_flakes`** — once the smoke job has comfortable headroom, intermittent E2E flakes stop hitting the timeout ceiling and surface as proper failures the bug tracker can investigate.
- **Composes with [`chore_drop_demo_seed_from_ci`](../chore_drop_demo_seed_from_ci/idea.md)** (also shipped in PR #290) — that one shaved ~60s by removing the demo seed; this one shaves the bigger chunk by removing the docker-build duplication.
