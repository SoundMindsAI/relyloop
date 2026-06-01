# Implementation Plan — `infra_solr_smoke_stability`

**Date:** 2026-06-01
**Status:** Draft
**Primary spec:** [`feature_spec.md`](./feature_spec.md)
**Policy source(s):** [CLAUDE.md](../../../../../CLAUDE.md) (Absolute Rules + Common Pitfalls), [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](../../../../03_runbooks/demo-reseed-engine-tolerance.md) (Phase 1 precedent — companion runbook to the one this work creates)

---

## 0) Planning principles

- This is an infra/CI plan. Most template sections (backend domain/service/repo, frontend, migration, API contracts, audit events) are N/A — the deliverable is GHA workflow YAML + a new runbook + a CLAUDE.md edit.
- Two epics: **Epic 1** (workflow changes, sequential within one PR), **Epic 2** (documentation).
- Phase 1 (the spec's only phase) covers FR-1, FR-2, FR-3, FR-4. No deferred phase — Levers 2/3 escalate into their own spec when evidence triggers them (D-4).
- **Soft sequencing recommendation** (per cycle-2 plan finding #1; NOT a hard gate): Epic 1 → Epic 2. The runbook's lever cascade is generic/forward-looking (it documents Levers 1/2/3 + memory-pressure escalation in the abstract, NOT this PR's specific outcome), so Epic 2 can run before Story 1.3 watches CI. But running Epic 2 second has a small benefit: if smoke goes red, the Story 1.3 evidence can sharpen wording. Either order is fine. Story 2.3 finalization re-verifies AC-1 on the FINAL HEAD SHA regardless, so the merge-target run is always captured.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (diagnostics fold-in: `solr` + `opensearch` + `docker inspect` exit-state) | Epic 1 / Story 1.1 | One-line YAML edit + the `docker inspect` adjunct line. |
| FR-2 (Lever 1 heap-cap + `COMPOSE_PROJECT_NAME` pin) | Epic 1 / Story 1.2 | `SOLR_HEAP_SIZE` is step-level on "Bring up the stack"; `COMPOSE_PROJECT_NAME` is JOB-level so it persists to the later failure-diagnostics step (per cycle-3 finding #1). |
| FR-3 (smoke ran; triage; before-merge forcing function if red) | Epic 1 / Story 1.3 | Verification + outcome triage + branch-protection re-check + (if smoke red) file the follow-up spec stub AND link it from the PR body before merge. |
| FR-4 (new runbook + CLAUDE.md row) | Epic 2 / Stories 2.1 + 2.2 | Story 2.1 = new `smoke-solr-stability.md`; Story 2.2 = CLAUDE.md "Key Runbooks" row. |

**Phase coverage:** spec defines a single phase; this plan covers all of it. No `phase2_idea.md` required (D-4).

## 2) Delivery structure

**Format:** Epic → Story → Tasks → DoD. The spec is infra-shaped so the stories are smaller than a typical product story; that's intentional — each story is its own small commit on a single feature branch, all merging in one PR.

### Conventions (project-specific)

- **Single feature branch + single PR.** Branch: `feature/infra-solr-smoke-stability`. Each story = one commit (or one logical group).
- **Conventional Commits + DCO.** Every commit message follows the project regex (`infra(...)` for workflow edits, `docs(...)` for runbook/CLAUDE.md). Every commit signed with `git commit -s`.
- **No skip-hooks.** Never `--no-verify` or `--no-gpg-sign`.
- **Pre-push gate before push.** Run `make fmt && make lint && make typecheck && make test-unit && make pre-commit` per CLAUDE.md (this project's standard set; for infra-only PRs, lint + the pre-commit hooks cover the YAML and markdown surface).
- **Static workflow validation.** For YAML edits to `.github/workflows/pr.yml`, parse with Python's `yaml.safe_load` and assert the structural properties per AC-4 before pushing — don't rely on GHA's implicit load to catch typos.

### AI Agent Execution Protocol

0. **Load context first.** Read `architecture.md`, `state.md`, and `feature_spec.md` §19 decision log before starting Story 1.1.
1. **Read scope** for the story being executed.
2. **Edit the workflow / compose / runbook file.**
3. **Run the static validation** specific to that story (YAML parse, `docker compose config`, `test -f` on the new runbook file).
4. **Commit** with `-s`.
5. After all Epic 1 stories: push, open PR, watch CI.
6. After CI runs: execute Story 1.3's outcome triage.
7. After Epic 1 verified: execute Epic 2 (runbook + CLAUDE.md row).
8. After all 5 stories: update `state.md` per §4.0; finalize.

---

## Epic 1 — Workflow + Compose changes

**Goal:** Land the diagnostics half (FR-1) and the optimistic-lever half (FR-2), then triage the resulting smoke-job outcome (FR-3) and either merge clean (smoke green) or merge with a pre-filed follow-up spec linked from the PR body (smoke red, per D-6).

### Story 1.1 — Failure-diagnostics fold-in (FR-1)

**Outcome:** The smoke-test job's "Collect docker compose logs on failure" step captures `solr` + `opensearch` (in addition to the existing api/worker/postgres/redis/elasticsearch/ui), AND appends a `docker inspect` adjunct line that captures per-container `OOMKilled` flags + exit codes. The step remains best-effort (`|| true`).

**New files**

| File | Purpose |
|---|---|
| _(none)_ | This story modifies an existing workflow only. |

**Modified files**

| File | Change |
|---|---|
| `.github/workflows/pr.yml` (smoke-test job, around lines 716-728) | (a) Extend the `docker compose logs` service list from `api worker postgres redis elasticsearch ui` to `api worker postgres redis elasticsearch opensearch solr ui`. (b) Append a second line: `docker compose ps -aq \| xargs -r docker inspect --format '{{.Name}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} error={{.State.Error}}' >> smoke-logs.txt 2>&1 \|\| true`. Both lines must keep `\|\| true` (best-effort). |

**Endpoints / Key interfaces / Pydantic schemas**

N/A — workflow YAML only.

**Tasks**

1. Read [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) lines 716-728 to confirm the current "Collect docker compose logs on failure" step shape.
2. Edit the `run:` block to:
   ```yaml
   run: |
     docker compose logs --no-color api worker postgres redis elasticsearch opensearch solr ui > smoke-logs.txt 2>&1 || true
     docker compose ps -aq | xargs -r docker inspect --format '{{.Name}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} error={{.State.Error}} health={{with .State.Health}}{{.Status}}{{end}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}' >> smoke-logs.txt 2>&1 || true
     curl -s http://127.0.0.1:8000/healthz >> smoke-logs.txt 2>&1 || true
   ```
   (Preserve the existing `curl /healthz` tail line. The extended `--format` includes `health` + `started` + `finished` fields per cycle-3 plan finding #4, so the Lever-2 runbook trigger ("Solr booted but past healthcheck tolerance") can be diagnosed from artifact evidence alone — the prior template only had exit/oom/error.)
3. Run YAML parse validation:
   ```bash
   python3 -c "import yaml; wf=yaml.safe_load(open('.github/workflows/pr.yml')); steps=wf['jobs']['smoke-test']['steps']; step=next(s for s in steps if s.get('name')=='Collect docker compose logs on failure'); assert 'opensearch solr ui' in step['run'], step['run']; assert 'docker inspect' in step['run'], step['run']"
   ```
4. Commit: `infra(smoke-ci): capture solr + opensearch logs + docker inspect on smoke failure`.

**Definition of Done (DoD)**

- [ ] `.github/workflows/pr.yml` smoke-test job's "Collect docker compose logs on failure" step lists `solr` and `opensearch` in the logs command.
- [ ] The same step appends `docker inspect` output (capturing `OOMKilled` + exit codes) to `smoke-logs.txt`, with `|| true`.
- [ ] YAML parse validation script (Task 3) succeeds.
- [ ] All three lines retain `|| true` — best-effort diagnostics (cycle-3 finding #2 wording: "intentionally best-effort").
- [ ] Commit message follows Conventional Commits + DCO.

---

### Story 1.2 — Lever 1 heap-cap + `COMPOSE_PROJECT_NAME` pin (FR-2)

**Outcome:** The smoke-test job's "Bring up the stack" step sets `SOLR_HEAP_SIZE: "256m"` (step-level) so Solr boots with a 256m heap on the GHA runner. The smoke-test job's job-level `env:` sets `COMPOSE_PROJECT_NAME: "relyloop"` so the container-name prefix is deterministic (`relyloop-solr-1`, `relyloop-opensearch-1`) for both the `make up` step AND the later failure-diagnostics step (GHA step-level env does NOT persist to later steps — per cycle-3 finding #1, this MUST be job-level).

**New files**

| File | Purpose |
|---|---|
| _(none)_ | This story modifies an existing workflow only. |

**Modified files**

| File | Change |
|---|---|
| `.github/workflows/pr.yml` (smoke-test job — line 487 `smoke-test:` declaration block) | (a) Add a job-level `env:` block immediately after `permissions:` (line 502-503) containing `COMPOSE_PROJECT_NAME: "relyloop"`. (b) Add `SOLR_HEAP_SIZE: "256m"` to the "Bring up the stack" step's existing env block (line 621-628), alongside `RELYLOOP_GIT_SHA`, `RELYLOOP_SKIP_BUILD`, and `RELYLOOP_SKIP_AUTO_SEED`. |

**Endpoints / Key interfaces / Pydantic schemas**

N/A.

**Tasks**

1. Read `.github/workflows/pr.yml` lines 487-510 (job header + `permissions:` block) and lines 620-629 ("Bring up the stack" step) to confirm insertion points. **Critical sanity check (per cycle-1 finding #12):** verify NO job-level `env:` block already exists between `permissions:` and `steps:` on the `smoke-test:` job — duplicate YAML keys at the same level produce undefined merge behavior. If a job-level `env:` block has been added since spec time, APPEND `COMPOSE_PROJECT_NAME: "relyloop"` to it rather than creating a second block. Check with: `python3 -c "import yaml; wf=yaml.safe_load(open('.github/workflows/pr.yml')); print('existing job-env keys:', list((wf['jobs']['smoke-test'].get('env') or {}).keys()))"`.
2. Insert a job-level `env:` block after `permissions:` (typical GHA layout: `permissions:` then `env:` then `steps:`) — OR extend the existing one per the sanity check above:
   ```yaml
     smoke-test:
       name: smoke (operator-path tutorial flow)
       if: ${{ vars.SKIP_HEAVY_CI != 'true' }}
       runs-on: ubuntu-24.04
       timeout-minutes: 15
       needs: [docker, docker-ui]
       permissions:
         contents: read
       env:
         # Pin Compose project name so container-name prefixes (relyloop-solr-1,
         # relyloop-opensearch-1) are deterministic for diagnostics grep across
         # both `make up` and the later failure-diagnostics step (GHA step-level
         # env does NOT persist to later steps).
         # See infra_solr_smoke_stability spec FR-2 + AC-2.
         COMPOSE_PROJECT_NAME: "relyloop"
       steps:
         ...
   ```
3. Edit the "Bring up the stack" step's `env:` block to add `SOLR_HEAP_SIZE: "256m"`:
   ```yaml
   - name: Bring up the stack
     env:
       RELYLOOP_GIT_SHA: ${{ github.sha }}
       RELYLOOP_SKIP_BUILD: "1"
       RELYLOOP_SKIP_AUTO_SEED: "1"
       # Cap Solr heap to reduce JVM memory pressure on the GHA runner.
       # Compose's solr service reads ${SOLR_HEAP_SIZE:-512m}; the 512m default
       # is correct for local dev, the 256m cap is CI-only.
       # See infra_solr_smoke_stability spec FR-2 + decision log D-1, D-5.
       SOLR_HEAP_SIZE: "256m"
     run: make up
   ```
4. Run AC-4 validation:
   ```bash
   # Step-level SOLR_HEAP_SIZE:
   python3 -c "import yaml; wf=yaml.safe_load(open('.github/workflows/pr.yml')); steps=wf['jobs']['smoke-test']['steps']; step=next(s for s in steps if (s.get('run') or '').strip()=='make up'); assert (step.get('env') or {}).get('SOLR_HEAP_SIZE')=='256m', step.get('env')"
   # Job-level COMPOSE_PROJECT_NAME:
   python3 -c "import yaml; wf=yaml.safe_load(open('.github/workflows/pr.yml')); job=wf['jobs']['smoke-test']; assert (job.get('env') or {}).get('COMPOSE_PROJECT_NAME')=='relyloop', job.get('env')"
   # Structural Compose render:
   SOLR_HEAP_SIZE=256m docker compose config --format json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['services']['solr']['environment']['SOLR_HEAP']=='256m'; print('ok')"
   ```
5. Verify Story 1.1's edits + Story 1.2's edits don't conflict — run AC-3 to confirm local `make up` still resolves Solr heap to 512m (no env set):
   ```bash
   docker compose config --format json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['services']['solr']['environment']['SOLR_HEAP']=='512m', d['services']['solr']['environment']; print('local default unchanged')"
   git diff main -- docker-compose.yml  # must be empty
   ```
6. Commit: `infra(smoke-ci): cap solr heap to 256m + pin COMPOSE_PROJECT_NAME for diagnostics`.

**Definition of Done (DoD)**

- [ ] `.github/workflows/pr.yml` smoke-test job has a job-level `env:` block with `COMPOSE_PROJECT_NAME: "relyloop"`.
- [ ] The "Bring up the stack" step's step-level `env:` block contains `SOLR_HEAP_SIZE: "256m"` alongside the existing entries.
- [ ] AC-4 YAML parse checks (both step-level + job-level) succeed.
- [ ] AC-4 structural Compose check succeeds (Solr renders as `SOLR_HEAP: 256m` with the env var set).
- [ ] AC-3 local-default check succeeds (Solr renders as `SOLR_HEAP: 512m` without the env var set; `git diff main -- docker-compose.yml` empty).
- [ ] Both env entries carry inline comments explaining the rationale + linking to the spec.
- [ ] Commit message follows Conventional Commits + DCO.

---

### Story 1.3 — Push, watch CI, triage outcome, file follow-up if red (FR-3)

**Outcome:** The PR is opened with both Story 1.1 + Story 1.2 commits. CI runs to a definitive outcome on `pr.yml`. Outcome triage:
- **Smoke green** → AC-1 / AC-3 / AC-4 all satisfied; proceed to Epic 2.
- **Smoke red** → AC-2 verified from the artifact (Solr + OpenSearch sections present, `docker inspect` exit-state present); branch protection re-verified; follow-up spec stub for Lever 2 (or Lever 3, based on captured evidence) filed AND linked from this PR's body; THEN proceed to Epic 2.

**New files**

| File | Purpose |
|---|---|
| _(conditional)_ `docs/00_overview/planned_features/02_mvp2/infra_solr_smoke_lever2/idea.md` (or `..._lever3/`, depending on evidence) | Created ONLY if smoke is red. Tiny idea-stage file (10-30 lines) scoped to the next lever per the FR-4 runbook escalation triggers. Linked from this PR's body. |

**Modified files**

| File | Change |
|---|---|
| _(conditional)_ This PR's body on GitHub | Add a "Follow-up" section linking the lever-2/3 idea file path. ONLY in the smoke-red case. |

**Tasks**

1. Push the branch: `git push -u origin feature/infra-solr-smoke-stability`.
2. Open the PR with `gh pr create`. PR title: `infra(smoke-ci): cap Solr heap + capture solr/opensearch logs on smoke failure`. PR body lists Story 1.1 + 1.2 + Epic 2 outcomes and explicitly notes the D-6 red-merge-allowed posture.
3. Identify the PR run constrained to `pr.yml` AND the current branch HEAD SHA (per cycle-1 finding #9, the unconstrained `gh run list --branch ...` can return a stale or wrong-workflow run):
   ```bash
   HEAD_SHA=$(git rev-parse HEAD)
   RUN_ID=$(gh run list --workflow pr.yml --branch feature/infra-solr-smoke-stability --limit 5 --json databaseId,headSha -q ".[] | select(.headSha == \"$HEAD_SHA\") | .databaseId" | head -1)
   echo "RUN_ID=$RUN_ID for HEAD_SHA=$HEAD_SHA"
   gh run watch "$RUN_ID"
   ```
4. Once CI completes, derive the job-by-job outcome:
   ```bash
   gh run view "$RUN_ID" --json jobs -q '.jobs[] | "\(.conclusion)\t\(.name)"'
   ```
5. **AC-1 check — mechanical (per cycle-2 plan finding #4):** assert every non-smoke job is `success` AND smoke is `success` or `failure` (NOT `cancelled`/`skipped`). Exits non-zero on failure:
   ```bash
   python3 - <<'PY' "$RUN_ID"
   import json, subprocess, sys
   run_id = sys.argv[1]
   wf = __import__('yaml').safe_load(open('.github/workflows/pr.yml'))
   expected_jobs = {j.get('name', jid) for jid, j in wf['jobs'].items()}
   smoke_name = 'smoke (operator-path tutorial flow)'
   gh = subprocess.run(['gh', 'run', 'view', run_id, '--json', 'jobs'], capture_output=True, text=True, check=True)
   jobs = json.loads(gh.stdout)['jobs']
   actual = {j['name']: j['conclusion'] for j in jobs}
   bad = []
   for name in expected_jobs:
       if name not in actual:
           bad.append(f'MISSING: {name}')
           continue
       c = actual[name]
       if name == smoke_name:
           if c not in ('success', 'failure'):
               bad.append(f'SMOKE_UNTRIAGED: {c}')
       elif c != 'success':
           bad.append(f'NON_SMOKE_NOT_SUCCESS: {name} = {c}')
   if bad:
       print('AC-1 FAILED:', '; '.join(bad), file=sys.stderr); sys.exit(1)
   print(f'AC-1 ok (smoke={actual[smoke_name]})')
   PY
   ```
6. **Branch on smoke outcome:**

   **(a) Smoke green path:**
   - AC-1 + AC-3 + AC-4 are all green. Proceed to Epic 2.
   - No follow-up artifact needed. The Outcome (B) half delivered.

   **(b) Smoke red path:**
   - Verify the failure-diagnostics artifact name matches the upload step (per cycle-1 finding #10):
     ```bash
     python3 -c "import yaml; wf=yaml.safe_load(open('.github/workflows/pr.yml')); steps=wf['jobs']['smoke-test']['steps']; step=next(s for s in steps if s.get('name')=='Upload failure diagnostics'); print('artifact name:', step['with']['name'])"
     # Expected: smoke-logs
     ```
   - Download the failure-diagnostics artifact to a known dir (robust against `gh run download`'s extract-to-subdir behavior):
     ```bash
     rm -rf /tmp/smoke-artifacts && mkdir -p /tmp/smoke-artifacts
     gh run download "$RUN_ID" --name smoke-logs --dir /tmp/smoke-artifacts
     LOGS=$(find /tmp/smoke-artifacts -name smoke-logs.txt -print -quit)
     test -n "$LOGS" || (echo "smoke-logs.txt not in artifact" && exit 1)
     ```
   - Run AC-2 verification on the downloaded `$LOGS` — mechanical assertion (per cycle-2 plan findings #5):
     ```bash
     grep -Eq '^relyloop-solr-1[[:space:]]+\|' "$LOGS" || { echo "AC-2 FAILED: no relyloop-solr-1 log lines" >&2; exit 1; }
     grep -Eq '^relyloop-opensearch-1[[:space:]]+\|' "$LOGS" || { echo "AC-2 FAILED: no relyloop-opensearch-1 log lines" >&2; exit 1; }
     grep -Eq 'relyloop-solr-1 exit=[0-9-]+ oom=(true|false) error=' "$LOGS" || { echo "FAILED: missing solr docker inspect exit-state line (Story 1.1 adjunct)" >&2; exit 1; }
     echo "AC-2 ok"
     ```
     (Note: the inspect line emits `oom=true` / `oom=false` per the `{{.State.OOMKilled}}` template in Story 1.1 — NOT `OOMKilled=true`. Runbook prose in Story 2.1 uses the same `oom=...` wording for consistency, per cycle-1 finding #11.)
   - **Re-verify branch protection — mechanical (per cycle-2 plan finding #6 + cycle-3 plan finding #6):** explicitly inspect the HTTP status to distinguish 404 (no protection — pass) from 403 (auth/permission failure — escalate, do NOT proceed); parse the JSON and fail if smoke is required.
     ```bash
     python3 - <<'PY'
     import json, subprocess, sys
     # Use `gh api --include` to get the HTTP status line, not just the body.
     r = subprocess.run(['gh', 'api', '-i', 'repos/SoundMindsAI/relyloop/branches/main/protection'], capture_output=True, text=True)
     # `-i` puts status on stdout (header), body after; on non-2xx gh still exits non-zero.
     status_line = r.stdout.splitlines()[0] if r.stdout else ''
     if '404' in status_line:
         print('branch-protection: HTTP 404 (no protection) — red-merge path open')
         sys.exit(0)
     if '403' in status_line or '401' in status_line:
         print(f'branch-protection: AUTH FAILURE ({status_line}) — cannot verify; ESCALATE (do not assume no protection)', file=sys.stderr)
         sys.exit(1)
     if r.returncode != 0 and not r.stdout:
         print(f'branch-protection: unexpected gh failure: {r.stderr}', file=sys.stderr); sys.exit(1)
     # Parse the body (after the blank line that separates headers from body)
     body = r.stdout.split('\n\n', 1)[1] if '\n\n' in r.stdout else r.stdout
     d = json.loads(body)
     required = (d.get('required_status_checks') or {}).get('contexts', []) + [c['context'] for c in (d.get('required_status_checks') or {}).get('checks', [])]
     if any('smoke' in c.lower() for c in required):
         print(f'branch-protection: smoke IS required ({required}) — RED-MERGE PATH CLOSED. Apply Lever 2 as follow-up commit BEFORE merge.', file=sys.stderr)
         sys.exit(1)
     print(f'branch-protection: smoke NOT in required checks ({required or "[]"}) — red-merge path open')
     PY
     ```
     If the script exits non-zero, STOP. Auth-failure case: re-authenticate (`gh auth status` / `gh auth refresh`); only proceed once status is unambiguous. Smoke-required case: apply Lever 2 as a follow-up commit on this same branch BEFORE merge, OR split into two PRs.
   - **Read the captured Solr logs** to determine the failure mode (per FR-4 runbook trigger mapping in Story 2.1 §3):
     - `oom=true` in the inspect line OR a JVM heap/metaspace/native-memory OOM trace in `^relyloop-solr-1 |` lines → **memory-pressure escalation** (revisit heap sizing across ES + OpenSearch + Solr together — the §13 Known Risk path; NOT just reapplying the Solr cap).
     - Solr listening successfully (boot succeeded per `^relyloop-solr-1 |` log lines) but the artifact's inspect line shows `health=unhealthy` or `health=starting` past the effective healthcheck tolerance (`start_period: 30s` + `interval: 10s` × `retries: 6` with `timeout: 5s` per docker-compose.yml — up to ~95s; do NOT use a flat 30s cutoff per cycle-2 plan finding #8 + cycle-3 plan finding #4) → **Lever 2** (healthcheck-timing escalation via a CI-only override mechanism — details locked in the Lever 2 follow-up spec; per cycle-1 finding #7, do NOT presume the exact YAML shape now).
     - Solr unavailable AND the tutorial-path smoke test genuinely doesn't depend on Solr (requires a full smoke-path audit, NOT just a one-file grep, per cycle-1 finding #8) → **Lever 3** (smoke-tolerance — multi-file scope, full spec).
   - **File the follow-up artifact** at `docs/00_overview/planned_features/02_mvp2/infra_solr_smoke_<lever-name>/idea.md` (the slug picks per the chosen escalation: `_memory_pressure_revisit`, `_start_period_lever2`, or `_tolerance_lever3`). Per the spec's relaxed FR-3 / DoD wording: an **idea-stage file** is the minimum bar (acceptable for one-line lever YAML edits); a full spec is warranted if the scope is multi-file (e.g., Lever 3 tolerance audit). The idea file should be ~30-50 lines: Origin (this PR run URL + captured Solr exit reason + `oom=` value), Problem (one paragraph), Proposed lever (one of the three above), Why deferred (waiting on the data we just captured = now captured), Relationship to this work (cite this PR).
   - **Link the new artifact from this PR's body** by editing the PR via `gh pr edit <pr> --body-file <new-body.md>`. The link is the mechanical forcing function — the PR body MUST contain a "Follow-up" section pointing at the new artifact's path BEFORE merge. **After editing, verify mechanically (per cycle-2 plan finding #7):**
     ```bash
     gh pr view <pr> --json body -q .body | grep -F "docs/00_overview/planned_features/02_mvp2/infra_solr_smoke_" || { echo "PR body missing follow-up link" >&2; exit 1; }
     ```

7. Commit the follow-up artifact (if smoke red) on this same feature branch — that keeps the PR + follow-up reference in one place rather than across branches. Commit message: `docs(planned-features): capture infra_solr_smoke_<lever-name> follow-up`.

8. **Re-trigger CI** (since steps 6-7 may have added a commit). Re-derive `RUN_ID` per step 3 with the new `HEAD_SHA`, then re-watch. The merge-target run is the LATEST `pr.yml` run on the final HEAD SHA, not the run from step 3 (per cycle-1 finding #2).

**Definition of Done (DoD)**

- [ ] PR is open on GitHub.
- [ ] CI completed; smoke job's outcome is one of `success` or `failure` (NOT `cancelled` / `skipped`).
- [ ] All non-smoke `pr.yml` jobs are `success` per AC-1.
- [ ] **If smoke green:** Story 1.3 is complete; no follow-up needed.
- [ ] **If smoke red:** AC-2 grep on the failure-diagnostics artifact succeeds AND branch protection re-check confirms the smoke job is NOT a required status check AND a follow-up idea file exists for the next lever AND the PR body links it under a "Follow-up" section.

---

## Epic 2 — Documentation

**Goal:** Write the runbook so future maintainers have an evidence-driven escalation path, and surface it in CLAUDE.md so it's reachable from the project's canonical conventions doc. Runs AFTER Epic 1 verification (Story 1.3 outcome triage) so the runbook documents what was observed empirically, not what was predicted.

### Story 2.1 — Write `smoke-solr-stability.md` runbook (FR-4)

**Outcome:** A new runbook file exists at `docs/03_runbooks/smoke-solr-stability.md` documenting the heap-cap rationale, the evidence-mapped lever cascade (Lever 1 → Lever 2 → Lever 3 → sibling-JVM-cap escalation), and the diagnostic-first workflow. Modeled structurally on the existing [`demo-reseed-engine-tolerance.md`](../../../../03_runbooks/demo-reseed-engine-tolerance.md) (the Phase 1 sibling runbook) for visual consistency.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/smoke-solr-stability.md` | Runbook documenting (a) heap-cap rationale + GHA-only scope; (b) evidence-mapped lever cascade with explicit triggers (not symptom-mapped); (c) diagnostic-first workflow — "read smoke-logs `relyloop-solr-1` section + `docker inspect` exit state BEFORE picking a lever." Includes a "What to do if smoke goes red after Lever 1" decision tree. Carries the SPDX header pattern used by all RelyLoop runbooks. |

**Modified files**

| File | Change |
|---|---|
| _(none)_ | Story 2.2 handles CLAUDE.md separately. |

**Endpoints / Key interfaces / Pydantic schemas**

N/A.

**Tasks**

1. Read [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](../../../../03_runbooks/demo-reseed-engine-tolerance.md) lines 1-30 for the SPDX header + Owner/Audience pattern.
2. Create the new runbook file with sections:
   - **Header:** SPDX-FileCopyrightText + SPDX-License-Identifier (per the REUSE convention; the freshness gate passes 1655/1655 currently).
   - **Owner:** `infra_solr_smoke_stability` (this folder, once finalized: `implemented_features/2026_06_01_infra_solr_smoke_stability/`).
   - **Audience:** maintainers diagnosing a red `smoke` job on a PR.
   - **§1: Why Solr heap is capped at 256m in CI.** Reference the ES `ES_JAVA_OPTS` precedent at [`pr.yml:287`](../../../../../.github/workflows/pr.yml#L287); call out the hypothesis nature (spec D-1 + §13 Known Risk); the GHA-runner-only scope (Compose default of 512m stays for local dev).
   - **§2: When smoke goes red — the diagnostic workflow.** Step-by-step: (a) `gh run download <run> --name smoke-logs`; (b) `grep -E '^relyloop-solr-1' smoke-logs.txt` to read Solr container output; (c) `grep 'relyloop-solr-1 exit=' smoke-logs.txt` to read the `docker inspect` exit-state line (FR-1 adjunct); (d) classify the failure per §3 below.
   - **§3: The lever cascade (evidence-mapped, not symptom-mapped).** Lever 1 is the CURRENT baseline (already shipped by the PR this runbook ships with); Levers 2 / 3 / memory-pressure are FUTURE escalations triggered if the smoke job goes red AFTER Lever 1 is in place. Each escalation entry: trigger evidence + the lever + the rationale + the file edit shape.
     - **Lever 1 (CURRENT, this PR):** Solr heap capped to 256m via `SOLR_HEAP_SIZE: "256m"` step-env on the smoke job's "Bring up the stack" step. This is the baseline state. Do NOT re-apply.
     - **IF Lever 1 didn't fix the crash, escalate based on the captured evidence:**
       - **Memory-pressure escalation (heap, metaspace, native OOM, OR kernel `oom=true`):** the spec's §13 Known Risk path. The smoke Compose stack runs three JVM services (Solr + ES + OpenSearch) concurrently; the backend job's `ES_JAVA_OPTS` env applies to GHA service containers NOT to the smoke job's Compose stack, so ES + OpenSearch run at their Compose defaults today. Edit: cap ES + OpenSearch heap in the smoke Compose path too (via `ES_JAVA_OPTS` env override on smoke + Compose env-var slot for OpenSearch heap; details locked in the follow-up spec). Multi-file scope. This is the unified escalation for both Solr-internal OOM traces and kernel-side `oom=true` (per cycle-1 plan finding #6 — Lever 1 was previously listed separately for these; that's wrong because the lever is what changed, the failure mode is what triggers the next change).
       - **Lever 2 (healthcheck-timing escalation):** Trigger: Solr boots successfully (logs show "Started SolrJetty" or equivalent) but the container's effective healthcheck tolerance window (`start_period: 30s` + `interval: 10s` × `retries: 6` with `timeout: 5s` per [`docker-compose.yml:280-285`](../../../../../docker-compose.yml#L280-L285) — total tolerance up to ~95s, NOT a flat 30s window per cycle-2 plan finding #8) elapsed before the healthcheck went green. Read Solr log timestamps and compare to the healthcheck transitions in `docker inspect` to confirm — don't assume "boot > 30s = Lever 2." Edit: add a CI-only override mechanism for the Solr healthcheck timing, preserving the local-dev defaults. The exact YAML shape (env-var interpolation in healthcheck values vs. a docker-compose override file vs. a step-level `docker compose ... --wait-timeout` flag) is locked in the Lever-2 follow-up spec.
       - **Lever 3 (smoke-tolerance):** Trigger: Solr genuinely unavailable AND the smoke path genuinely doesn't depend on Solr. **Important:** Lever 3 selection requires a FULL smoke-path audit, not a single-file grep. The smoke path can depend on Solr transitively via `/healthz` (the api probes Solr as a subsystem), seed/migrate steps, fixtures, or backend service calls. The audit covers: `backend/tests/smoke/test_tutorial_path.py` + all seed scripts (`make seed-clusters`, `make seed-es`) + the api's `/healthz` Solr-probe behavior (currently treats a missing Solr as a `subsystems.solr` field, not a job failure — per spec §2 audit) + the tutorial walkthrough flow. Only if Solr is genuinely unreferenced across that surface is Lever 3 viable. Edit: change the smoke job's success criteria to tolerate `subsystems.solr: down` in `/healthz` AND adjust any tutorial-path assertions that touch Solr (per cycle-2 plan finding #9 — there is no dedicated "Solr healthcheck wait" step to drop; the dependency is via `/healthz` subsystem semantics + tutorial-path implicit assumptions). Multi-file scope, full spec.
   - **§4: Why each lever stays GHA-only.** Local dev (`make up`) runs without `SOLR_HEAP_SIZE`/`COMPOSE_PROJECT_NAME` so Compose defaults apply: Solr 512m heap, project name derived from working directory. Don't change `docker-compose.yml` defaults (per spec D-5).
3. Verify SPDX gate stays green: `uv run reuse lint` → 1655+/1655+.
4. Commit: `docs(runbooks): smoke-solr-stability — heap-cap rationale + evidence-mapped lever cascade`.

**Definition of Done (DoD)**

- [ ] `docs/03_runbooks/smoke-solr-stability.md` exists with the four sections (§1 rationale, §2 diagnostic workflow, §3 lever cascade with evidence-mapped triggers, §4 GHA-only scope).
- [ ] SPDX header present (matching the demo-reseed-engine-tolerance.md pattern).
- [ ] `uv run reuse lint` still reports `Congratulations! Your project is compliant`.
- [ ] All cited file references resolve (`test -f` passes for `.github/workflows/pr.yml`, the existing sibling runbook).
- [ ] Lever cascade in §3 uses **evidence-mapped triggers** (not symptom-mapped) per cycle-3 finding #3.
- [ ] Commit message follows Conventional Commits + DCO.

---

### Story 2.2 — Surface the runbook in CLAUDE.md (FR-4)



**Outcome:** CLAUDE.md "Key Runbooks" table contains a row linking to `docs/03_runbooks/smoke-solr-stability.md`, so a maintainer hitting a red smoke job can find the lever cascade from the project's canonical conventions doc.

**New files**

| File | Purpose |
|---|---|
| _(none)_ | This story modifies an existing file only. |

**Modified files**

| File | Change |
|---|---|
| [`CLAUDE.md`](../../../../../CLAUDE.md) "Key Runbooks" table | Add a row after the "Demo reseed engine tolerance" row (the structural sibling) linking to `docs/03_runbooks/smoke-solr-stability.md`. Row format: `\| Smoke job Solr stability — lever cascade (heap-cap / start_period / smoke-tolerance) for a red `smoke` CI job \| [`docs/03_runbooks/smoke-solr-stability.md`](docs/03_runbooks/smoke-solr-stability.md) (`infra_solr_smoke_stability`) \|`. |

**Tasks**

1. Open [`CLAUDE.md`](../../../../../CLAUDE.md), find the "Key Runbooks" table (search for `## Key Runbooks` or the "Demo reseed engine tolerance" row added by `infra_solr_ci_readiness` Phase 1).
2. Add the new row immediately after the "Demo reseed engine tolerance" row — these two are sibling runbooks (backend half + smoke half of the same Solr CI debt).
3. Run AC-5 verification:
   ```bash
   grep -q 'smoke-solr-stability.md' CLAUDE.md && test -f docs/03_runbooks/smoke-solr-stability.md && echo "AC-5 ok"
   ```
4. Commit: `docs(claude-md): link smoke-solr-stability runbook from Key Runbooks table`.

**Definition of Done (DoD)**

- [ ] `CLAUDE.md` "Key Runbooks" table contains a row matching the pattern in "Modified files" above.
- [ ] AC-5 verification command (Task 3) succeeds.
- [ ] Row placement is immediately after the "Demo reseed engine tolerance" row.
- [ ] Commit message follows Conventional Commits + DCO.

---

### Story 2.3a — Pre-merge final CI verification + cleanup of stale red→green follow-ups (cycle-1 plan findings #2 + #3; cycle-3 plan finding #1 sequencing fix; cycle-3 plan finding #2 red→green cleanup)

**Outcome:** The FINAL `pr.yml` run on the FINAL HEAD SHA (post-Epic-2 commits, post any smoke-red follow-up commit) is re-verified to satisfy AC-1 + (if final-smoke red) AC-2. If Story 1.3 created a follow-up artifact + PR-body link because Story 1.3's run was red, but the final run is green, the stale artifact is deleted and the PR body's "Follow-up" section is removed. Sequencing matters: state.md is NOT updated in this story (state.md updates need the post-merge squash SHA, so they happen in Story 2.3b as a separate post-merge PR per the project's established pattern — see PR #368 finalizing PR #367).

**New files / Modified files**

| File | Change |
|---|---|
| _(conditional)_ `docs/00_overview/planned_features/02_mvp2/infra_solr_smoke_<lever-name>/` | DELETED if Story 1.3 created it AND the final run is green (red→green divergence cleanup). |
| _(conditional)_ This PR's body on GitHub | "Follow-up" section REMOVED if Story 1.3 added it AND the final run is green. |

(Note: `state.md` updates do NOT live in this story — see Story 2.3b. Pre-merge state.md edits would force a chicken-and-egg loop because they change HEAD which invalidates the just-verified CI run, per cycle-3 plan finding #1. The squash-merge SHA is also unknown until merge, per cycle-3 plan finding #5.)

**Endpoints / Key interfaces / Pydantic schemas**

N/A.

**Tasks**

1. Determine the FINAL HEAD SHA (post-Epic-2 commits, post any smoke-red follow-up commit): `HEAD_SHA=$(git rev-parse HEAD)`.
2. Re-derive the merge-target `pr.yml` run for that SHA:
   ```bash
   FINAL_RUN_ID=$(gh run list --workflow pr.yml --branch feature/infra-solr-smoke-stability --limit 5 --json databaseId,headSha -q ".[] | select(.headSha == \"$HEAD_SHA\") | .databaseId" | head -1)
   gh run watch "$FINAL_RUN_ID"
   ```
3. Re-run the mechanical AC-1 assertion script from Story 1.3 step 5 against `$FINAL_RUN_ID`.
4. **Re-verify AC-2 on the FINAL run whenever smoke is red** (per cycle-2 plan finding #2 — not just when the outcome changed from Story 1.3). If the final smoke conclusion is `failure`:
   - Re-download the smoke-logs artifact from `$FINAL_RUN_ID`: `gh run download "$FINAL_RUN_ID" --name smoke-logs --dir /tmp/smoke-artifacts-final`.
   - Re-run the AC-2 mechanical assertions on the FINAL artifact (per Story 1.3 step 6(b)'s grep/exit-1 commands).
   - Re-read the FINAL artifact's Solr exit reason + `oom=` value.
   - **If the final evidence diverges from Story 1.3's evidence**, re-execute Story 1.3 step 6(b)'s "File the follow-up artifact" + "Link the new artifact from this PR's body" tasks against the FINAL evidence, AMENDING (not duplicating) the Story-1.3 idea file. The PR body link must point at the artifact that reflects the merge-target evidence.
5. **Red→green cleanup (per cycle-3 plan finding #2):** If Story 1.3 was triggered (smoke red on the initial run) AND the FINAL run is `success`:
   - Delete the follow-up artifact folder created by Story 1.3 (e.g., `rm -rf docs/00_overview/planned_features/02_mvp2/infra_solr_smoke_<lever-name>/`).
   - Edit the PR body to REMOVE the "Follow-up" section: `gh pr edit <pr> --body-file <new-body-without-followup.md>` and verify with `gh pr view <pr> --json body -q .body | grep -F 'infra_solr_smoke_' && { echo "PR body still references the deleted artifact" >&2; exit 1; } || true`.
   - Commit on the feature branch: `chore(planned-features): drop infra_solr_smoke_<lever-name> follow-up — final smoke run went green`.
   - **Iterate Task 2-4 once more** for the new HEAD SHA created by this cleanup commit — verify the new final run is also `success` (or if it goes red, re-execute step 4 with the new evidence). One iteration max in practice; if smoke flakes between green and red across iterations, escalate to the user.
6. Verify the PR is ready to merge:
   ```bash
   gh pr view <pr> --json mergeStateStatus,statusCheckRollup -q '{state: .mergeStateStatus, checks: [.statusCheckRollup[] | {name, conclusion}]}'
   ```
   Expect `state: CLEAN` or `state: UNSTABLE` (the latter if smoke red but other jobs green — D-6 allowed merge posture).

**Definition of Done (DoD)**

- [ ] Final `pr.yml` run on the final HEAD SHA satisfies AC-1 (mechanical assertion script exits 0).
- [ ] If smoke red: AC-2 mechanical assertions pass on the FINAL artifact; follow-up artifact reflects FINAL evidence (not stale Story-1.3 evidence); PR body link verified mechanically.
- [ ] If smoke red → green divergence: stale follow-up artifact deleted + PR body "Follow-up" section removed + the post-cleanup HEAD's `pr.yml` run also verified.
- [ ] `gh pr view --json mergeStateStatus` returns `CLEAN` or `UNSTABLE` (depending on smoke outcome).
- [ ] Commit message (if any cleanup commit was made) follows Conventional Commits + DCO.

---

### Story 2.3b — Post-merge state.md finalization (separate follow-up PR)

**Outcome:** A small follow-up PR updates `state.md` to reflect the merge outcome with the actual squash-merge SHA. This matches the project's established pattern (e.g., PR #368 `docs(state): finalize infra_solr_ci_readiness Phase 1 (PR #367 merged)` was a separate finalization PR on the same day as PR #367). It exists as a separate PR because (a) the squash SHA isn't known until merge (cycle-3 plan finding #5) and (b) committing state.md pre-merge would create a chicken-and-egg HEAD invalidation loop (cycle-3 plan finding #1).

**Branch / PR structure**

- Branch: `chore/finalize-infra-solr-smoke-stability` (off the post-merge `main`).
- PR title: `docs(state): finalize infra_solr_smoke_stability (PR #<feature-pr> merged)`.
- Scope: `state.md` only.

**New files**

| File | Purpose |
|---|---|
| _(none)_ | `state.md` only. |

**Modified files**

| File | Change |
|---|---|
| [`state.md`](../../../../../state.md) "Last 5 merges" + "Known debt" sections | Prepend to "Last 5 merges" + UPDATE "Smoke half still open (Phase 2)" entry per the conditional below. |

**Tasks**

1. After the feature PR merges, capture the squash-merge SHA from `gh pr view <feature-pr> --json mergeCommit -q .mergeCommit.oid`.
2. Branch off updated `main`: `git checkout main && git pull && git checkout -b chore/finalize-infra-solr-smoke-stability`.
3. Edit `state.md`:
   - Prepend to "Last 5 merges" (newest first; drop the now-6th row):
     - **Smoke green:** `**2026-MM-DD** — \`infra_solr_smoke_stability\` (PR #XXX, squash-merged \`<SHA>\`). Capped Solr heap to 256m in the smoke job (\`SOLR_HEAP_SIZE: "256m"\` step-env on \`make up\`) + pinned \`COMPOSE_PROJECT_NAME=relyloop\` at job-env + added \`solr\` + \`opensearch\` + \`docker inspect\` exit-state to failure-diagnostics. Smoke job is now green on every branch — completes the \`pr.yml\`-green-on-every-branch contract that started with Phase 1. New runbook at \`docs/03_runbooks/smoke-solr-stability.md\` with the evidence-mapped lever cascade for future Solr CI debt.`
     - **Smoke red:** `**2026-MM-DD** — \`infra_solr_smoke_stability\` (PR #XXX, squash-merged \`<SHA>\`, smoke RED on merge per D-6 fast-lane posture). Diagnostics half landed: smoke-logs artifact now contains Solr + OpenSearch + \`docker inspect\` exit-state. Heap-cap half did NOT fix the crash — captured evidence: <one-line summary from the artifact, e.g. "oom=true (kernel OOMKilled) + Solr boot trace absent" or "Solr heap OOM at Lucene index init">. Follow-up: <link to the filed artifact under \`02_mvp2/infra_solr_smoke_<lever>\`>.`
   - UPDATE "Known debt" entry "Smoke half still open (Phase 2)":
     - **Smoke green:** Strike the entry entirely. Smoke debt resolved.
     - **Smoke red:** Update the entry to: `**Smoke half: lever 1 (heap-cap) shipped 2026-MM-DD but did not fix the crash.** Captured evidence: <summary>. Next escalation: <Lever 2 / Lever 3 / memory-pressure revisit per runbook>. Tracked in \`02_mvp2/infra_solr_smoke_<lever>\`.`
4. Commit + push + open follow-up PR.

**Definition of Done (DoD)**

- [ ] Follow-up PR opened with title `docs(state): finalize infra_solr_smoke_stability (PR #<feature-pr> merged)`.
- [ ] `state.md` "Last 5 merges" prepended with the appropriate (green vs red) one-liner including the actual squash-merge SHA.
- [ ] `state.md` "Known debt" entry updated per the conditional logic above.
- [ ] No `state.md` size-gate violation (`wc -c state.md` < 60 KB).
- [ ] Follow-up PR's CI passes (it's docs-only; the same `pr.yml` matrix runs).
- [ ] Follow-up PR merged.

---

## UI Guidance

**N/A — no frontend scope in this plan.** No `<select>`, no filter chip, no badge, no form, no page. This is a CI workflow + Compose env + runbook + CLAUDE.md edit only.

(Per the template's required note: "No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.")

---

## 3) Testing workstream

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Scope: N/A — no Python code changes
- Tasks: _(none)_
- DoD: _(N/A)_

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Scope: N/A — no DB or service changes
- Tasks: _(none)_
- DoD: _(N/A)_

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Scope: N/A — no API changes; spec has no endpoint catalog
- Tasks: _(none)_
- DoD: _(N/A)_

### 3.4 E2E tests
- Location: `ui/tests/e2e/`
- Scope: N/A — no UI changes
- Tasks: _(none)_
- DoD: _(N/A)_

### 3.5 Static workflow & Compose validation (the only test surface for this plan)

This is the actual test surface — workflow YAML correctness, Compose interpolation correctness, runbook file existence. Verified via the AC commands listed in the spec §12, executed during Story 1.2's Task 4 and Story 1.3's Task 5-6.

- Location: inline in Story 1.1 + 1.2 + 2.1 task lists (no separate test file)
- Tasks:
  - [ ] AC-3 — local `docker compose config` renders `SOLR_HEAP: 512m` and `docker-compose.yml` is unchanged versus `main` (Story 1.2 Task 5)
  - [ ] AC-4 — YAML parse confirms step-level `SOLR_HEAP_SIZE: "256m"` on the `make up` step AND job-level `COMPOSE_PROJECT_NAME: "relyloop"` (Story 1.2 Task 4)
  - [ ] AC-4 — `SOLR_HEAP_SIZE=256m docker compose config --format json` renders Solr's `SOLR_HEAP` as `256m` (Story 1.2 Task 4)
  - [ ] AC-5 — `test -f docs/03_runbooks/smoke-solr-stability.md && grep -q 'smoke-solr-stability.md' CLAUDE.md` (Story 2.2 Task 3)
- DoD:
  - [ ] All four AC verification commands above return success codes
  - [ ] Verification is performed at pre-push gate, not just at CI

### 3.6 Smoke job outcome verification (the empirical half)

The smoke job's own run on this PR is the integration-level verification — AC-1 (outcome triage) + AC-2 (conditional on smoke-red path).

- Location: `pr.yml` smoke-test job on the PR's own CI run (re-verified against the FINAL HEAD SHA per Story 2.3)
- Tasks:
  - [ ] AC-1 — every non-smoke `pr.yml` job is `success`; smoke is `success` or `failure` (NOT cancelled / skipped) — Story 1.3 Task 4-5 (initial) + Story 2.3 Task 3 (final HEAD)
  - [ ] AC-2 (conditional, smoke-red only) — grep `^relyloop-solr-1` + `^relyloop-opensearch-1` on the smoke-logs artifact — Story 1.3 Task 6(b)
- DoD:
  - [ ] AC-1 verified on the FINAL merge run (Story 2.3)
  - [ ] If smoke red: AC-2 verified AND branch protection re-checked AND follow-up artifact (idea file at minimum) filed + linked from PR body

### 3.7 Existing test impact audit

No backend tests, no frontend tests, no E2E tests reference the smoke-job's failure-diagnostics list, the smoke-job env block, or `SOLR_HEAP_SIZE`. Verified via grep:

| Pattern | Files matched | Action |
|---|---|---|
| `SOLR_HEAP_SIZE` | `docker-compose.yml:274` — the existing `${SOLR_HEAP_SIZE:-512m}` override slot (per cycle-1 plan finding #13 — NOT first introduction; this PR adds the first workflow-side assignment of the var, which the existing Compose slot consumes) | None — Story 1.2's `SOLR_HEAP_SIZE: "256m"` env entry intentionally feeds the existing slot |
| `COMPOSE_PROJECT_NAME` | _(none — first introduction)_ | None |
| `relyloop-solr-1` | only in the runbook this plan creates (Story 2.1) | None |
| `docker compose logs --no-color` | only in `.github/workflows/pr.yml` (the line we're editing) | None |

### 3.8 Migration verification

N/A — no migration. Alembic head stays `0022_solr_engine_auth_check`.

### 3.9 CI gates

For an infra-only PR, the relevant CI gates are:

- [ ] `make pre-commit` (runs all hooks including the dashboard regen + REUSE lint + secrets-defense + DCO check) — required pre-push
- [ ] `make lint` (ruff over Python; the workflow YAML doesn't need it but the project guard exists) — required pre-push
- [ ] `make test-unit` (paranoia — verify no accidental project-state change) — required pre-push
- [ ] `pr.yml` static-checks-backend + static-checks-frontend on the PR — required green
- [ ] `pr.yml` backend (full suite) on the PR — required green
- [ ] `pr.yml` frontend on the PR — required green
- [ ] `pr.yml` smoke-test on the PR — required RAN (success OR failure per AC-1)

---

## 4) Documentation update workstream

### 4.0 Core context files (required)

**`state.md`** — update at finalization:
- [ ] "Last 5 merges" — prepend a one-liner describing the smoke-stability work
- [ ] "Known debt" — **conditional update** per spec D-6 + DoD:
  - **If smoke green on merge run:** strike the "Smoke half still open (Phase 2)" item entirely; smoke debt is RESOLVED.
  - **If smoke red on merge run:** UPDATE the same item to record the captured evidence (Solr exit reason from the smoke-logs artifact) + a link to the follow-up spec, NOT marked resolved.

**`architecture.md`** — no changes. CI infra doesn't affect product architecture.

**`CLAUDE.md`** — already handled by Story 2.2 (the Key Runbooks row).

### 4.1 Architecture docs (`docs/01_architecture/`) — no changes.

### 4.2 Product docs (`docs/02_product/`) — no changes (CI infra, not a product feature).

### 4.3 Runbooks (`docs/03_runbooks/`) — Story 2.1 creates `smoke-solr-stability.md`.

### 4.4 Security docs (`docs/04_security/`) — no changes.

### 4.5 Quality docs (`docs/05_quality/`) — no changes (the smoke layer is unchanged in shape; testing.md doesn't need an edit).

**Documentation DoD**

- [ ] `state.md` updated per §4.0 (conditional on smoke green vs red)
- [ ] `CLAUDE.md` Key Runbooks table includes the new row (Story 2.2)
- [ ] `docs/03_runbooks/smoke-solr-stability.md` exists (Story 2.1)

---

## 5) Lean refactor workstream

### 5.1 Refactor goals — _none._ This plan is additive (YAML env keys + log-collect service list + runbook file + CLAUDE.md row). No refactoring opportunity.

### 5.2 Planned refactor tasks — _none._

### 5.3 Refactor guardrails — _N/A._

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `infra_solr_ci_readiness` Phase 1 merged (PR #367) | Story 1.3 outcome triage (the "Solr-may-be-missing-in-CI" contract is established) | Merged 2026-06-01 | None |
| GHA standard `ubuntu-24.04` runner class | Story 1.3 — the heap-cap hypothesis assumes the standard runner | Active; verified via grep that all `pr.yml` jobs use `ubuntu-24.04` / `ubuntu-latest` | A future migration to ARM or self-hosted runners with different memory budgets re-triggers the flake; the runbook §1 calls this out |
| Branch protection on `main` remains permissive (no required smoke check) | Story 1.3 smoke-red path — the D-6 red-merge posture | Permissive as of 2026-05-31 per `state.md` | If protection has been re-enabled, the smoke-red path is closed; Story 1.3 Task 6(b) re-verifies before merge |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Lever 1 (heap-cap) doesn't fix the Solr crash (root cause is non-OOM) | Medium | Low (per D-6, PR merges anyway; diagnostics half is the durable value) | Story 1.3 Task 6(b) — follow-up idea file filed BEFORE merge per the mechanical forcing function |
| `COMPOSE_PROJECT_NAME=relyloop` already set somewhere upstream by the runner | Very low | Low (would just be a redundant env) | Verified — `grep -r COMPOSE_PROJECT_NAME .github/` returns no current usage |
| The new `docker inspect` line in Story 1.1 fails on some container shapes (e.g., no containers ever started) | Low | Low (`|| true` keeps step best-effort) | `|| true` mandatory per spec FR-1 |
| Heap-cap regresses local dev (a contributor mistakenly sets `SOLR_HEAP_SIZE=256m` in `.env`) | Very low | Low (operator can unset; Compose default is preserved) | The override slot pattern is documented in the runbook §4 — operators see "GHA-only" prominently |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Smoke job's `make up` step fails before any Solr container is created | A pre-`make up` step fails (e.g., secret generation, image load) | The failure-diagnostics step still runs (it has `if: failure()`), but `docker compose logs` returns nothing because no Compose stack exists. The step exits 0 due to `|| true`. | Manual: read the run's step-level logs from the GHA UI rather than the artifact |
| Solr container starts, then crashes after the diagnostics step has already run | Race between Solr boot timing and an earlier failure in `make up` | The diagnostics artifact may not contain the actual Solr crash output (it ran too early). Story 1.3 Task 6(b)'s `docker inspect` line captures the exit state regardless. | Re-run the smoke job; or escalate to Lever 2 (start_period bump) to give Solr more boot time |
| Branch protection has been re-enabled to require smoke between spec time and Story 1.3 | Operator added required-status-checks for smoke | Story 1.3 Task 6(b) branch-protection re-check catches this; STOP and escalate (apply Lever 2 as a follow-up commit BEFORE merge, OR split into two PRs) | Manual escalation per Story 1.3 |
| GPT-5.5 review identifies a structural plan flaw after this plan is written | The plan-gen Step 6 cross-model review | Apply findings per gate rules; re-review until convergence | Already accounted for in /impl-plan-gen workflow |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** (diagnostics fold-in) — commit on the new branch.
2. **Story 1.2** (heap-cap + COMPOSE_PROJECT_NAME) — commit on the same branch immediately after.
3. **Story 1.3** (push + watch + triage) — push the branch with both 1.1 + 1.2; open PR; watch CI; triage outcome.
4. **Story 2.1** (runbook) — write AFTER 1.3 (recommended for sharper wording; not a hard gate per cycle-2 plan finding #1 + §0).
5. **Story 2.2** (CLAUDE.md row) — write AFTER 2.1 (the row links to the file that must exist).
6. **Story 2.3a** (pre-merge final verification + red→green cleanup) — re-verify AC-1 (+ AC-2 if red) on the FINAL HEAD SHA. Hard gate before merge.
7. **MERGE THE FEATURE PR** — `gh pr merge --squash` after 2.3a clears.
8. **Story 2.3b** (post-merge state.md finalization PR) — separate small PR off updated `main`, updates `state.md` with the actual squash SHA. Matches the project pattern (PR #368 finalized PR #367).
9. Normal path: 6 stories in the feature PR + 1 in the state.md follow-up PR. Smoke-red path: Story 1.3 adds a follow-up idea file commit before Story 2.3a; if Story 2.3a's final run is green, that follow-up gets deleted in the cleanup step.

### Parallelization opportunities

None — single contributor, single branch, single PR. Stories 1.1 + 1.2 could technically be one commit (both touch the same workflow file) but separating them keeps the git history readable.

---

## 8) Rollout and cutover plan

- **Rollout stages:** _N/A — CI infra, atomic with PR merge._
- **Feature flag strategy:** _N/A._
- **Migration/cutover steps:** _N/A — no migration, no schema, no data._
- **Reconciliation/repair strategy:** _N/A._

The "rollout" is: PR merges → next PR's `pr.yml` run on `main` uses the new workflow. There's no in-flight state to reconcile, no migration to backfill, no operator runbook update beyond Story 2.1.

---

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Failure-diagnostics fold-in
- [ ] Story 1.2 — Lever 1 heap-cap + COMPOSE_PROJECT_NAME pin
- [ ] Story 1.3 — Push, watch CI, triage outcome
- [ ] Story 2.1 — Runbook `smoke-solr-stability.md`
- [ ] Story 2.2 — CLAUDE.md Key Runbooks row
- [ ] Story 2.3a — Pre-merge final CI verification + red→green cleanup (no state.md edit here)
- [ ] Story 2.3b — Post-merge state.md finalization (SEPARATE follow-up PR per project pattern)

### Blocked items

_(none)_

### Done this sprint

_(none yet)_

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] For Stories 1.1 + 1.2: workflow YAML parses + structural assertions pass per AC-4 / AC-3
- [ ] For Story 1.3: smoke-job outcome triaged per AC-1; if red, AC-2 verified + branch protection re-checked + follow-up idea filed + PR body updated
- [ ] For Story 2.1: `test -f` passes for the new runbook; `reuse lint` clean
- [ ] For Story 2.2: AC-5 grep passes
- [ ] For Story 2.3a: final-HEAD AC-1 mechanical assertion exits 0; if smoke red, AC-2 mechanical assertions pass on the FINAL artifact; if red→green divergence, stale follow-up artifact deleted + PR body cleaned
- [ ] For Story 2.3b: separate follow-up PR opened with `state.md` change only; squash SHA filled in; PR body title matches `docs(state): finalize infra_solr_smoke_stability (PR #<feature-pr> merged)` per project pattern
- [ ] Conventional Commits + DCO on every commit
- [ ] No backend/frontend/db tests apply — N/A for this plan
- [ ] No migration round-trip — N/A (no migration)

---

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:** spec has zero endpoints (§8 marked N/A). Plan defines zero endpoints. **Match.**
2. **Spec ↔ plan error code coverage:** spec has zero error codes (§8.5 marked N/A). Plan covers zero. **Match.**
3. **Spec ↔ plan FR coverage:** spec defines FR-1 through FR-4. Plan §1 traceability table maps every one. **Match.**
4. **Story internal consistency:** all 7 stories list New/Modified files explicitly (5 stories in the feature PR — 1.1, 1.2, 1.3, 2.1, 2.2, 2.3a — plus Story 2.3b which is a separate post-merge follow-up PR). **`.github/workflows/pr.yml` is intentionally modified by both Story 1.1 (failure-diagnostics step, lines 716-728) AND Story 1.2 (job header + "Bring up the stack" step env, lines ~487-510 + 620-629) in non-overlapping regions** — the split keeps the diagnostics edit and the lever edit as separate commits for review readability. `state.md` is owned solely by Story 2.3b (which lives in a separate PR). No other file is owned by two stories. **Pass.**
5. **Test file count and assignment:** zero new test files. The 4 AC verification commands (AC-3, AC-4 × 2, AC-5) are inline tasks in Stories 1.2 + 2.2, not separate test files. AC-1 + AC-2 verifications are Story 1.3 tasks. **Pass — no orphaned test files.**
6. **Gate arithmetic:** the ONLY hard pre-merge gate is **Story 2.3a's final-HEAD AC-1/AC-2 re-verification** (per cycle-3 plan finding #3 — Epic 1 → Epic 2 sequencing is advisory only; the real merge gate is Story 2.3a). Story 1.3's CI watch is informational; it can fire before or after Epic 2's runbook commits. Story 2.3b (post-merge state.md PR) is sequenced AFTER merge by construction (needs the squash SHA). 7 stories total: 6 in the feature PR + 1 in the follow-up state.md PR. **Pass.**
7. **Open questions resolved:** spec §19 has zero open questions ("None at spec time" — all locked in D-1 through D-6). **Pass.**
8. **Frontend UI Guidance:** N/A — no frontend scope; explicit "No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan" statement included above. **Pass.**

---

## 12) Definition of plan done

- [x] Every FR (1-4) is mapped to stories/tasks/tests/docs updates per §1 traceability.
- [x] Every story includes New files, Modified files, Endpoints (N/A noted), Key interfaces (N/A noted), Tasks, and DoD.
- [x] Test layers (unit/integration/contract/e2e) are explicitly scoped (all N/A — static workflow validation + smoke job outcome verification IS the test surface; explicitly framed per cycle-3 finding #10).
- [x] Documentation updates planned: Story 2.1 (new runbook), Story 2.2 (CLAUDE.md row), §4.0 (`state.md` finalization).
- [x] Lean refactor scope: explicitly none.
- [x] Phase/epic gates: Epic 1 hard gate = Story 1.3 outcome triaged + (if smoke red) follow-up filed before Epic 2 starts.
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review (§11) performed; no unresolved findings.
