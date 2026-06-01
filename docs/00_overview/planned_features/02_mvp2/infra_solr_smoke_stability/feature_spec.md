# Feature Specification — `infra_solr_smoke_stability`

**Date:** 2026-06-01
**Status:** Draft
**Owners:** Eric Starr (engineering lead)
**Related docs:**
- [`idea.md`](./idea.md)
- [`infra_solr_ci_readiness` Phase 1 (shipped, PR #367)](../../../implemented_features/2026_06_01_infra_solr_ci_readiness/feature_spec.md)
- [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](../../../../03_runbooks/demo-reseed-engine-tolerance.md) — Phase 1 runbook (the backend-half story)

---

## 1) Purpose

- **Problem:** The `pr.yml` `smoke (operator-path tutorial flow)` job is red on every branch. It runs `make up`, which brings up the full Compose stack including the `solr:10.0` service; on the GHA `ubuntu-24.04` runner the Solr container crashes during boot (`relyloop-solr-1 exited (1)`), failing the smoke job at [`Makefile:109`](../../../../../Makefile#L109) (`bash scripts/install.sh`). The `pr.yml` failure-diagnostics step ([`.github/workflows/pr.yml:716-728`](../../../../../.github/workflows/pr.yml#L716-L728)) collects Compose logs for `api worker postgres redis elasticsearch ui` but neither `solr` nor `opensearch`, so the actual crash reason is invisible from CI artifacts. `infra_solr_ci_readiness` Phase 1 (PR #367, merged 2026-06-01) addressed only the `backend` job's reseed failure — the smoke job stays red until this work ships.
- **Outcome (two halves, sequenced for honesty):** **(A) Diagnostics in place — guaranteed.** Compose log artifacts on smoke failure include all three engines (Solr + OpenSearch added; ES already covered), so future runner regressions are diagnosable from CI alone. This half lands no matter what. **(B) Optimistic heap-cap fix — attempted.** Lever 1 (Solr heap cap to 256m) is applied to the smoke job in the same PR; if it fixes the crash, the smoke job goes green and the "every `pr.yml` job green" contract that started with Phase 1 is complete. If it doesn't (e.g., non-heap memory failure), the now-captured Solr logs feed an FR-3 follow-up that picks Lever 2 or 3 from evidence. The smoke debt is marked resolved in `state.md` only if (B) succeeds; if only (A) lands, the debt entry is updated with the captured evidence + the follow-up spec link.
- **Non-goal:** This spec does NOT change the live-Solr integration tests scaffolded but not exercised by `infra_adapter_solr` (those live in [`chore_solr_post_pipeline_followups`](../chore_solr_post_pipeline_followups/idea.md)). It does NOT add a Solr service container to the backend job — Phase 1's engine-tolerant reseed already made that unnecessary. It does NOT change the `solr.UBIComponent`-not-in-stock-image story or any product behavior.

## 2) Current state audit

### Existing implementations

- [`.github/workflows/pr.yml:487-738`](../../../../../.github/workflows/pr.yml#L487-L738) — `smoke-test` job (the `docker:` job follows at line 739). Runs `make up` (line 629), waits for `/healthz` (lines 631-642), runs migrate + seed + Playwright/pytest. Has no Solr-specific health wait — the api's `/healthz` probes Solr as one of five parallel subsystem checks (with a 200ms timeout per CLAUDE.md), so a missing Solr surfaces as a subsystem-status field, not a job failure.
- [`.github/workflows/pr.yml:719`](../../../../../.github/workflows/pr.yml#L719) — `docker compose logs --no-color api worker postgres redis elasticsearch ui > smoke-logs.txt 2>&1`. The smoke job's failure-diagnostics collect step; missing `solr` and `opensearch`.
- [`docker-compose.yml:271-285`](../../../../../docker-compose.yml#L271-L285) — `solr` service block. Reads `SOLR_HEAP: ${SOLR_HEAP_SIZE:-512m}` (line 274); healthcheck has `start_period: 30s` (line 285), `interval: 10s`, `timeout: 5s`, `retries: 6`. Total tolerance before the container is marked unhealthy: up to ~95s, depending on how Docker schedules the first probe and whether failing probes consume the full 5s timeout vs. fail-fast.
- [`.github/workflows/pr.yml:287`](../../../../../.github/workflows/pr.yml#L287) — the backend job sets `ES_JAVA_OPTS: "-Xms256m -Xmx256m"` for its Elasticsearch service container. This is the precedent for the smoke job's Solr heap override.

### Navigation and link impact

| Source file | Current reference | New reference |
|---|---|---|
| `CLAUDE.md` (Key Runbooks table) | — | Add row → [`docs/03_runbooks/smoke-solr-stability.md`](../../../../03_runbooks/smoke-solr-stability.md) |
| `state.md` (Known debt) | "Smoke half still open (Phase 2)" entry | Strike (Phase 2 has now shipped) |

No UI, no API, no operator-facing URL repointing. The two doc edits above are the only navigation changes.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `.github/workflows/pr.yml` (`smoke-test` job) | `docker compose logs ... api worker postgres redis elasticsearch ui` | 1 | Add `solr` + `opensearch` to the service list |
| `.github/workflows/pr.yml` (`smoke-test` job) | `env:` block on the `make up` step | 1 | Add `SOLR_HEAP_SIZE: "256m"` |

No backend pytest, frontend vitest, or Playwright spec changes. Verification routes through AC-1 (smoke RAN + non-smoke jobs green), AC-2 (diagnostics artifact on red runs), AC-4 (static workflow assertions — covers diagnostics correctness on green runs) — not "green smoke is required."

### Existing behaviors affected by scope change

- **Smoke job's tolerance to Solr boot.** Current: implicit, undocumented — depends on whether the `solr` healthcheck reports healthy before any step that needs the api to have probed Solr. New: explicit — the smoke job caps Solr heap at 256m to reduce JVM memory pressure on the runner. The cap is a hypothesis; the runner's exact memory budget is not cited because it's not load-bearing for the decision (the rationale is "cheapest available lever," not "sized to a specific budget"). Decision needed: **no** — the lever choice is locked in §19.

---

## 3) Scope

### In scope

- **FR-1:** Failure-diagnostics fold-in. The smoke-test job's "Collect docker compose logs on failure" step ([`pr.yml:716-728`](../../../../../.github/workflows/pr.yml#L716-L728)) is extended to capture `solr` AND `opensearch` Compose logs.
- **FR-2:** Lever 1 (heap-cap) applied. `SOLR_HEAP_SIZE: "256m"` is set in the smoke job's `make up` step env block, alongside `RELYLOOP_SKIP_AUTO_SEED: "1"`. This mirrors the backend job's `ES_JAVA_OPTS: -Xms256m -Xmx256m` precedent.
- **FR-3:** Verification — the smoke job must RUN on the same PR that ships FR-1 + FR-2. If smoke is GREEN, AC-4's static workflow check is the proof that FR-1's diagnostics half is correctly applied (the actual log artifact is not produced on a green run). If smoke is RED, AC-2 becomes the runtime gating check (the artifact must contain `relyloop-solr-1` + `relyloop-opensearch-1` sections). Green smoke is the desired outcome; if Lever 1 doesn't fix the crash, the PR can still merge (`main` no longer enforces heavy-CI checks per `state.md`), but a follow-up spec MUST be filed AND linked from this PR's body BEFORE merge (not after), so the forcing function is mechanical rather than time-based.
- **FR-4:** Runbook entry. A new file at `docs/03_runbooks/smoke-solr-stability.md` (canonical path, not "extend existing") documents the heap-cap rationale, the lever cascade (1 → 2 → 3) with explicit escalation triggers, and the diagnostic-first workflow ("read the smoke-logs artifact's `relyloop-solr-1` section before picking a lever").

### Out of scope

- Lever 2 (`start_period` bump) and Lever 3 (smoke-tolerance of Solr-down). These are escalation paths if Lever 1 doesn't resolve the crash; the runbook (FR-4) documents the **starting-point edit** for each, but per D-4 neither is genuinely one-line in scope — Lever 2 needs a CI-only env override for the healthcheck (so local dev isn't slowed), Lever 3 needs to audit the tutorial-path smoke pytest's assumptions about Solr availability. If triggered, either gets its own spec scoped to the evidence captured by FR-1.
- Live-Solr integration tests in CI ([`chore_solr_post_pipeline_followups`](../chore_solr_post_pipeline_followups/idea.md)).
- The `solr.UBIComponent`-not-in-stock-image story (no change; Phase 1 made the demo reseed already handle this).
- Any change to the `backend` job's Solr posture (already handled by Phase 1 — backend is engine-tolerant via reachability probe).
- Any change to local dev — `docker-compose.yml`'s Solr block is untouched. The heap override is GHA-only, set via env at job scope.

### API convention check

N/A — this spec adds no API endpoints. No router, no auth, no error envelope.

### Phase boundaries

**Single-phase spec.** The work splits naturally into two commits within one PR (FR-1 lands first as a one-line YAML edit; FR-2 lands second alongside it) but ships in a single PR. The idea's "two PRs" framing was the cautious sequence for the case where Lever 1 might not work; choosing Lever 1 as the locked default (D-1) plus the relaxed AC-1 / D-6 stance ("smoke red is allowed to merge because the diagnostics half is the durable value") collapses the sequence into one PR without sacrificing safety. The worst case is a smoke job that's no greener than before — at which point the new Solr+OpenSearch diagnostics artifact tells the FR-3 follow-up which lever to try next, AND the diagnostics half has already landed (so the next iteration is not blind).

**Deferred phase tracking:** No deferred phase; the escalation paths (Lever 2, Lever 3) are documented in §19's decision log + runbook, not as a `phase2_idea.md`. Captured in §19 below as the explicit follow-up path.

## 4) Product principles and constraints

- **Local dev never carries CI-only env vars.** `SOLR_HEAP_SIZE=256m` is a GHA-runner tuning value — it lives in `.github/workflows/pr.yml`, never in `.env.example` or `docker-compose.yml`. The Compose default of 512m stays correct for the operator laptop.
- **CI failures must be diagnosable from artifacts alone.** Operators investigating a red smoke job should not need to re-run with extra logging — every service the smoke job depends on must be in the failure-diagnostics collect list. Phase 1 established this contract for the backend job (engine-reachability probe ⇒ skip + WARN log); this work extends it to the smoke job's diagnostics step.
- **Match the precedent.** The backend job already caps ES heap at `-Xms256m -Xmx256m` ([`pr.yml:287`](../../../../../.github/workflows/pr.yml#L287)) on the same `ubuntu-24.04` runner class. Solr 10's default heap (512m) is roughly twice that on a runner already running api + worker + postgres + redis + elasticsearch + opensearch + ui. Heap-cap is the most likely root cause and the cheapest, lowest-risk lever.

### Anti-patterns

- **Do not** change `docker-compose.yml`'s `${SOLR_HEAP_SIZE:-512m}` default to `256m`. That would silently make local Solr slower for every operator. The override slot was added precisely so CI can choose differently from the operator default.
- **Do not** skip FR-1 (the diagnostics fold-in) and apply only FR-2. If the heap cap doesn't fix the crash, the next failure must produce Solr logs in the smoke-logs artifact — otherwise the next iteration is blind. Diagnostics-first is a hard ordering invariant.
- **Do not** wrap Solr boot in a custom health-poll step in the smoke job. The api's `/healthz` already probes Solr; if Solr is down post-Lever-1, the smoke job will surface that via the api's `subsystems.solr` field. Adding a redundant poll obscures the path of evidence (operator reads `/healthz` first, then docker logs second).
- **Do not** apply Levers 1 + 2 + 3 all at once "just in case." Levers 2 and 3 mask different failure modes than Lever 1 — applying them blindly hides whatever the real root cause is, and the next regression (when Solr starts crashing again for a different reason) is harder to debug.

## 5) Assumptions and dependencies

- **Dependency:** `infra_solr_ci_readiness` Phase 1 (PR #367, merged 2026-06-01).
  - **Why required:** Phase 1 established the contract that "Solr is allowed to be missing in CI" on the backend job. The smoke job's posture changes here are a parallel statement of the same contract: Solr boot is allowed to be unreliable, and CI must produce evidence either way.
  - **Status:** Merged.
  - **Risk if missing:** None now that it's shipped.
- **Dependency:** GHA standard `ubuntu-24.04` / `ubuntu-latest` runner class. The heap-cap is a hypothesis sized against the published runner memory budget (per the GitHub docs at the time of writing); we are NOT citing a measured Solr-on-the-runner OOM trace because that evidence is exactly what FR-1 produces. If the captured logs show a non-heap memory failure mode (metaspace exhaustion, native memory, total-runner pressure from sibling JVMs), Lever 1 may not be sufficient and the follow-up per FR-3 must address that.
  - **Status:** All `pr.yml` jobs use `ubuntu-24.04` or `ubuntu-latest` (verified via grep). No self-hosted runner in scope.
  - **Risk if missing:** A future migration to ARM runners or self-hosted runners with different memory budgets would re-trigger the smoke flake; the runbook entry calls this out.

## 6) Actors and roles

- **Primary actor:** RelyLoop maintainer landing a PR.
- **Role model:** N/A — pre-MVP4, single-tenant, no auth surface.
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface (per [`tech-stack.md` §"Canonical release matrix"](../../../../01_architecture/tech-stack.md)).

### Audit events

N/A — this work mutates no tenant-visible state. The only writes are to the GHA workflow YAML, which is source-controlled (every change is a git commit, which is the audit trail for CI changes).

## 7) Functional requirements

### FR-1: Smoke-job failure-diagnostics fold-in (`solr` + `opensearch`)

- Requirement:
  - The smoke-test job's "Collect docker compose logs on failure" step ([`.github/workflows/pr.yml:716-728`](../../../../../.github/workflows/pr.yml#L716-L728)) **MUST** include `solr` and `opensearch` in the `docker compose logs` service list. Final form: `docker compose logs --no-color api worker postgres redis elasticsearch opensearch solr ui > smoke-logs.txt 2>&1 || true` (the trailing `|| true` is mandatory because the diagnostics step is intentionally best-effort — adding services must not cause the step to fail if one service's logs can't be collected).
  - To diagnose total-runner-memory failures (where Solr is OOM-killed by the kernel rather than throwing a Solr-internal OOM trace), the diagnostics step **SHOULD** also append `docker compose ps -aq | xargs -r docker inspect --format '{{.Name}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} error={{.State.Error}}' >> smoke-logs.txt 2>&1 || true` so per-container `OOMKilled` flags + exit codes are captured. (`docker compose ps --format json` does NOT include `OOMKilled` — that field lives in `docker inspect`'s `State` struct.) The `|| true` keeps the diagnostics best-effort.
- Notes: This is a one-line YAML edit. Pre-existing — `opensearch` is also missing from the list today (the smoke job ships an OpenSearch container per [`docker-compose.yml:235`](../../../../../docker-compose.yml#L235)) — folding both in costs nothing.

### FR-2: Lever 1 applied — cap Solr heap at 256m for the smoke job

- Requirement:
  - The smoke-test job **MUST** set `SOLR_HEAP_SIZE: "256m"` in the env block of the "Bring up the stack" step ([`.github/workflows/pr.yml:620-629`](../../../../../.github/workflows/pr.yml#L620-L629) — `env:` at line 621, `run: make up` at line 629), alongside the existing `RELYLOOP_GIT_SHA`, `RELYLOOP_SKIP_BUILD`, and `RELYLOOP_SKIP_AUTO_SEED` entries.
  - The smoke-test job **MUST** also set `COMPOSE_PROJECT_NAME: "relyloop"` at **job-level `env`** (not step-level — GHA step env does NOT persist to later steps, and the failure-diagnostics step at line 716-728 must see the same project name as `make up` so `docker compose logs` finds the same stack). This pins the container-name prefix (`relyloop-solr-1`, `relyloop-opensearch-1`) so the AC-2 diagnostics grep is deterministic.
  - The `docker-compose.yml` `solr` service block **MUST NOT** change — the Compose default of `${SOLR_HEAP_SIZE:-512m}` is correct for local dev and is what the env-var override slots into.
  - The change **MUST NOT** alter the heap for any other Compose service (postgres, redis, elasticsearch, opensearch, api, worker, ui).
- Notes: The 256m value mirrors the backend job's ES_JAVA_OPTS precedent at [`pr.yml:287`](../../../../../.github/workflows/pr.yml#L287). This is a **hypothesis** — we do not yet have a measured Solr-on-the-runner OOM trace (FR-1 produces that evidence). The hypothesis: Solr 10 + the `ltr` module fits in 256m for the synthetic CI workload, matching the same pattern that works for Elasticsearch. If the captured logs show metaspace OOM, native memory exhaustion, or a non-memory crash, Lever 1 will not be sufficient and FR-3's follow-up applies.

### FR-3: Smoke job runs; outcome triages cleanly; follow-up filed if needed

- Requirement:
  - On the PR that ships FR-1 + FR-2, the `pr.yml` `smoke (operator-path tutorial flow)` job **MUST** RUN to completion (success OR failure — not cancelled / skipped).
  - All other `pr.yml` jobs **MUST** pass on the same run (the full required-job list is enumerated in AC-1).
  - **If smoke is green:** Lever 1 fixed the crash. Merge normally.
  - **If smoke is red:** AC-2 MUST be satisfied (the diagnostics artifact contains Solr + OpenSearch logs proving FR-1 works). The PR may still merge on the fast lane (per D-6 + `state.md`'s no-heavy-CI-required posture), AND a **follow-up artifact for Lever 2 (or Lever 3)** — at minimum an idea-stage `idea.md` in its own planned-features folder — MUST be filed AND linked from this PR's body **BEFORE merge** (per cycle-3 finding #7 — a mechanical forcing function rather than a 48-hour promise). The forcing function is the PR-body link, not the artifact's depth — a tiny idea file is acceptable for a one-line lever-YAML follow-up; a full spec is overkill for that scope.
- Notes: This requirement replaces the original "green smoke is the merge gate" framing per cycle-1 cross-model finding #10. The diagnostics half (FR-1) is the durable value of this work — it lands regardless of lever outcome. The lever half (FR-2) is the optimistic attempt at fixing the crash with the cheapest known lever; if it fails, the evidence it produces is what unblocks the next iteration.

### FR-4: Runbook entry

- Requirement:
  - A new runbook file at `docs/03_runbooks/smoke-solr-stability.md` (canonical path; do NOT extend an existing runbook — keep concerns separate) **MUST** be created documenting: (a) the heap-cap rationale and the GHA-runner-only scope; (b) the lever cascade (Lever 1 → Lever 2 → Lever 3) for future smoke-job Solr failures, with **evidence-mapped escalation triggers** (not symptom-mapped): "slow boot that later becomes healthy (logs show Solr listening but past the healthcheck window) → Lever 2 (start_period bump); JVM heap/metaspace/native-memory OOM or kernel `OOMKilled: true` → memory tuning revisit (cap sibling JVMs ES + OpenSearch, not just bump start_period — the cycle-2 NFR known risk); Solr unavailable but tutorial smoke path doesn't actually depend on Solr → Lever 3 (smoke-tolerance)"; (c) the diagnostic-first workflow — "read smoke-logs artifact's `relyloop-solr-1` section AND the `docker inspect` exit-state line BEFORE picking a lever."
  - The CLAUDE.md "Key Runbooks" table **MUST** be updated with a row linking to `docs/03_runbooks/smoke-solr-stability.md`, similar to the existing "Demo reseed engine tolerance" row.
- Notes: The runbook section is the durable artifact — without it, a future maintainer hitting the next Solr CI flake has no documented path through the levers.

## 8) API and data contract baseline

### 8.1 Endpoint surface

N/A — no API endpoints.

### 8.2 Contract rules

N/A.

### 8.3 Response examples

N/A.

### 8.4 Enumerated value contracts

N/A — no filters, badges, or enums introduced.

### 8.5 Error code catalog

N/A.

## 9) Data model and state transitions

N/A — no schema changes. Alembic head stays `0022_solr_engine_auth_check`.

## 10) Security, privacy, and compliance

- **Threats:** None — the change is GHA-config-only.
- **Controls:** GHA workflow file is source-controlled; every edit is a reviewable git commit.
- **Secrets/key handling:** No new secrets. `SOLR_HEAP_SIZE` is non-sensitive tuning data and ships in the workflow YAML cleartext.
- **Auditability:** Git history is the audit trail.
- **Data retention/deletion/export impact:** None.

## 11) UX flows and edge cases

N/A — no UI surface. The "user" here is the maintainer reading CI status on the PR page.

## 12) Given/When/Then acceptance criteria

### AC-1: Smoke job runs; outcome triages cleanly

- Given the PR branches off `main` (which carries the `infra_solr_ci_readiness` Phase 1 merge).
- When the PR's `pr.yml` workflow runs.
- Then the `smoke (operator-path tutorial flow)` job runs to completion (either `success` or `failure`, NOT `cancelled` or `skipped`), AND every other `pr.yml` job — enumerated exactly as the workflow declares (no ellipses) — completes with `success`:
  - `backend (unit tests — fast lane)`
  - `license-headers`
  - `license-inventory`
  - `static-checks (backend — ruff + mypy + guards, always-run)`
  - `static-checks (frontend — prettier + eslint + tsc + vitest, always-run)`
  - `backend (lint + typecheck + tests + coverage)`
  - `frontend (lint + typecheck + tests + build)`
  - `docker buildx (relyloop/api)`
  - `docker buildx (relyloop/ui)`
- Any `skipped` outcome on the non-smoke jobs (e.g., due to a path filter or `if:` guard not satisfied) MUST be treated as a failed AC-1 unless explicitly documented as expected behavior for that PR's diff (e.g., a docs-only PR may skip backend tests — but this spec's PR touches `.github/workflows/pr.yml`, so no path filter skip should fire).
- **Re-derive before implementing.** The job list above is captured at spec time (2026-06-01). Before /impl-execute starts, re-derive the list from the actual `pr.yml` HEAD with `python3 -c "import yaml; wf=yaml.safe_load(open('.github/workflows/pr.yml')); [print(j.get('name', jid)) for jid, j in wf['jobs'].items()]"` — if any job has been added, removed, or renamed since spec time, update AC-1's list before merge.
- Outcome triage:
  - **Smoke green:** Lever 1 fixed the crash — happy path; PR merges normally.
  - **Smoke red:** Lever 1 did not fix the crash; AC-2 then becomes the gating verification (the diagnostics artifact MUST contain Solr logs). PR is still mergeable on the fast lane (`main` no longer enforces heavy-CI checks per `state.md`); FR-3 requires a follow-up spec within 48 hours.
- Example values (use the exact GHA job display names, NOT slugs):
  - Verification: `gh run view <run_id> --json jobs -q '.jobs[] | select(.name != "smoke (operator-path tutorial flow)") | "\(.conclusion)\t\(.name)"'` shows every non-smoke job as `success`.

### AC-2: Failure-diagnostics artifact contains Solr + OpenSearch logs (when smoke is red)

- Given a smoke-job failure on a run of this PR's branch (which carries FR-1 + FR-2). **Pre-PR-#367 artifacts are NOT acceptable evidence** — they were produced by the old workflow before FR-1 applied. AC-2 must be verified on a post-FR-1 run.
- When the "Upload failure diagnostics" step uploads `smoke-logs.txt`.
- Then the file contains both Solr AND OpenSearch container log lines. The smoke job MUST set `COMPOSE_PROJECT_NAME=relyloop` in its env block alongside `SOLR_HEAP_SIZE` (FR-2) — this pins the container-name prefix to `relyloop-solr-1` / `relyloop-opensearch-1` so the verification grep is deterministic (Docker Compose's default project name is the working-dir basename, which is `relyloop` on every GHA checkout today but is not contractually guaranteed; pinning removes the dependency).
- Example values:
  - Verification (in CI artifact post-download): `grep -Eq '^solr-1[[:space:]]+\|' smoke-logs.txt && grep -Eq '^opensearch-1[[:space:]]+\|' smoke-logs.txt`.
- **If the smoke job happens to go green on the run (Lever 1 worked):** AC-2's runtime check is NOT required — AC-5's static workflow verification (the `docker compose logs` command in pr.yml includes `solr` and `opensearch`) proves the diagnostics half is correctly applied. A scratch failure is not forced because (a) it is operationally noisy and (b) injecting a failure before `make up` succeeds would produce zero Solr containers and therefore zero Solr logs — falsely failing AC-2.

### AC-3: Local `make up` is unaffected (verified by `docker compose config`, not runtime)

- Given a checkout of this PR's branch.
- When `docker compose config` runs (no env overrides set — i.e., no `SOLR_HEAP_SIZE` in the shell environment, no `.env` override).
- Then the rendered `solr` service block contains `SOLR_HEAP: 512m` (the Compose default), AND `docker-compose.yml` is unchanged versus `main` (the heap override lives only in `.github/workflows/pr.yml`).
- Example values:
  - Verification (structural — robust against re-ordering of the `environment:` block): `docker compose config --format json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['services']['solr']['environment']['SOLR_HEAP'])"` returns `512m`.
  - And: `git diff main -- docker-compose.yml` returns no diff.

### AC-4: GHA workflow env interpolation resolves to `SOLR_HEAP=256m` under the smoke job

- Given the smoke-test job's env block on this PR's branch.
- When the workflow renders (verifiable statically without running CI by parsing the YAML).
- Then the "Bring up the stack" step's env block contains `SOLR_HEAP_SIZE: "256m"` (step-level — affects `make up`), AND the smoke-test job's job-level `env:` contains `COMPOSE_PROJECT_NAME: "relyloop"` (job-level — persists to every later step including failure-diagnostics per cycle-3 finding #1), AND a `SOLR_HEAP_SIZE=256m docker compose config` invocation against the unchanged `docker-compose.yml` renders the `solr` service's `SOLR_HEAP` as `256m`.
- Example values:
  - YAML parse — step-level: `python3 -c "import yaml; wf=yaml.safe_load(open('.github/workflows/pr.yml')); steps=wf['jobs']['smoke-test']['steps']; step=next(s for s in steps if (s.get('run') or '').strip()=='make up'); assert (step.get('env') or {}).get('SOLR_HEAP_SIZE')=='256m', step.get('env')"` succeeds (selects the `make up` step specifically — does NOT merge across all steps).
  - YAML parse — job-level: `python3 -c "import yaml; wf=yaml.safe_load(open('.github/workflows/pr.yml')); job=wf['jobs']['smoke-test']; assert (job.get('env') or {}).get('COMPOSE_PROJECT_NAME')=='relyloop', job.get('env')"` succeeds.
  - Structural Compose check: `SOLR_HEAP_SIZE=256m docker compose config --format json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['services']['solr']['environment']['SOLR_HEAP'])"` returns `256m`.

### AC-5: Runbook lever cascade is reachable from CLAUDE.md

- Given a maintainer reading [CLAUDE.md](../../../../../CLAUDE.md) "Key Runbooks" table.
- When they look up "smoke job Solr stability" / "GHA Solr crash" / similar phrasing.
- Then a row in the table links to `docs/03_runbooks/smoke-solr-stability.md` which documents Levers 1/2/3 with escalation triggers and the diagnostic-first workflow.
- Example values:
  - Verification: `grep -q 'smoke-solr-stability.md' CLAUDE.md && test -f docs/03_runbooks/smoke-solr-stability.md`.

## 13) Non-functional requirements

- **Performance:** No new runtime cost. The heap cap reduces Solr's JVM memory footprint by ~256MB on every CI run, which marginally reduces overall runner memory pressure (downstream side benefit: api/worker/postgres/redis have more headroom).
- **Reliability:** If Lever 1 is the correct lever, smoke pass rate on `pr.yml` should rise toward 100%. We do not have historical pass-rate metrics — Phase 1's merge timeline means baseline is "100% red on smoke since Solr added on 2026-05-31."
- **Known risk (not addressed in this spec):** The smoke Compose stack runs **three JVM services concurrently** (Elasticsearch, OpenSearch, Solr). The backend job caps ES heap (`ES_JAVA_OPTS: -Xms256m -Xmx256m`) but that env applies to GHA service containers, not to the smoke job's Compose stack. So the smoke stack's ES and OpenSearch run at their Compose defaults today. If the captured Solr logs reveal total-runner memory pressure (e.g., kernel-level OOM-killer signal rather than a Solr-internal OOM trace), the fix is not Solr-specific — it requires capping ES + OpenSearch heap in the smoke Compose path too. That work is OUT OF SCOPE here but is flagged for the follow-up spec triggered by FR-3.
- **Operability:** No change to operator-visible behavior. CI maintainers gain diagnosis-time evidence (Solr + OpenSearch logs in failure artifacts).
- **Accessibility/usability:** N/A.

## 14) Test strategy requirements

This work has no backend, frontend, or domain-logic surface — the existing test pyramid is unchanged. The smoke-job itself is the integration test for FR-2 and FR-3; the static-checks YAML lint + the workflow validation steps in GHA exercise FR-1.

| Layer | Coverage |
|---|---|
| Unit (`backend/tests/unit/`) | N/A — no Python code changes |
| Integration (`backend/tests/integration/`) | N/A — no Python code changes |
| Contract (`backend/tests/contract/`) | N/A — no API changes |
| E2E (`ui/tests/e2e/`) | N/A — no UI changes |
| Smoke job (`.github/workflows/pr.yml` `smoke-test`) | The smoke job's own green-on-green outcome is the verification (AC-1). No new pytest spec; the existing tutorial-path smoke spec runs as-is. |
| Workflow YAML static validation | YAML parse + structural assertion of the `SOLR_HEAP_SIZE` / `COMPOSE_PROJECT_NAME` env keys per AC-4 (run as part of pre-push gate, not a CI job). GHA's implicit YAML-load check on push is a backstop but is NOT a lint job — it only prevents totally invalid workflows from being scheduled. |
| Runbook verification | `test -f docs/03_runbooks/smoke-solr-stability.md && grep -q 'smoke-solr-stability.md' CLAUDE.md` — verified at PR review (AC-5). |

## 15) Documentation update requirements

- `docs/01_architecture/`: no change. The Compose Solr block is unchanged; the architecture doc's Solr description stays accurate.
- `docs/02_product/`: no change (CI infra, not a product feature).
- `docs/03_runbooks/`: create new `smoke-solr-stability.md` per FR-4 (canonical path locked in §3 / FR-4).
- `docs/04_security/`: no change.
- `docs/05_quality/`: no change (CI infra outcome is captured in `testing.md`'s pyramid; the smoke layer is unchanged).
- `CLAUDE.md`: add a "Key Runbooks" row pointing at the new runbook section per AC-5.
- `state.md`: update "Last 5 merges" + "Known debt" entries. **The "smoke half still open" debt entry is marked RESOLVED only if smoke went green on the merge run (Lever 1 worked).** If smoke merged red on the fast lane (D-6 path), the debt entry is UPDATED to record the captured evidence (Solr exit reason from the smoke-logs artifact) + a link to the FR-3 follow-up spec, NOT marked resolved. Update at finalization.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None — CI infra, ships atomically with the PR's merge.
- **Migration/backfill expectations:** None.
- **Operational readiness gates:** The smoke job must RUN to a non-cancelled/non-skipped conclusion on this PR's own run (AC-1). If it passes, Lever 1 worked — happy path. If it fails, AC-2 becomes the gating check (the diagnostics artifact must contain Solr + OpenSearch logs proving FR-1 worked); merge is still allowed on the fast lane per D-6 (mutable-branch-protection caveat below), and the captured evidence drives the FR-3 follow-up spec within 48 hours.
- **Branch-protection caveat for the red-merge path:** D-6 relies on `main` not enforcing the smoke job as a required status check (the rule was removed 2026-05-31 per `state.md`). Before merging in the smoke-red case, the implementer MUST re-verify branch protection is still permissive: `gh api repos/SoundMindsAI/relyloop/branches/main/protection 2>/dev/null` returns 404 (no protection) OR the `required_status_checks` does not list the smoke job. If protection has been re-enabled to require smoke, the red-merge path is BLOCKED and the implementer must escalate per FR-3 within the same PR (apply Lever 2 as a follow-up commit) or split into two PRs.
- **Release gate:**
  - All non-smoke `pr.yml` jobs pass; smoke job RAN (success or failure, not cancelled/skipped) — per AC-1.
  - `SOLR_HEAP_SIZE` correctly resolves to `256m` under the smoke job (AC-5; verifiable statically via `docker compose config` + YAML parse — no need to wait for CI).
  - Smoke-logs artifact contains `relyloop-solr-1` + `relyloop-opensearch-1` sections **only on the smoke-red path** (AC-2). On the smoke-green path, AC-4's static workflow assertion covers FR-1 correctness (no scratch failure is forced — that would be noisy and could false-fail per cycle-2 finding #5).
  - Runbook file + CLAUDE.md row added (AC-4).
  - If smoke is red on the merge run: follow-up artifact (idea-stage file at minimum, full spec if scope warrants) for Lever 2/3 **filed AND linked from PR body BEFORE merge** (FR-3 forcing function — mechanical, not time-based).

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (diagnostics fold-in) | AC-2 | Story 1.1 (YAML edit: services + `docker compose ps`) | smoke-logs artifact inspection on a post-FR-1 run | — |
| FR-2 (Lever 1: heap cap + COMPOSE_PROJECT_NAME) | AC-3, AC-4 | Story 1.2 (env-block edit) | `docker compose config --format json` structural check; YAML parse | — |
| FR-3 (smoke ran; triage; follow-up forcing function) | AC-1, AC-2 | Story 1.2 + 1.3 (verify run + branch-protection re-check) | full `pr.yml` matrix outcome triage | — |
| FR-4 (runbook + CLAUDE.md) | AC-5 | Story 2.1 (runbook), Story 2.2 (CLAUDE.md row) | grep + `test -f` verification | `docs/03_runbooks/smoke-solr-stability.md`, `CLAUDE.md` |

## 18) Definition of feature done

- [ ] AC-1 — smoke job RAN on the merge PR + all other required `pr.yml` jobs (full list in AC-1) green.
- [ ] AC-2 — failure-diagnostics artifact verifiably contains `relyloop-solr-1` + `relyloop-opensearch-1` log lines (required only in the smoke-red case; in smoke-green case, AC-4's static YAML check covers FR-1 correctness).
- [ ] AC-3 — `docker compose config` renders `SOLR_HEAP: 512m` (Compose default unchanged); `git diff main -- docker-compose.yml` is empty.
- [ ] AC-4 — `.github/workflows/pr.yml` smoke-test step has `SOLR_HEAP_SIZE: "256m"` AND `COMPOSE_PROJECT_NAME: "relyloop"` env (static YAML parse); `SOLR_HEAP_SIZE=256m docker compose config --format json | jq .services.solr.environment.SOLR_HEAP` returns `"256m"`.
- [ ] AC-5 — runbook file `docs/03_runbooks/smoke-solr-stability.md` exists; CLAUDE.md "Key Runbooks" table links to it.
- [ ] No open questions remain in §19.
- [ ] If AC-1's outcome is "smoke red," a follow-up artifact for Lever 2 (or Lever 3) — at minimum an idea-stage `idea.md` in its own planned-features folder — **is filed AND linked from this PR's body BEFORE merge** — this is a mechanical forcing function (the PR can't merge without the link in the body) rather than a time-based "within 48 hours" promise. Artifact depth is a judgement call: a one-line lever-YAML follow-up rates an idea file; a multi-file scope (e.g., Lever 3 smoke-tolerance audit) rates a full spec.
- [ ] Branch-protection state on `main` re-verified before merge in the smoke-red case (per §16 branch-protection caveat).
- [ ] `state.md` updated: **only if smoke green**, strike the "Smoke half still open (Phase 2)" item entirely; **if smoke red**, update the same item to record the captured evidence + the follow-up spec path/link.

## 19) Open questions and decision log

### Open questions

_None at spec time._ The lever-choice question (the idea's central open fork) is locked below.

### Decision log

- **2026-06-01 — D-1: Lever 1 (heap-cap) is the locked default for this spec.** Rationale: it is the cheapest, lowest-risk lever; it has the strongest precedent (the backend job's `ES_JAVA_OPTS: -Xms256m -Xmx256m`); and the worst case if it doesn't fix the crash is a no-change-in-redness smoke job that now produces Solr logs in the failure-diagnostics artifact — feeding the next iteration. Lever 2 (`start_period` bump from 30s to 60s/90s) and Lever 3 (smoke-tolerance of Solr-down) are documented as escalation paths in the runbook (FR-4) and explicitly out of scope here.
- **2026-06-01 — D-7: Lever 0 added in-PR (filesystem permissions fix) after PR #383's first CI run.** Rationale: the diagnostics fold-in (FR-1) shipped on PR #383's first CI run and immediately surfaced a failure mode the locked lever cascade never anticipated — Solr's container user (UID 8983) couldn't write to `./data/solr` (root-owned on the GHA runner). Container exited (1) in 542ms with `Cannot write to /var/solr as 8983:8983`; `oom=false` ruled out the entire memory-pressure cascade. Per the user's "implement-over-defer" directive, the fix landed inline on the same PR (`mkdir -p ./data/solr && sudo chown 8983:8983 ./data/solr` before `make up`) rather than as a follow-up idea — single-line edit, zero ambiguity, and deferring would have meant another full PR cycle to land a fix that took 30 seconds to write. Lever 1 (heap-cap) stays in place as defense against future JVM heap pressure, but Lever 0 is what actually fixed PR #383. The runbook §3 now leads with Lever 0 as the proven baseline, with Lever 1 as the secondary defense-in-depth measure.
- **2026-06-01 — D-2: Single-PR delivery, not the two-PR sequence the idea proposed.** Rationale: the idea's two-PR sequence was a hedge against bundling a "we don't know what the fix is" lever PR with a clean diagnostics PR. Locking Lever 1 by D-1 collapses that risk — Lever 1 is the cleanest, lowest-risk fix, the diagnostics fold-in is one line, and a single PR is faster to land. If Lever 1 doesn't work, the next PR is just as cheap to write because the diagnostics are now in place.
- **2026-06-01 — D-3: Fold `opensearch` in alongside `solr` in the failure-diagnostics list.** Rationale: OpenSearch is also a smoke-job dependency (Compose line 235) and is also missing from the log collect line at `pr.yml:719`. Folding both in is one line of diff and removes a pre-existing diagnostic gap. The idea explicitly named this as a worthwhile fold-in.
- **2026-06-01 — D-4: Escalation path documented in the runbook, NOT as a `phase2_idea.md`.** Rationale: Levers 2 and 3 have documented triggers and known starting-point edits (Lever 2 = bump `start_period` from 30s to 60s/90s; Lever 3 = make smoke job tolerant of Solr-down via tutorial-path test adjustment). However, NEITHER lever is genuinely "one line" — Lever 2 changes the Compose healthcheck which affects local dev, so it requires a CI-only env override slot (similar to `SOLR_HEAP_SIZE`) plus a docker-compose.yml edit; Lever 3 requires auditing the tutorial-path smoke pytest's implicit assumptions about Solr availability, which is multi-file. The runbook documents the **starting point** for each lever; the **scope** is determined when the lever is actually applied, driven by the captured log evidence. Either lever, if triggered by FR-3, gets its own spec (one file, ~50-100 lines per the pattern of this one) — not a `phase2_idea.md` pre-written today against unknown evidence.
- **2026-06-01 — D-6: Smoke job is allowed to merge red on this PR.** Rationale: GPT-5.5 caught (cycle 1 finding #10) that the single-PR delivery (D-2) plus a "smoke must be green" DoD created a deadlock — if Lever 1 doesn't fix the crash, the diagnostics half (FR-1) cannot land either, and the next iteration is still blind. Resolution: AC-1 is relaxed to "smoke job RAN" (success OR failure, not cancelled/skipped); if smoke is red, AC-2 becomes the gating verification (the artifact must contain Solr+OpenSearch logs). This is safe because `main` no longer enforces heavy-CI required-status-checks (per `state.md`, the operator removed that rule 2026-05-31), so the PR is mergeable on the fast lane in the Lever-1-fails case. FR-3's follow-up clause (file a follow-up spec within 48 hours) is the forcing function that ensures the lever-half work doesn't get lost.
- **2026-06-01 — D-5: `docker-compose.yml` is NOT touched.** Rationale: the heap override slot already exists (`${SOLR_HEAP_SIZE:-512m}`). Changing the 512m default to anything else would silently affect every operator's local laptop, which is the wrong scope of fix. The env var goes in the GHA workflow only.
