# Feature Specification — Native-first local LLM (use host Ollama; demote Docker bundle)

**Date:** 2026-06-19
**Status:** Draft
**Owners:** Eric Starr (Product), Opus (Engineering — spec author)
**Related docs:**
- [idea.md](idea.md) — the input brief
- Shipped baseline: [`feat_bundled_local_llm`](../../../implemented_features/2026_06_19_bundled_local_llm/feature_spec.md) (PR #573)
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md), [`deployment.md`](../../../01_architecture/deployment.md)

---

## 1) Purpose

- **Problem:** `RELYLOOP_LLM=ollama make up` (shipped in PR #573) starts a Dockerized Ollama that on Docker-for-Mac is CPU-only (no Metal passthrough) and impractically slow — a 256-token reply exceeded 10 min on a dev Mac. The genuinely fast local path, a host-native Ollama (Metal-accelerated), works today only via the manual Option C (`OPENAI_BASE_URL=http://host.docker.internal:11434/v1`).
- **Outcome:** Make `RELYLOOP_LLM=ollama` **native-first**: install.sh detects a host-native Ollama and auto-wires the app at it (Metal speed, one flag). The slow Docker container drops to an explicit `RELYLOOP_LLM=ollama-docker` escape hatch. When no native Ollama is found, print clear install guidance and bring the stack up LLM-free — never the slow container by default.
- **Non-goal:** Not auto-installing Ollama; not GPU-passthrough for the Docker container; not LM Studio auto-detection (LM Studio stays a documented Option-C endpoint); no new LLM provider abstraction.

## 2) Current state audit

### Existing implementations

- [`scripts/lib/relyloop_llm.sh`](../../../../scripts/lib/relyloop_llm.sh) — `parse_relyloop_llm`: allowlist currently `{ollama}`; `ollama` appends the `bundled-llm` Compose profile; FR-4 precedence (`OPENAI_BASE_URL` set → no profile) runs first + strips a pre-seeded token. **This feature changes the allowlist to `{ollama, ollama-docker}` and makes `ollama` NOT append a profile** (native path; detection moves to install.sh).
- [`scripts/install.sh`](../../../../scripts/install.sh) §5c — sources `relyloop_llm.sh`, and on the `bundled-llm` branch exports `OPENAI_BASE_URL=http://ollama:11434/v1`, defaults the model, writes the sentinel `openai_key`, pre-creates `./data/ollama`; the `else` branch clears a stale sentinel. **This feature adds a native-detection branch for `ollama`.**
- [`docker-compose.yml`](../../../../docker-compose.yml) — the `ollama` service (`profiles: ["bundled-llm"]`) is unchanged; it is now started only by `ollama-docker`. api/worker have **no** `extra_hosts` (verified — only comment references) → a Linux container can't resolve `host.docker.internal` to reach a host-native Ollama. **This feature adds `extra_hosts`.**
- The OpenAI-compatible env wiring (`OPENAI_BASE_URL`/`OPENAI_MODEL`/`OPENAI_MODEL_CHAT` `${VAR:-…}` on api+worker) and the capability check + sentinel-key handling are reused unchanged.

### Navigation and link impact

N/A — no UI/links.

### Existing test impact

| Test file | Pattern | Required change |
|---|---|---|
| [`scripts/ci/test_parse_relyloop_llm.sh`](../../../../scripts/ci/test_parse_relyloop_llm.sh) | helper allowlist cases | Update: `ollama` no longer appends `bundled-llm`; add `ollama-docker` → appends; unknown still errors; precedence unchanged. |
| [`backend/tests/unit/test_compose_deployment_shape.py`](../../../../backend/tests/unit/test_compose_deployment_shape.py) | `ollama` service shape | Add: api/worker carry `extra_hosts: host.docker.internal:host-gateway`. `ollama` service profile assertion unchanged. |
| [`backend/tests/unit/docs/test_readme_documents_bundled_llm.py`](../../../../backend/tests/unit/docs/test_readme_documents_bundled_llm.py) | README↔helper lockstep | Update assertions for the native-first wording + `ollama-docker`. |

### Existing behaviors affected by scope change

- **`RELYLOOP_LLM=ollama`:** Current → starts the slow Docker container. New → native-first (detect host Ollama; no container). **Decision: yes (this is the feature).**
- **The Docker container:** Current → started by `ollama`. New → started only by `ollama-docker`. Decision: yes.
- **`OPENAI_BASE_URL` precedence, sentinel key, capability recheck:** unchanged.

---

## 3) Scope

### In scope

- `relyloop_llm.sh` allowlist `{ollama, ollama-docker}`; `ollama` = native path (no profile), `ollama-docker` = bundled container (appends `bundled-llm`).
- install.sh native-Ollama detection for `ollama`: probe `http://localhost:11434/api/tags`; found → wire the app at `http://host.docker.internal:11434/v1` + model default + sentinel key; not found → actionable message + LLM-free stack (no container).
- Native model-presence check: if detected but the model isn't pulled, warn (`ollama pull <model>`) and proceed (capability check reports the degraded state).
- `extra_hosts: ["host.docker.internal:host-gateway"]` on api + worker (Linux reachability; harmless on Mac/Windows).
- Docs: README/`.env.example`/deployment/llm-orchestration/llm-endpoint-setup/tutorial updated for native-first + `ollama-docker`.
- Tests: bash helper rework, compose-shape `extra_hosts` assertion, README doc-test update.

### Out of scope

- LM Studio auto-detection (documented Option-C endpoint only — D-4).
- Auto-installing Ollama or auto-pulling on the host daemon by default (D-3 recommends instruct-and-degrade).
- GPU passthrough for the Docker `ollama` service.
- Removing the Docker `ollama` service (kept behind `ollama-docker` — D-5).

### API convention check

N/A — no HTTP endpoints added or changed.

### Phase boundaries

Single phase — the whole re-scope ships together. No deferred phases (so no `phaseN_idea.md`).

## 4) Product principles and constraints

- **Native-first, honestly.** The default `ollama` value delivers the fast (Metal) path or clearly tells the operator how to get it — it never silently falls back to the slow container.
- **Lightweight default preserved.** Bare `make up` (no `RELYLOOP_LLM`) is unchanged — no LLM.
- **No-op for existing Option C.** An explicit `OPENAI_BASE_URL` still wins for both `ollama` and `ollama-docker`.
- **Cross-platform honesty.** `host.docker.internal` needs `host-gateway` on Linux; the feature wires it. Where native detection can't work, the message points at `ollama-docker` / Option C.
- **Secrets rule (#2):** reuse the sentinel `openai_key`; no new secret.
- **Model-name rule (#8):** model names stay env-driven.
- **Hermetic CI:** no model pull in CI; native detection is host-only and not exercised in CI (the probe simply finds nothing).

### Anti-patterns

- **Do not** silently start the slow Docker container when native detection fails — print guidance and come up LLM-free instead.
- **Do not** put the host-network probe inside `relyloop_llm.sh` — the pure helper must stay host-network-agnostic + unit-testable; detection lives in install.sh.
- **Do not** auto-pull a model onto the operator's native daemon without asking (intrusive — instruct instead).
- **Do not** remove the `ollama` Compose service — it backs `ollama-docker`.

## 5) Assumptions and dependencies

- **Dependency:** a host-native Ollama the operator installs + runs (`ollama serve`, default `:11434`). Status: external/operator-provided. Risk if missing: `ollama` prints guidance + comes up LLM-free (handled).
- **Assumption:** install.sh runs on the host with `curl` available (verified on macOS) and the host Ollama listens on `localhost:11434` (Ollama default).
- **Assumption:** containers reach the host via `host.docker.internal` (native on Mac/Windows; via `host-gateway` on Linux, added here).

## 6) Actors and roles

- Primary actor: the operator running `make up`. Role model: N/A (single-tenant, no auth). Audit events: N/A (no app state mutation — install/Compose only).

## 7) Functional requirements

### FR-1: `RELYLOOP_LLM` allowlist + per-value behavior
- The helper **MUST** accept `{ollama, ollama-docker}`; unknown → exit 1 with the allowlist message (before any `docker compose` call).
- `ollama-docker` **MUST** append `bundled-llm` to `COMPOSE_PROFILES` (the shipped container path).
- `ollama` **MUST NOT** append any profile (native path; handled in install.sh).
- FR-4 precedence (`OPENAI_BASE_URL` non-empty → no-op + notice, strip a pre-seeded `bundled-llm`) **MUST** still run first for both values.

### FR-2: native-Ollama detection (the `ollama` value)
- The native-detect logic **MUST** live in a **sourceable, unit-testable function** (e.g. `scripts/lib/relyloop_native_llm.sh`) with the probe injectable (probe URL/command overridable) so CI can exercise it with a mocked `curl`/probe — NOT inline-only in install.sh (mirrors the helper-extraction pattern). See §14.
- When `RELYLOOP_LLM=ollama` and `OPENAI_BASE_URL` is unset, it **MUST** probe `http://localhost:11434/api/tags` (short timeout, e.g. `curl -fsS --max-time 2`) **and validate the response is Ollama-shaped** — it contains a `models` array (NS-2). A 200 from any other local service / proxy / malformed body **MUST** read as "not found" (no wiring, no sentinel write). **No new host dependency** (C2-NS-1): validate with `grep` for the `"models"` key, NOT `jq`/`python3` (not guaranteed on a clean host) — install.sh already uses `grep`/`curl` only.
- **Found (validated)** → export `OPENAI_BASE_URL=http://host.docker.internal:11434/v1`, default `OPENAI_MODEL`/`OPENAI_MODEL_CHAT` to `${OLLAMA_MODEL:-qwen3.5:4b}` (preserving operator-set values), write the sentinel `openai_key` (the shipped feature's FR-8) — and do **NOT** add `bundled-llm` / start the container.
- **Not found** → print an actionable message (install Ollama / `ollama serve` + `ollama pull` / or set `OPENAI_BASE_URL` / or `RELYLOOP_LLM=ollama-docker` for the slow CPU fallback) and bring the stack up LLM-free (`/healthz` `missing_key`). **MUST NOT** start the Docker container.

### FR-3: native model-presence check
- When a native Ollama is detected, install.sh **SHOULD** check whether the **effective** model(s) — the unique resolved values of `OPENAI_MODEL` + `OPENAI_MODEL_CHAT` after precedence/defaulting (NS-3), not merely `OLLAMA_MODEL` — appear in the `/api/tags` response, **normalizing the implicit `:latest` tag** (`foo` ≡ `foo:latest`). The check is a `grep` substring match against the probe response (no JSON parser, C2-NS-1). For each missing effective model it **MUST** print a warning naming the exact `ollama pull <model>` command, then proceed (the capability check reports the degraded state). It **MUST NOT** auto-pull onto the host daemon.

### FR-4: Linux reachability of the host Ollama
- api and worker **MUST** declare `extra_hosts: ["host.docker.internal:host-gateway"]` so a Linux container can resolve the host (no-op on Mac/Windows where it already resolves). Requires Docker Engine ≥ 20.10 / Compose v2 (`host-gateway` support) — documented as a minimum (NS-6); on older Docker, Compose would fail to parse, and the documented fallback is upgrade Docker, `RELYLOOP_LLM=ollama-docker`, or an explicit `OPENAI_BASE_URL`.
- **Linux loopback caveat (NS-1):** `host-gateway` resolves to the host's **bridge** address, NOT its loopback — so a native Ollama bound to the default `127.0.0.1:11434` is reachable by install.sh's host-side probe but **NOT** by the containers, a false happy path. The docs **MUST** instruct Linux operators to bind Ollama to a non-loopback interface (`OLLAMA_HOST=0.0.0.0:11434 ollama serve`), and FR-8 adds a container-side reachability check so this misconfig is caught, not silently broken. (On Docker Desktop / Mac / Windows, `host.docker.internal` reaches loopback-bound host services, so no change is needed there.)

### FR-8: post-`up` reachability verification + clear LLM-state messaging
- After `up --wait`, when the native path is active, install.sh **MUST** verify the app can actually reach the wired endpoint from **inside a container**. The check **MUST** use a tool guaranteed in the api image — the api image is Python-based, so use `docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=3)"` (NOT `curl`, which the slim image may lack, C2-NS-2). If the host-side probe found Ollama but the container can't reach it (the Linux-loopback trap), it **MUST** print a clear warning (bind `OLLAMA_HOST=0.0.0.0`, or use `ollama-docker` / `OPENAI_BASE_URL`) rather than leave `/healthz` silently `incapable`.
- install.sh **MUST** print an **unmistakable** summary line for the no-LLM outcome of `RELYLOOP_LLM=ollama` (NS-5): e.g. `RELYLOOP_LLM=ollama: no usable native Ollama — stack is up WITHOUT LLM features. For the old bundled-container behavior use RELYLOOP_LLM=ollama-docker.` — so operators/automation upgrading from the shipped behavior notice the change.

### FR-5: `OPENAI_BASE_URL` precedence (unchanged)
- An explicit `OPENAI_BASE_URL` **MUST** win for both `ollama` and `ollama-docker` — neither starts a container nor overrides the endpoint.

### FR-6: documentation
- README/guides **MUST** present `RELYLOOP_LLM=ollama` as "use your native (Metal-fast) Ollama" with the install-Ollama prerequisite, document `ollama-docker` as the slow zero-install CPU fallback, and keep Option C (arbitrary `OPENAI_BASE_URL`) for cloud/LM-Studio/remote. The README change **MUST** ship in the same PR as the code.

### FR-7: the bundled container is unchanged, now `ollama-docker`-only
- The `ollama` Compose service definition **MUST** be unchanged; it is started only when `ollama-docker` adds the `bundled-llm` profile.

## 8) API and data contract baseline

N/A — no endpoints, request/response shapes, or error codes added or changed. (`/healthz subsystems.openai` reflects the resolved endpoint, shape unchanged.)

## 9) Data model and state transitions

N/A — no tables, no migration.

## 10) Security, privacy, and compliance

- **Threats:** (1) The probe hitting an unexpected localhost service — mitigated: it checks Ollama's specific `/api/tags` shape with a short timeout, and a non-Ollama response just reads as "not found." (2) Reaching the host from a container (`host.docker.internal`) — this is the intended, operator-opted-in behavior; it exposes nothing new (the operator runs Ollama on their own host). **No data leaves the host** under native Ollama.
- **Controls:** native path is opt-in (`RELYLOOP_LLM=ollama`); no new secret (sentinel reused); no new CI egress.
- **Secrets:** unchanged.

## 11) UX flows and edge cases

### Primary flows
1. **Native present (the happy path):** operator has Ollama running → `RELYLOOP_LLM=ollama make up` → app wired at the Metal-fast host Ollama; chat/judge/digest work, fast.
2. **Native absent:** → clear message (install + run Ollama, or `ollama-docker`, or `OPENAI_BASE_URL`) → stack up, LLM-free.
3. **`ollama-docker`:** → the shipped slow CPU container (zero-install / Linux-GPU fallback).
4. **Option C:** `OPENAI_BASE_URL=…` → that endpoint; nothing bundled.

### Edge/error flows
- **Native present but model not pulled:** warn with the exact `ollama pull` command; stack up; capability check reports degraded until pulled (FR-3).
- **Linux without `host-gateway` support (very old Docker):** documented; fall back to `ollama-docker` or Option C.
- **Unknown `RELYLOOP_LLM`:** exit 1 + allowlist `{ollama, ollama-docker}`.

## 12) Given/When/Then acceptance criteria

### AC-1: `ollama` does not start a container
- Given `RELYLOOP_LLM=ollama` (no `OPENAI_BASE_URL`)
- When the helper resolves profiles
- Then `COMPOSE_PROFILES` does NOT contain `bundled-llm`.

### AC-2: `ollama-docker` starts the container
- Given `RELYLOOP_LLM=ollama-docker`
- When the helper resolves profiles
- Then `COMPOSE_PROFILES` contains `bundled-llm`.

### AC-3: native detected → wired at the host
- Given `RELYLOOP_LLM=ollama`, a host Ollama serving the model on `:11434`, `OPENAI_BASE_URL` unset
- When `make up` runs
- Then api/worker env `OPENAI_BASE_URL` = `http://host.docker.internal:11434/v1`, the sentinel key is written, no `ollama` container is started, and `/healthz` reaches `openai: configured`.

### AC-4: native absent → guidance + LLM-free, no container
- Given `RELYLOOP_LLM=ollama`, no host Ollama on `:11434`
- When `make up` runs
- Then install.sh prints the actionable message (naming `ollama-docker` and `OPENAI_BASE_URL`), no `ollama` container starts, and `/healthz` reports `openai: missing_key`.

### AC-5: native present but model missing → warn + proceed
- Given a host Ollama running but without `qwen3.5:4b`
- When `make up` runs with `RELYLOOP_LLM=ollama`
- Then install.sh prints the exact `ollama pull qwen3.5:4b` command and the stack still comes up (no auto-pull).

### AC-6: precedence unchanged
- Given `OPENAI_BASE_URL` set and `RELYLOOP_LLM=ollama` (or `ollama-docker`)
- When the helper runs
- Then no profile is added, no container starts, and the operator's endpoint is used.

### AC-7: `extra_hosts` present
- Given the Compose file
- Then api and worker declare `extra_hosts: ["host.docker.internal:host-gateway"]`.

### AC-8: unknown value fails fast
- Given `RELYLOOP_LLM=vllm` (no `OPENAI_BASE_URL`)
- Then install.sh exits non-zero naming the allowlist `ollama, ollama-docker`.

### AC-9: non-Ollama 200 reads as not-found (shape validation)
- Given `RELYLOOP_LLM=ollama` and a localhost:11434 that returns HTTP 200 but not an Ollama `models` array (other service / malformed JSON)
- When the native-detect function runs (mocked probe in CI)
- Then it treats it as not-found: no `OPENAI_BASE_URL` wired, no sentinel written, guidance printed.

### AC-10: Linux-loopback misconfig is caught post-up (FR-8)
- Given the host-side probe found Ollama but a container cannot reach `host.docker.internal:11434` (Ollama bound to loopback on Linux)
- When install.sh runs the post-`up` container-side reachability check
- Then it prints the bind-`OLLAMA_HOST=0.0.0.0` / `ollama-docker` / `OPENAI_BASE_URL` warning (not a silent `incapable`).

## 13) Non-functional requirements

- **Performance:** native Ollama is Metal-accelerated (fast); the whole point. The probe adds ≤2s to `make up` when `ollama` is selected.
- **Reliability:** native-detect failure never blocks the stack (comes up LLM-free).
- **Operability:** clear, copy-pasteable guidance on the not-found / model-missing paths.

## 14) Test strategy requirements

- **Bash unit (`test_parse_relyloop_llm.sh`):** rework — `ollama` → no `bundled-llm`; `ollama-docker` → `bundled-llm`; unknown → exit 1 (allowlist names both); precedence unchanged (strip on `OPENAI_BASE_URL` set).
- **Bash unit (NEW `test_relyloop_native_llm.sh`, NS-4):** exercise the native-detect function with an **injectable mocked probe** (no real network): native-present-and-Ollama-shaped → wires `host.docker.internal` + writes sentinel + no profile; HTTP-200-but-not-Ollama-shaped (no `models` array / malformed JSON) → treated as not-found, no sentinel; native-absent → guidance + no sentinel + no profile; explicit `OPENAI_BASE_URL` → probe skipped entirely (both `ollama` and `ollama-docker`); effective-model-missing (incl. `:latest` normalization) → prints the exact `ollama pull` command. Wired into `pr.yml`.
- **Unit (`test_compose_deployment_shape.py`):** assert api + worker carry `extra_hosts: host.docker.internal:host-gateway`; `ollama` service profile unchanged.
- **Doc (`test_readme_documents_bundled_llm.py`):** update for native-first wording + `ollama-docker`.
- **Operator-path (out-of-CI, maintainer):** native-present (wired + `configured` + the FR-8 container-side reachability check passes), native-absent (guidance + `missing_key`), Linux-loopback misconfig (FR-8 warning fires), `ollama-docker` (container path) — release-checklist. CI stays hermetic (the host probe finds nothing → behaves as native-absent; the mocked-probe bash test covers the found path).

## 15) Documentation update requirements

- `README.md` (native-first 3-option block), `.env.example`, `docs/01_architecture/llm-orchestration.md` + `deployment.md`, `docs/08_guides/llm-endpoint-setup.md` + tutorial Step 0, `docs/03_runbooks/release-checklist.md` (native-present/absent/`ollama-docker` gate), `CLAUDE.md` (`RELYLOOP_LLM` values).

## 16) Rollout and migration readiness

- No migration. Opt-in by construction. README/docs same PR. **Behavior change for existing `ollama` users (NS-5):** `RELYLOOP_LLM=ollama` now prefers a native Ollama and **no longer auto-starts the slow Docker container** — so a stack that previously got the bundled CPU LLM now comes up LLM-free if no native Ollama is present. This MUST be called out as a prominent **upgrade/release note**, install.sh MUST print the unmistakable summary line (FR-8), and `RELYLOOP_LLM=ollama-docker` preserves the old behavior. Release gate: `pr.yml` green (bash helper + native-detect + compose-shape tests) + the operator-path matrix recorded.

## 17) Traceability matrix

| FR | AC | Tests | Docs |
|---|---|---|---|
| FR-1 | AC-1, AC-2, AC-8 | `test_parse_relyloop_llm.sh` | CLAUDE.md |
| FR-2 | AC-3, AC-4 | operator-path | README, endpoint-setup |
| FR-3 | AC-5 | operator-path | endpoint-setup |
| FR-4 | AC-7 | `test_compose_deployment_shape.py` | deployment.md |
| FR-5 | AC-6 | `test_parse_relyloop_llm.sh` | README |
| FR-6 | AC-3..AC-5 | README doc test | README, guides |
| FR-7 | AC-2 | compose-shape | deployment.md |
| FR-8 | AC-10 | `test_relyloop_native_llm.sh` (messaging) + operator-path (reachability) | README, deployment.md, release-checklist |
| FR-2 shape-validation | AC-9 | `test_relyloop_native_llm.sh` | — |

## 18) Definition of feature done

- [ ] CI-verifiable ACs pass (`pr.yml`): AC-1, AC-2, AC-6, AC-8 (`test_parse_relyloop_llm.sh`); AC-9 + the FR-2 shape-validation / FR-3 model-warning / FR-8 messaging paths (`test_relyloop_native_llm.sh`, mocked probe); AC-7 (`test_compose_deployment_shape.py`).
- [ ] Maintainer/operator-path (out-of-CI, real Docker): AC-3, AC-4, AC-5, **AC-10 (Linux-loopback reachability warning)** + `ollama-docker` recorded in the release checklist.
- [ ] README documents native-first + `ollama-docker` (same PR); guides + CLAUDE.md updated.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions
- None blocking (D-1..D-5 resolved below).

### Decision log
- 2026-06-19 — **Native-first** (operator): `RELYLOOP_LLM=ollama` detects + uses host Ollama; Docker container demoted to `ollama-docker`.
- 2026-06-19 — **D-1 Linux reachability:** add `extra_hosts: host.docker.internal:host-gateway` to api+worker (vs. document-only). Chosen: wire it (harmless on Mac).
- 2026-06-19 — **D-2 not-found UX:** warn + proceed LLM-free (never the slow container, never hard-error).
- 2026-06-19 — **D-3 model-presence:** instruct-and-degrade (print `ollama pull`), never auto-pull on the host daemon.
- 2026-06-19 — **D-4 LM Studio:** out of scope for the `ollama` value; documented via Option C.
- 2026-06-19 — **D-5 keep the container:** keep behind `ollama-docker` (zero-install + Linux-GPU), don't remove.
- 2026-06-19 — **GPT-5.5 cross-model review (1 cycle, 6 findings, all accepted).** NS-1 (High): the Linux loopback trap — a host Ollama on `127.0.0.1` passes install.sh's host-side probe but is unreachable from containers via `host-gateway` → FR-4 documents the `OLLAMA_HOST=0.0.0.0` requirement + FR-8 adds a post-`up` container-side reachability check. NS-2: FR-2 now validates the probe response is Ollama-shaped (`models` array), not just HTTP 200. NS-3: FR-3 checks the *effective* `OPENAI_MODEL`/`_CHAT` set with `:latest` normalization. NS-4: native-detect extracted to a sourceable, mocked-probe-testable function (`relyloop_native_llm.sh`) with a new `test_relyloop_native_llm.sh` in CI. NS-5: prominent upgrade note + unmistakable post-`up` summary line (FR-8). NS-6: min Docker (≥20.10 / Compose v2) documented for `host-gateway`.
