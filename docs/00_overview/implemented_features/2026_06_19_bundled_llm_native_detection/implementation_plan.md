# Implementation Plan — Native-first local LLM (use host Ollama; demote Docker bundle)

**Date:** 2026-06-19
**Status:** Complete (PR #577, merged 2026-06-19 `71803791`)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** CLAUDE.md (Absolute Rules #2, #8; hermetic-CI), the shipped `feat_bundled_local_llm`

---

## 0) Planning principles

- Install/Compose/bash/docs only — no DB, migration, endpoints, or frontend. UI Guidance / audit / migration sections are **N/A** (stated).
- Reuse the shipped plumbing (`relyloop_llm.sh`, install.sh §5c, sentinel key, the `ollama` Compose service); the new risk is the native-detect logic, which becomes a **mocked-probe-testable helper** (no out-of-CI-only blind spots).
- Hermetic CI: the host probe finds nothing in CI → native-absent path; the found path is covered by the mocked-probe bash test.

## 1) Scope traceability (FR → stories)

| FR | Story | Notes |
|---|---|---|
| FR-1 (`{ollama, ollama-docker}`; `ollama`=no profile) | Story 1 | helper allowlist rework |
| FR-2 (native probe + shape validation, testable helper) | Story 2 | new `relyloop_native_llm.sh` |
| FR-3 (effective-model presence + `:latest` norm) | Story 2 | in the native helper |
| FR-4 (`extra_hosts` + Linux/min-Docker docs) | Story 3 (compose) + Story 4 (docs) | |
| FR-5 (`OPENAI_BASE_URL` precedence unchanged) | Story 1 | helper (already) |
| FR-6 (docs) | Story 4 | |
| FR-7 (`ollama` Compose service unchanged) | Story 3 | no edit; assert in test |
| FR-8 (post-`up` reachability + summary line) | Story 3 | install.sh |

All spec phases covered? Yes — single phase. No deferred work / no `phaseN_idea.md`.

## 2) Delivery structure

Epic → Story (4). Conventions: bash helpers in `scripts/lib/`, sourced by install.sh + a `scripts/ci/test_*.sh`; helpers fail non-zero with a clear message before any `docker compose` call; native probe is injectable for testing; model names env-driven.

**UI / State / Legacy parity:** N/A — no frontend component touched.

---

### Story 1 — `relyloop_llm.sh`: `{ollama, ollama-docker}` allowlist (FR-1, FR-5)

**Outcome:** `ollama` no longer appends the `bundled-llm` profile (native path); `ollama-docker` appends it (the shipped container path); unknown → exit 1 naming both; `OPENAI_BASE_URL` precedence unchanged (strips a pre-seeded token).

**Modified files**

| File | Change |
|---|---|
| `scripts/lib/relyloop_llm.sh` | Allowlist `{ollama, ollama-docker}`. `ollama` → return 0 with NO profile append (native handled in install.sh). `ollama-docker` → append `bundled-llm` (the current `ollama` behavior). Keep the FR-4 precedence block (OPENAI_BASE_URL set → no-op + notice + strip). Update header comments. |
| `scripts/ci/test_parse_relyloop_llm.sh` | Rework: `ollama` + `solr` preset → `solr` (no bundled-llm); `ollama-docker` + `solr` → `solr,bundled-llm`; `ollama-docker` already-present → idempotent; whitespace; precedence (OPENAI_BASE_URL set → strip) for both values; unknown `vllm` (no endpoint) → exit 1 naming `ollama, ollama-docker`. |

**Tasks**
1. Change the allowlist check: accept `ollama` (no append) and `ollama-docker` (append `bundled-llm`); everything else → error naming both.
2. Update the unknown-value message to `Allowed: ollama, ollama-docker.`
3. Rework the bash test cases accordingly.

**DoD**
- `bash scripts/ci/test_parse_relyloop_llm.sh` passes (AC-1, AC-2, AC-6, AC-8); shellcheck clean.

---

### Story 2 — `relyloop_native_llm.sh` native-detect helper + tests (FR-2, FR-3)

**Outcome:** A sourceable, **mocked-probe-testable** function resolves a host-native Ollama and, on a validated find, exports `OPENAI_BASE_URL`/model defaults + prints success; on not-found prints actionable guidance; on a detected-but-missing effective model prints the exact `ollama pull` command.

**New files**

| File | Purpose |
|---|---|
| `scripts/lib/relyloop_native_llm.sh` | `resolve_native_ollama()` — the testable core: (0) **early OPENAI_BASE_URL skip** — if `$OPENAI_BASE_URL` is set, no-op return 0 without probing (P-2). (1) probe `${RELYLOOP_NATIVE_PROBE_URL:-http://localhost:11434/api/tags}` via an **overridable probe FUNCTION** `${RELYLOOP_NATIVE_PROBE_FUNC:-relyloop_native_probe}` (default wraps `curl -fsS --max-time 2 "$1"`; tests set `RELYLOOP_NATIVE_PROBE_FUNC=mock_probe`) — a command-string env var is shellcheck-brittle (P-4); no `eval`. (2) **validate shape** with `grep -Eq '"models"[[:space:]]*:[[:space:]]*\['` (require the array opener, not just the `"models"` substring — P-3); malformed/non-Ollama → guidance + return 1. (3) on found: export `OPENAI_BASE_URL=http://host.docker.internal:11434/v1` + `OPENAI_MODEL`/`OPENAI_MODEL_CHAT="${...:-${OLLAMA_MODEL:-qwen3.5:4b}}"`; **write the sentinel** into `${RELYLOOP_OPENAI_KEY_FILE:-./secrets/openai_key}` (injectable path → testable; empty-or-sentinel guard, P-1); per missing effective model (grep with `:latest` normalization) echo the exact `ollama pull <model>`; return 0. (4) not-found: clear a stale sentinel (iff == sentinel), echo the install/`ollama-docker`/`OPENAI_BASE_URL` guidance, return 1. **Message helpers** (`_native_summary_no_llm`, `_native_warn_unreachable`) are sourceable so the FR-8 strings are testable (P-6). |
| `scripts/ci/test_relyloop_native_llm.sh` | Mocked-probe regression test (see Tasks/DoD). |

**Modified files**

| File | Change |
|---|---|
| `.github/workflows/pr.yml` | Add `relyloop_native_llm regression` step next to the other helper tests (~:375). |

**Key interfaces** (bash)

```bash
# scripts/lib/relyloop_native_llm.sh
relyloop_native_probe() { curl -fsS --max-time 2 "$1"; }   # overridable for tests
resolve_native_ollama() {
  # 0. $OPENAI_BASE_URL set -> no-op return 0 (don't probe).
  # 1. body="$("${RELYLOOP_NATIVE_PROBE_FUNC:-relyloop_native_probe}" "$url")" or not-found.
  # 2. grep -Eq '"models"[[:space:]]*:[[:space:]]*\[' <<<"$body" else not-found.
  # 3. found -> export OPENAI_BASE_URL + model defaults; write sentinel to
  #    ${RELYLOOP_OPENAI_KEY_FILE:-./secrets/openai_key}; warn per missing
  #    effective model (:latest-normalized grep); return 0.
  # 4. not-found -> clear stale sentinel; _native_*_guidance; return 1.
}
```

**Tasks**
1. Write `resolve_native_ollama` + `relyloop_native_probe` + the `_native_*` message helpers (overridable probe FUNCTION, tight `"models":[` grep, injectable `RELYLOOP_OPENAI_KEY_FILE`, effective-model `:latest`-normalized grep, sentinel write/clear).
2. Write `test_relyloop_native_llm.sh` (mocked probe via `RELYLOOP_NATIVE_PROBE_FUNC`, `RELYLOOP_OPENAI_KEY_FILE` → tempfile): (a) Ollama-shaped → `OPENAI_BASE_URL`=host.docker.internal + sentinel written, rc 0; (b) malformed shapes `{"models":"bad"}` / `{"not_models":[]}` / plain text containing `models` → rc 1, no export, **no sentinel** (AC-9, P-3); (c) probe fails → rc 1 + guidance + stale sentinel cleared (AC-4); (d) `OLLAMA_MODEL` absent from body → exact `ollama pull <model>` warning (AC-5); (e) `:latest` normalization — effective `llama3` matches body `llama3:latest` (no warning); missing `llama3` → `ollama pull llama3` (P-5); (f) operator `OPENAI_MODEL` set → that effective model is the one checked; (g) **`OPENAI_BASE_URL` set → probe NOT invoked** (mock probe fails the test if called), env unchanged, rc 0 (P-2); (h) FR-8 message helpers emit the exact substrings `WITHOUT LLM features` / `ollama-docker` / `OPENAI_BASE_URL` / `OLLAMA_HOST=0.0.0.0` (P-6).
3. Wire into `pr.yml`.

**DoD**
- `bash scripts/ci/test_relyloop_native_llm.sh` passes (AC-9 + FR-2/FR-3/FR-8 message paths); shellcheck clean; wired into CI.

---

### Story 3 — install.sh integration + `extra_hosts` (FR-2 wiring, FR-4, FR-7, FR-8)

**Outcome:** `RELYLOOP_LLM=ollama` runs native-detect pre-`up` (found → sentinel + no container; not-found → LLM-free); api/worker reach the host on Linux; post-`up` reachability check + summary line catch the Linux-loopback trap.

**Modified files**

| File | Change |
|---|---|
| `scripts/install.sh` | In §5c, source `relyloop_native_llm.sh`. For the `ollama` value (bundled-llm NOT in profiles): call `resolve_native_ollama` — the helper owns the probe + env export + sentinel write/clear (rc 0 = native wired, rc 1 = not-found). On rc 0 set `NATIVE_LLM_ACTIVE=1`; on rc 1 call the helper's `_native_summary_no_llm` (the unmistakable no-LLM line) and proceed LLM-free. The `ollama-docker` path keeps the shipped container behavior (profile + sentinel + `./data/ollama` + the post-`up` restart). Add the FR-8 post-`up` block: if `NATIVE_LLM_ACTIVE` → `docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=3)"`; on failure call the helper's `_native_warn_unreachable` (the Linux-loopback/`OLLAMA_HOST=0.0.0.0` warning). |
| `docker-compose.yml` | Add `extra_hosts: ["host.docker.internal:host-gateway"]` to `api` and `worker`. |
| `backend/tests/unit/test_compose_deployment_shape.py` | Assert `api` + `worker` carry `extra_hosts` containing `host.docker.internal:host-gateway`; assert the `ollama` service profile is still `["bundled-llm"]` (unchanged, FR-7). |

**Tasks**
1. Wire the native-detect call + sentinel handling into install.sh §5c (native vs ollama-docker vs not-found branches).
2. Add `extra_hosts` to api + worker.
3. Add the FR-8 post-`up` reachability check (api-container Python) + the no-LLM summary line.
4. Extend `test_compose_deployment_shape.py`.

**DoD**
- `make test-unit` green incl. the `extra_hosts` assertion (AC-7); `bash -n scripts/install.sh` + shellcheck clean.
- Operator-path (out-of-CI): native-present → `configured`; native-absent → guidance + `missing_key`; Linux-loopback → FR-8 warning; `ollama-docker` → container path (AC-3, AC-4, AC-10).

---

### Story 4 — Documentation (FR-6, FR-4 docs)

**Outcome:** README + guides present `ollama` as native-first, `ollama-docker` as the slow fallback, with the Linux `OLLAMA_HOST=0.0.0.0` + min-Docker notes and the upgrade callout.

**Modified files**

| File | Change |
|---|---|
| `README.md` | Rewrite the LLM-options block: **A** no LLM (default); **B** `RELYLOOP_LLM=ollama` = use your native (Metal-fast) Ollama (prereq: install + `ollama serve` + `ollama pull qwen3.5:4b`; if absent → guidance, no LLM); **B-fallback** `RELYLOOP_LLM=ollama-docker` = slow zero-install CPU container; **C** `OPENAI_BASE_URL` = any endpoint. Upgrade note: `ollama` no longer auto-starts the Docker container. |
| `.env.example` | Update the `RELYLOOP_LLM` comment for `ollama` (native) vs `ollama-docker`. |
| `docs/01_architecture/deployment.md` | Native-first behavior; the `extra_hosts`/`host-gateway` min-Docker note; Linux `OLLAMA_HOST=0.0.0.0`. |
| `docs/01_architecture/llm-orchestration.md` | Update the bundled-LLM note → native-first. |
| `docs/08_guides/llm-endpoint-setup.md` + tutorial Step 0 | Native-first + `ollama-docker`; Linux loopback caveat. |
| `docs/03_runbooks/release-checklist.md` | Replace/extend §5b: native-present / native-absent / Linux-loopback / `ollama-docker` matrix. |
| `CLAUDE.md` | `RELYLOOP_LLM` values `{ollama (native), ollama-docker}`. |
| `backend/tests/unit/docs/test_readme_documents_bundled_llm.py` | Update assertions: README contains `RELYLOOP_LLM=ollama` (native) + `ollama-docker`; helper allowlist match updated. |

**Tasks**
1. Rewrite the README LLM block + the upgrade note.
2. Update `.env.example`, architecture/guide/runbook/CLAUDE docs.
3. Update the README doc test for the new wording + `ollama-docker`.
4. `bash scripts/regen-generated-artifacts.sh` (guides touched).

**DoD**
- README documents native-first + `ollama-docker`; README doc test green; freshness gates green.

---

## 3) Testing workstream

### 3.1 Unit (`backend/tests/unit/`)
- [ ] `test_compose_deployment_shape.py` — `extra_hosts` on api/worker; `ollama` profile unchanged (Story 3).
- [ ] `docs/test_readme_documents_bundled_llm.py` — native-first wording + `ollama-docker` (Story 4).

### 3.2 / 3.3 / 3.4 Integration / Contract / E2E
- N/A — no DB/endpoints/UI.

### 3.5 Bash (`scripts/ci/`)
- [ ] `test_parse_relyloop_llm.sh` reworked (Story 1) — allowlist `{ollama,ollama-docker}`.
- [ ] `test_relyloop_native_llm.sh` NEW (Story 2) — mocked-probe native-detect (found / not-Ollama-200 / not-found / model-missing / `:latest` / effective-model).
- [ ] Both wired into `pr.yml`.

### 3.6 CI gates
- [ ] `make test-unit`; `make lint`/`typecheck`; the two bash tests; shellcheck; **no model pull / no real network in CI**.

### 3.7 Out-of-CI operator-path (release checklist)
- [ ] Native-present (Metal) → `configured` + chat; native-absent → guidance + `missing_key`; Linux-loopback → FR-8 warning; `ollama-docker` → slow container path.

### Migration verification
- N/A — no schema change.

## 4) Documentation workstream
Covered by Story 4. Core files: `state.md` (recent changes + `RELYLOOP_LLM` values), `CLAUDE.md`, `architecture.md` (note only if material). No audit docs (N/A).

## 5) Lean refactor workstream
- The shipped `ollama`-container logic in install.sh §5c moves under the `ollama-docker` branch (behavioral parity preserved by the existing operator-path); the new `ollama` branch is the native path. Guardrail: `ollama-docker` must reproduce the shipped behavior exactly (sentinel, profile, `./data/ollama`, post-`up` restart).

## 6) Dependencies, risks, mitigations

| Risk | L/M/H | Mitigation |
|---|---|---|
| Linux loopback false-happy-path | M/H | FR-8 container-side reachability check + `OLLAMA_HOST=0.0.0.0` docs |
| Probe false-positive (non-Ollama 200) | M | grep `"models"` shape validation (AC-9, tested) |
| Existing `ollama` users silently lose LLM | M | upgrade note + unmistakable summary line (FR-8) |
| `host-gateway` on very old Docker → Compose parse fail | L | min-Docker doc + `ollama-docker`/`OPENAI_BASE_URL` fallback |

### Failure modes
| Mode | Trigger | Behavior | Recovery |
|---|---|---|---|
| native absent | `ollama`, no host Ollama | guidance + LLM-free, no container | install Ollama / `ollama-docker` / `OPENAI_BASE_URL` |
| native present, unreachable from container (Linux loopback) | `127.0.0.1`-bound Ollama | FR-8 warning post-`up` | `OLLAMA_HOST=0.0.0.0` |
| effective model missing | model not pulled | `ollama pull` warning, proceed | pull the model |

## 7) Sequencing
1. Story 1 (helper allowlist) → 2. Story 2 (native helper + tests) → 3. Story 3 (install.sh + compose) → 4. Story 4 (docs). Stories 1 & 2 are independent (parallelizable); Story 3 depends on 1+2; Story 4 last.

## 8) Rollout
Opt-in; no migration. **Behavior change** documented (upgrade note). README/docs same PR.

## 9) Execution tracker
- [ ] Story 1 — `relyloop_llm.sh` allowlist `{ollama, ollama-docker}` + test rework
- [ ] Story 2 — `relyloop_native_llm.sh` + `test_relyloop_native_llm.sh` + pr.yml
- [ ] Story 3 — install.sh native wiring + `extra_hosts` + FR-8 + compose-shape test
- [ ] Story 4 — docs + README doc test

## 10) Story-by-Story Verification Gate
- [ ] Files match story scope; helpers fail-fast before `docker compose`; model names env-driven.
- [ ] `make test-unit` + both bash tests + shellcheck pass; no CI network/model pull.
- [ ] Operator-path matrix recorded for native/absent/loopback/`ollama-docker`.
- [ ] README/docs in the same PR; upgrade note present.

## 11) Plan consistency review
- **FR coverage:** all 8 FRs mapped (§1); each ≥1 story. ✓
- **Endpoints/error codes:** spec has 0 → plan has 0. ✓
- **Test assignment:** compose-shape→S3, README doc→S4, `test_parse_relyloop_llm`→S1, `test_relyloop_native_llm`→S2. No orphans. ✓
- **File ownership:** `relyloop_llm.sh`→S1 only; `relyloop_native_llm.sh`→S2 only; `install.sh`+`docker-compose.yml`→S3 only; docs→S4 only. ✓
- **Codebase paths verified this session:** `scripts/lib/`, `scripts/ci/`, `scripts/install.sh` §5c, `docker-compose.yml` (no `extra_hosts`), `test_compose_deployment_shape.py`, `.github/workflows/pr.yml:375`. ✓
- **Open questions:** spec §19 none open. ✓
- **UI/migration/audit:** N/A (stated). ✓

## 12) Definition of plan done
- [x] Every FR → story + tests + docs.
- [x] Each story has Modified/New files, Tasks, DoD (Endpoints/Schemas N/A).
- [x] Test layers scoped (unit + bash; integration/contract/e2e N/A w/ reasons).
- [x] Refactor scope bounded (§5).
- [x] Consistency review (§11) clean.
