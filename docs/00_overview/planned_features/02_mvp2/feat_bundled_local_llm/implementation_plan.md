# Implementation Plan — Bundled local LLM (one-flag opt-in)

**Date:** 2026-06-19
**Status:** Draft
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** CLAUDE.md (Absolute Rules #2, #8; hermetic-CI pitfall), [deployment.md](../../../01_architecture/deployment.md), [llm-orchestration.md](../../../01_architecture/llm-orchestration.md)

---

## 0) Planning principles

- Every story traces to FR IDs from the spec.
- This is **install/Compose/docs/tests** work — no DB, no migration, no HTTP endpoints, no frontend. UI Guidance, audit-event, and migration sections are **N/A** (stated explicitly below).
- Hermetic CI: nothing in `pr.yml` pulls the Ollama image or a model. Real-model validation is an out-of-CI maintainer gate.
- Mirror existing, proven patterns: `relyloop_engines.sh` (helper), the `solr` service block (Compose), `test_parse_relyloop_engines.sh` (bash test).

## 1) Scope traceability (FR → stories)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (`RELYLOOP_LLM` selector + env-load) | Story 1 | helper + extend `relyloop_env_file.sh` |
| FR-2 (`ollama` Compose service) | Story 2 | profile-gated service + readiness |
| FR-3 (auto-wire endpoint/model + recheck) | Story 3 | install.sh integration |
| FR-4 (`OPENAI_BASE_URL` precedence) | Story 1 (helper owns it) | skip-with-notice; unit-tested in `test_parse_relyloop_llm.sh` |
| FR-5 (`OLLAMA_MODEL` swap) | Story 2 (service) + Story 3 (model default) | no allowlist |
| FR-6 (README + guides) | Story 4 | same PR as code |
| FR-7 (lightweight default) | Story 1 + Story 2 | profile-gating proves it |
| FR-8 (sentinel key + clean revert) | Story 3 | reuse `openai_key` mount |

All spec phases? Phase 1 only — Phase 2 (host-native detection) is tracked in [phase2_idea.md](phase2_idea.md) (verified present). No untracked deferred work.

## 2) Delivery structure

**Structure:** Epic → Story (4 stories). Conventions: bash helpers live in `scripts/lib/`, sourced by `install.sh` + a `scripts/ci/test_*.sh`; helpers exit non-zero with a clear stderr message on bad input, BEFORE any `docker compose` call; Compose services that are opt-in carry `profiles: [...]`; model names stay env-driven (Absolute Rule #8).

**UI element inventory / State dependency / Legacy parity:** N/A — no user-facing component (>0 LOC of JSX) is created, moved, or deleted. No frontend scope anywhere in this plan.

---

### Story 1 — `RELYLOOP_LLM` helper (incl. FR-4 precedence) + `.env` loader extension (FR-1, FR-4, FR-7)

**Outcome:** `RELYLOOP_LLM=ollama` (shell or `.env`) appends `bundled-llm` to `COMPOSE_PROFILES` — **unless `OPENAI_BASE_URL` is set, in which case the helper itself no-ops + prints the skip notice (FR-4 lives in the helper so it's unit-testable in isolation)**. Unset → no profile; unknown value → exit 1 with allowlist message; `OPENAI_BASE_URL`/`OLLAMA_MODEL`/etc. set in `.env` become visible to install.sh's bash logic (loaded before the helper runs).

**New files**

| File | Purpose |
|---|---|
| `scripts/lib/relyloop_llm.sh` | `parse_relyloop_llm()` — validate `RELYLOOP_LLM` against `{ollama}`, append `bundled-llm` to `COMPOSE_PROFILES`. Mirrors `relyloop_engines.sh`. |
| `scripts/ci/test_parse_relyloop_llm.sh` | Bash regression test mirroring `test_parse_relyloop_engines.sh`. |

**Modified files**

| File | Change |
|---|---|
| `scripts/lib/relyloop_env_file.sh` | Extend the by-name extraction loop ([:37](../../../../scripts/lib/relyloop_env_file.sh)) to also read `RELYLOOP_LLM OPENAI_BASE_URL OPENAI_MODEL OPENAI_MODEL_CHAT OLLAMA_MODEL` from `.env` (shell still wins). Keep by-name (never blind-source). |
| `scripts/ci/test_load_relyloop_env_file.sh` | Add cases for the 5 new keys (incl. an `OPENAI_BASE_URL` with `?`/`#` to prove by-name tolerance; `.env`-only value picked up; shell overrides `.env`). |
| `.github/workflows/pr.yml` | Add a `parse_relyloop_llm regression` step next to the existing helper tests ([~:375](../../../../.github/workflows/pr.yml)). |

**Key interfaces** (bash)

```bash
# scripts/lib/relyloop_llm.sh
parse_relyloop_llm() {
  # 1. FR-4 precedence FIRST: if $OPENAI_BASE_URL non-empty → print skip notice,
  #    do NOT append bundled-llm, return 0 — operator endpoint wins REGARDLESS of
  #    RELYLOOP_LLM (even a typo'd value isn't an error when an endpoint is set)
  # 2. unset/empty $RELYLOOP_LLM → no-op return 0
  # 3. unknown $RELYLOOP_LLM (OPENAI_BASE_URL empty) → stderr + return 1 (set -e → exit 1)
  # 4. ollama → append "bundled-llm" to COMPOSE_PROFILES (comma-join, dedupe, bash-3.2-safe)
}
```

**Tasks**
1. Write `relyloop_llm.sh` mirroring `relyloop_engines.sh` (SPDX header, allowlist `{ollama}`, **FR-4 precedence check on `OPENAI_BASE_URL`**, append-not-overwrite to `COMPOSE_PROFILES`, bash-3.2-safe array idioms).
2. Extend `relyloop_env_file.sh` key list to the 5 new keys.
3. Write `test_parse_relyloop_llm.sh`: unset → unchanged (no `bundled-llm`); `ollama` → contains `bundled-llm`; composes with pre-set `COMPOSE_PROFILES=solr` → `solr,bundled-llm`; **`ollama` + `OPENAI_BASE_URL=…` set → rc 0, no `bundled-llm` + notice (FR-4)**; **`vllm` + `OPENAI_BASE_URL=…` set → rc 0 (precedence short-circuits before allowlist), no `bundled-llm`**; `vllm` (no endpoint) → rc≠0 + stderr names `ollama`; whitespace tolerated.
4. Extend `test_load_relyloop_env_file.sh` for the new keys.
5. Wire both into `pr.yml`.

**Definition of Done**
- `bash scripts/ci/test_parse_relyloop_llm.sh` + `test_load_relyloop_env_file.sh` pass locally (AC-2, AC-4, AC-5).
- `shellcheck` clean on the new/modified `scripts/lib` + `scripts/ci` files.
- `pr.yml` runs the new test.

---

### Story 2 — `ollama` Compose service + default-off guards (FR-2, FR-5 service, FR-7)

**Outcome:** A profile-gated `ollama` service serves `${OLLAMA_MODEL:-qwen3.5:4b}`, healthy only once the model is served (with a readiness budget for the multi-GB pull); the default `up` never starts it; `selected_engines` ignores the `bundled-llm` token.

**New files**

| File | Purpose |
|---|---|
| `docker/ollama/entrypoint.sh` | **Chosen mechanism (decided here, not deferred):** start `ollama serve` in the background, wait for the daemon to accept connections, run `ollama pull "$OLLAMA_MODEL"`, then `wait` on (foreground) the serve PID. Mounted into the `ollama` service as its `entrypoint`. Single service, no cross-profile `depends_on`. The healthcheck (`ollama show "$OLLAMA_MODEL"`) only passes once the pull has completed. |

**Modified files**

| File | Change |
|---|---|
| `docker-compose.yml` | Add `ollama` service: `profiles: ["bundled-llm"]`, `image: ${BASE_REGISTRY:-}ollama/ollama:${OLLAMA_IMAGE_TAG:-<pinned non-latest>}`, `environment: OLLAMA_MODEL=${OLLAMA_MODEL:-qwen3.5:4b}`, volume `./data/ollama:/root/.ollama`. **Healthcheck must use `$$` so Compose passes the var to the container shell at runtime (not host-interpolated at config time):** `test: ["CMD-SHELL", "ollama show \"$${OLLAMA_MODEL}\""]`, with generous `start_period`/`retries` for the multi-GB pull. Do NOT add `depends_on: ollama` to api/worker. |
| `backend/tests/unit/test_compose_deployment_shape.py` | Assert: `ollama` service exists; `profiles == ["bundled-llm"]`; image matches `${BASE_REGISTRY:-}ollama/ollama:` and not `latest`; api/worker have no `depends_on.ollama` (extend the existing `["api","worker"]` parametrization). |
| `backend/tests/unit/core/test_settings_selected_engines.py` (new test fn or file) | `COMPOSE_PROFILES="solr,bundled-llm"` → `Settings().selected_engines == {"solr"}` — locks the `& known` filter at [settings.py:484](../../../../backend/app/core/settings.py). |
| `.gitignore` | Ensure `./data/ollama` is covered by the existing `./data/` ignore (verify; likely already). |

**Tasks**
1. Add the `ollama` service mirroring the `solr` block (profiles/image/volume/healthcheck), `entrypoint: ["/entrypoint.sh"]` (the serve+pull script above, mounted read-only), and a readiness budget tuned for a multi-GB first pull (large `start_period`, ample `retries`). Pin a concrete non-`latest` `ollama/ollama` tag.
2. Confirm no `depends_on: ollama` is added anywhere.
3. Extend `test_compose_deployment_shape.py` (YAML-dict assertions only — no `compose config` exclusion). Include an assertion that the healthcheck `test` string contains `$${OLLAMA_MODEL}` (double-dollar, runtime-interpolated) — guards the Compose-interpolation gotcha.
4. Add the `selected_engines` guard test.
5. `docker compose --profile bundled-llm config --quiet` parses; default `docker compose config --quiet` parses.

**Definition of Done**
- `make test-unit` green incl. the new compose-shape + `selected_engines` assertions (AC-1, AC-8).
- `docker compose --profile bundled-llm config --quiet` exits 0; default config has no active `ollama` (YAML `profiles` proves it).
- No `depends_on: ollama` on api/worker (test-asserted).

---

### Story 3 — install.sh integration: wire endpoint/model, sentinel key, precedence, recheck (FR-3, FR-4, FR-8, FR-5 default)

**Outcome:** `RELYLOOP_LLM=ollama make up` (no `OPENAI_BASE_URL`) brings up Ollama, points the app at it, writes a sentinel key, and `/healthz` reaches `openai: configured`. Setting `OPENAI_BASE_URL` skips the bundle with a notice. Reverting to Option A clears the sentinel.

**Modified files**

| File | Change |
|---|---|
| `scripts/install.sh` | After `parse_relyloop_engines` (§5), source + call `parse_relyloop_llm` (the helper owns FR-4 precedence + the skip-notice — install.sh does not strip). **All secret/env resolution happens BEFORE `docker compose up` (§8)** so containers start in the correct state: (a) if `bundled-llm` ∈ `COMPOSE_PROFILES` → `export OPENAI_BASE_URL=http://ollama:11434/v1`; **preserving** model defaults `export OPENAI_MODEL="${OPENAI_MODEL:-${OLLAMA_MODEL:-qwen3.5:4b}}"` + same for `OPENAI_MODEL_CHAT` (never clobber an operator-set value, FR-3); write sentinel `ollama` into `./secrets/openai_key` iff empty-or-sentinel (FR-8); pre-create `./data/ollama` (mirror §7c). (b) Whenever `bundled-llm` is NOT active → clear `./secrets/openai_key` to empty **iff its content == sentinel** (covers BOTH revert-to-A *and* B→C; warn on the B→C case to set a real key), so api never starts with a stale `Bearer ollama` against the cloud default or the operator's endpoint (FR-8 clean revert). **After** `up --wait`: if `bundled-llm` active → `docker compose restart api worker` (the FastAPI lifespan re-runs the capability check against the now-ready endpoint and overwrites the cached result — [main.py:94](../../../../backend/app/main.py)), so `/healthz` reaches `configured` without the 24h stale window (FR-3). |

**Key interfaces** (bash, in install.sh)

```bash
source scripts/lib/relyloop_llm.sh
parse_relyloop_llm                       # appends bundled-llm UNLESS OPENAI_BASE_URL set (FR-4 in helper)

# ---- BEFORE `docker compose up -d --wait` (containers must start correctly) ----
if [[ ",${COMPOSE_PROFILES:-}," == *",bundled-llm,"* ]]; then
  export OPENAI_BASE_URL="http://ollama:11434/v1"
  export OPENAI_MODEL="${OPENAI_MODEL:-${OLLAMA_MODEL:-qwen3.5:4b}}"          # preserve operator value
  export OPENAI_MODEL_CHAT="${OPENAI_MODEL_CHAT:-${OLLAMA_MODEL:-qwen3.5:4b}}"
  [[ -s ./secrets/openai_key && "$(cat ./secrets/openai_key)" != "ollama" ]] || printf 'ollama' > ./secrets/openai_key  # sentinel iff empty-or-sentinel
  mkdir -p ./data/ollama
else
  # Bundle NOT active. A leftover sentinel is stale whether reverting to A
  # (OPENAI_BASE_URL empty → must read missing_key) or switching to C
  # (OPENAI_BASE_URL set → must NOT send `Bearer ollama` to the operator's
  # endpoint). Clear it in BOTH cases; warn on the B→C case.
  if [[ -s ./secrets/openai_key && "$(cat ./secrets/openai_key)" == "ollama" ]]; then
    : > ./secrets/openai_key
    [[ -n "${OPENAI_BASE_URL:-}" ]] && echo "Cleared bundled-LLM sentinel key; set a real key in ./secrets/openai_key for your OPENAI_BASE_URL endpoint." >&2
  fi
fi

# ... docker compose up -d --wait ...

# ---- AFTER up: force a fresh capability probe against the ready endpoint ----
if [[ ",${COMPOSE_PROFILES:-}," == *",bundled-llm,"* ]]; then
  docker compose restart api worker   # lifespan re-runs run_capability_check_background → overwrites cache
fi
```

**Tasks**
1. Wire `parse_relyloop_llm` into install.sh; add the pre-`up` resolution block (export endpoint + preserving model defaults + sentinel write + `./data/ollama` mkdir) and the revert-clear branch.
2. Sentinel write (Option B) + sentinel clear (revert to A); never touch a non-sentinel key. Both happen BEFORE `up`.
3. Post-`up` `docker compose restart api worker` under Option B (deterministic recheck — lifespan re-probes).
4. Add AC-9 guard: unit test asserting the capability check returns `missing_key` (no probe) on an empty key — verify existing coverage in `backend/tests/unit/llm/`; add if absent.

**Definition of Done**
- AC-3: with `RELYLOOP_LLM=ollama` + empty key + unset `OPENAI_BASE_URL`, api/worker env shows the ollama URL + `qwen3.5:4b`, `./secrets/openai_key` holds the sentinel, `/healthz` reaches `configured` post-recheck (manual clean-room).
- AC-4: `OPENAI_BASE_URL` + `RELYLOOP_LLM=ollama` → no `ollama` container + skip notice (manual).
- AC-9: empty-key gate unit test green.
- Revert: after a `bundled-llm` run, a plain `make up` clears the sentinel and `/healthz` is `missing_key` (manual clean-room).
- `bash -n scripts/install.sh` + shellcheck clean.

---

### Story 4 — Documentation (FR-6) + release-gate

**Outcome:** README documents Options A/B/C side-by-side (shipped with the code); guides, runbook, CLAUDE.md, `.env.example`, and the release checklist updated.

**Modified files**

| File | Change |
|---|---|
| `README.md` | Add the three-option LLM block (A: default/no-LLM, B: `RELYLOOP_LLM=ollama make up` → `qwen3.5:4b` + CPU-only-macOS caveat + ~2–3 GB pull, C: `OPENAI_BASE_URL` BYO + bundle-skip), per spec FR-6 draft copy. |
| `.env.example` | Add commented `# RELYLOOP_LLM=ollama` + `# OLLAMA_MODEL=qwen3.5:4b`; **clarify that the uncommented `OPENAI_BASE_URL` (line 32) means Option C and disables Option B** — comment it out by default OR add an explicit note so a copied `.env.example` doesn't silently bypass the bundle. |
| `docs/01_architecture/deployment.md` | Document the `bundled-llm` profile + `RELYLOOP_LLM` alongside the engine-profile section; note the model-registry egress (distinct from `BASE_REGISTRY`). |
| `docs/01_architecture/llm-orchestration.md` | Add bundled-Ollama as a first-class local endpoint option. |
| `docs/08_guides/llm-endpoint-setup.md` + `docs/08_guides/tutorial-first-study.md` (Step 0) | Fold in the opt-in + CPU-only caveat + the B→C key caveat. |
| `docs/03_runbooks/corporate-network-install.md` | Note model-registry egress for Option B + Option C as the corp fallback. |
| `docs/03_runbooks/release-checklist.md` | Add the out-of-CI LLM-compatibility gate (run the real capability check against `ollama/ollama:<pinned>` + `qwen3.5:4b`; record known-good). |
| `CLAUDE.md` | Add `RELYLOOP_LLM` to install-time vars + the `bundled-llm` profile to the ports/compose notes. |

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/docs/test_readme_documents_bundled_llm.py` (or extend `test_claude_md_sections.py`) | Assert README contains `RELYLOOP_LLM=ollama` and the three options — keeps README ↔ helper in lockstep (clean-room discipline, AC-7). |

**Tasks**
1. Write the README block (FR-6 draft copy from spec).
2. Update `.env.example` (commented vars + OPENAI_BASE_URL precedence clarification).
3. Update the architecture/guide/runbook/CLAUDE docs.
4. Add the README doc test.
5. Run `bash scripts/regen-generated-artifacts.sh` if any generated-doc surface is touched (guides), to keep freshness gates green.

**Definition of Done**
- AC-7: README documents A/B/C; README doc test green.
- `make test-unit` green; generated-artifact freshness gates green.
- CLAUDE.md lists `RELYLOOP_LLM` + `bundled-llm`.

---

## 3) Testing workstream

### 3.1 Unit tests (`backend/tests/unit/`)
- [ ] `test_compose_deployment_shape.py` — `ollama` service shape + profile + no api/worker depends_on (Story 2).
- [ ] `core/test_settings_selected_engines.py` — `selected_engines` ignores `bundled-llm` (Story 2).
- [ ] `llm/` — empty-key gate returns `missing_key` without probing (AC-9, Story 3; verify/extend existing).
- [ ] `docs/test_readme_documents_bundled_llm.py` — README documents the options (Story 4).

### 3.2 Integration tests
- N/A — no DB workflow. (Option B end-to-end requires a real model pull → out-of-CI manual clean-room, not an integration test.)

### 3.3 Contract tests
- N/A — no HTTP endpoints added.

### 3.4 E2E tests
- N/A — no UI.

### 3.5 Bash regression tests (`scripts/ci/`)
- [ ] `test_parse_relyloop_llm.sh` (Story 1) — allowlist, append, precedence, unknown→exit1.
- [ ] `test_load_relyloop_env_file.sh` extension (Story 1) — 5 new keys, `.env`-only + shell-override.
- [ ] Both wired into `pr.yml`.

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make lint` / `make typecheck` (Python untouched mostly; shellcheck on bash)
- [ ] `bash scripts/ci/test_parse_relyloop_llm.sh`
- [ ] No model pull in any CI job (hermetic).

### 3.7 Out-of-CI maintainer gates (release checklist)
- [ ] Clean-room: Option A (no LLM, `missing_key`, clean revert) + Option B (`RELYLOOP_LLM=ollama make up` → `configured` → chat) on a real host.
- [ ] LLM-compatibility: real `function_calling` + `structured_output` probe of `qwen3.5:4b` via the pinned Ollama image; record known-good (fallback to Qwen3 small instruct if it fails).

### Migration verification
- N/A — no schema change.

## 4) Documentation update workstream

Covered by Story 4. Core context files: `state.md` (add the feature to recent changes + note `RELYLOOP_LLM`), `CLAUDE.md` (install-time vars + `bundled-llm` profile + ports note), `architecture.md` (note the optional LLM service if material). No audit-event docs (N/A).

## 5) Lean refactor workstream

- Minimal. The only refactor is extending `relyloop_env_file.sh`'s key list (additive). No dead-code removal. Guardrail: the existing `test_load_relyloop_env_file.sh` must stay green (behavioral parity for the existing 4 keys).

## 6) Dependencies, risks, and mitigations

### Dependencies
| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `ollama/ollama` image (pinned) | Story 2 | external/stable | Option B unavailable; A/C unaffected |
| `qwen3.5:4b` in Ollama library | Story 2/3 | confirmed | `OLLAMA_MODEL` overrides; Qwen3 fallback |

### Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Healthcheck too tight → `up --wait` false-fails on slow pull | M | M | generous `start_period`/`retries` (FR-2 readiness budget); document |
| `qwen3.5:4b` fails tool-calling/structured-output via Ollama | M | M | out-of-CI compat gate; Qwen3 small instruct fallback (§16) |
| Sentinel key sent to cloud after B→C without real key | L | M | FR-8 clean-revert clears sentinel on revert to A; doc the B→C key step |
| `.env.example`'s uncommented `OPENAI_BASE_URL` silently disables Option B | M | M | Story 4 comments it / documents precedence |
| Capability check caches pre-ready failure 24h | M | M | FR-3 post-`--wait` recheck (restart api/worker) |

### Failure mode catalog
| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Model pull blocked (corp/no egress) | Option B first run, model-registry blocked | `up --wait` surfaces ollama unhealthy; install.sh up/build error path | retry or use Option C (documented) |
| Both `RELYLOOP_LLM` + `OPENAI_BASE_URL` set | misconfig | skip-with-notice; endpoint wins; no container | none needed (intended) |
| Unknown `RELYLOOP_LLM` | typo | exit 1 + allowlist message before any pull | fix the value |

## 7) Sequencing and parallelization

### Suggested sequence
1. Story 1 (helper + env-load) — foundation.
2. Story 2 (Compose service) — independent of Story 1; can parallelize.
3. Story 3 (install.sh integration) — depends on Story 1 + Story 2.
4. Story 4 (docs) — after behavior is final.

### Parallelization
- Stories 1 and 2 are independent (bash helper vs Compose YAML) — parallelizable. Story 3 joins them; Story 4 last.

## 8) Rollout and cutover plan

- Opt-in by construction (`RELYLOOP_LLM`); no flag, no migration, no cutover. README/guide docs ship in the same PR (clean-room discipline). Lightweight default is unchanged for existing users.

## 9) Execution tracker

### Current sprint
- [ ] Story 1 — `relyloop_llm.sh` helper + env-load extension + bash tests
- [ ] Story 2 — `ollama` Compose service + compose-shape/selected_engines guards
- [ ] Story 3 — install.sh integration (wire/precedence/sentinel/recheck)
- [ ] Story 4 — docs (README/guides/runbook/CLAUDE/.env.example) + README doc test

### Blocked items
- None.

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate

- [ ] Files created/modified match story scope.
- [ ] Bash helpers exit non-zero before any `docker compose` call on bad input.
- [ ] No `depends_on: ollama` on api/worker (test-asserted).
- [ ] Model names env-driven (no hardcoded tag in Python).
- [ ] `make test-unit` + new bash tests pass; shellcheck clean.
- [ ] No CI job pulls the Ollama image or a model.
- [ ] README/docs updated in the same PR when behavior changed.

## 11) Plan consistency review

- **FR coverage:** all 8 FRs mapped (table §1); each assigned to ≥1 story. ✓
- **Endpoint/error-code parity:** spec adds 0 endpoints / 0 error codes → 0 in plan. ✓
- **Test file assignment:** every test in §3 assigned to a story (compose-shape→S2, selected_engines→S2, empty-key→S3, bash tests→S1, README doc→S4). No orphans. ✓
- **File ownership:** no file is "new" in two stories. `install.sh` modified only in S3; `docker-compose.yml` only in S2; `relyloop_env_file.sh` only in S1. ✓
- **Codebase paths verified:** `scripts/lib/`, `scripts/ci/`, `backend/tests/unit/test_compose_deployment_shape.py`, `backend/app/core/settings.py:484`, `.github/workflows/pr.yml:375`, `.env.example:32`, solr block in `docker-compose.yml` — all confirmed by reads this session. ✓
- **Open questions:** spec §19 has none open. ✓
- **UI Guidance / migration / audit:** N/A (stated). ✓
- **Gate arithmetic:** 4 stories, 0 endpoints, 4 unit test files + 2 bash tests. ✓

## 12) Definition of plan done

- [x] Every FR mapped to a story + tests + docs.
- [x] Each story has New/Modified files, Tasks, DoD (Endpoints/Schemas N/A — no API surface).
- [x] Test layers scoped (unit + bash; integration/contract/e2e N/A with reasons).
- [x] Doc updates planned (Story 4 + §4).
- [x] Refactor scope bounded (§5).
- [x] Story verification gate included (§10).
- [x] Consistency review performed (§11), no unresolved findings.
