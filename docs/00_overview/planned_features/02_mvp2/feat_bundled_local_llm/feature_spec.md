# Feature Specification — Bundled local LLM (one-flag opt-in)

**Date:** 2026-06-19
**Status:** Draft
**Owners:** Eric Starr (Product), Opus (Engineering — spec author)
**Related docs:**
- [idea.md](idea.md) — the input brief
- [implementation_plan.md](implementation_plan.md) — generated next
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)
- [`docs/01_architecture/deployment.md`](../../../01_architecture/deployment.md)

---

## 1) Purpose

- **Problem:** After `make up`, the search stack is fully operational but every LLM-dependent feature (chat agent, LLM-as-judge, digest narrative) is dark — `OPENAI_BASE_URL` defaults to `https://api.openai.com/v1` with an empty `openai_key`, so `/healthz` reports `openai: missing_key` and those features refuse. A brand-new evaluator must find an OpenAI key or stand up their own LLM before the headline "conversational agent" does anything.
- **Outcome:** A **one-flag** path — `RELYLOOP_LLM=ollama make up` — brings up a self-contained, OpenAI-compatible local LLM (Ollama serving `qwen3.5:4b`) so chat/judge/digest work immediately with no external key, while the **basic default stays LLM-free and lightweight** (nothing extra to download, lowest RAM). Setting `OPENAI_BASE_URL` to your own endpoint bypasses the bundled container entirely.
- **Non-goal:** Not a performance recommendation, not a production inference deployment, not a new LLM provider abstraction. The bundled model is CPU-only on macOS (see §4) and exists so the whole product is demonstrable from one command.

## 2) Current state audit

### Existing implementations

- [`docker-compose.yml:160-163`](../../../../docker-compose.yml) — `api` service env: `OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://api.openai.com/v1}`, `OPENAI_API_KEY_FILE: /run/secrets/openai_key`, `OPENAI_MODEL: ${OPENAI_MODEL:-gpt-4o-2024-08-06}`, `OPENAI_MODEL_CHAT: ${OPENAI_MODEL_CHAT:-gpt-4o-mini-2024-07-18}`. The `${VAR:-default}` form means a shell/`.env` value wins. **This is the seam the feature wires into** — no app code change needed.
- [`docker-compose.yml:257-260`](../../../../docker-compose.yml) — `worker` service: identical OPENAI_* env block.
- [`docker-compose.yml:172`](../../../../docker-compose.yml) — `COMPOSE_PROFILES: ${COMPOSE_PROFILES:-es,os,solr}` is passed into the `api` container env (consumed by the seeder to know which engines are active).
- [`docker-compose.yml:346,379,420`](../../../../docker-compose.yml) — `elasticsearch`/`opensearch`/`solr` services each carry `profiles: ["es"|"os"|"solr"]`. **The bundled LLM mirrors this with `profiles: ["bundled-llm"]`.**
- [`docker-compose.yml:443-444`](../../../../docker-compose.yml) — `openai_key` Docker secret (`file: ./secrets/openai_key`), created empty by install.sh.
- [`scripts/install.sh`](../../../../scripts/install.sh) — §0 sources `RELYLOOP_*` from `.env` ([relyloop_env_file.sh](../../../../scripts/lib/relyloop_env_file.sh)); §5 runs `parse_relyloop_engines` ([relyloop_engines.sh](../../../../scripts/lib/relyloop_engines.sh)) → `COMPOSE_PROFILES`; §5b runs `parse_relyloop_engine_versions`; §8 `docker compose up -d --wait`; §9 auto-seeds `--if-empty`. **The feature adds a `parse_relyloop_llm` step alongside §5.**
- [`scripts/lib/relyloop_engines.sh`](../../../../scripts/lib/relyloop_engines.sh) + [`scripts/ci/test_parse_relyloop_engines.sh`](../../../../scripts/ci/test_parse_relyloop_engines.sh) — the canonical "validate an env var allowlist → append to `COMPOSE_PROFILES`, unit-tested in isolation" pattern the new `RELYLOOP_LLM` helper mirrors.
- [`backend/app/core/settings.py:123-135`](../../../../backend/app/core/settings.py) — `openai_base_url` / `openai_model` / `openai_model_chat` `Field(default=...)`. App reads these from env; **no change needed** (Absolute Rule #8 honored — names stay env-driven).
- [`backend/app/llm/capability_check.py`](../../../../backend/app/llm/capability_check.py) + [`capability_models.py`](../../../../backend/app/llm/capability_models.py) — FR-7 startup capability probe (`models_endpoint`, `function_calling`, `structured_output`), cached in Redis under `openai:capabilities:{sha256(base_url)}` with a **24h TTL** ([capability_check.py:48](../../../../backend/app/llm/capability_check.py)). **Two consequences this feature must handle:** (a) the probe **requires a non-empty `api_key`** — [capability_check.py:310](../../../../backend/app/llm/capability_check.py) docstring: "caller MUST pre-check it is non-empty"; an empty key returns `missing_key` WITHOUT probing, so Option B with the default empty `openai_key` would stay dark even with Ollama healthy (→ FR-8). (b) the result is cached 24h including failures, so an api startup probe that runs before Ollama finishes pulling would cache a fail for 24h (→ FR-3 recheck).
- [`scripts/lib/relyloop_env_file.sh:37`](../../../../scripts/lib/relyloop_env_file.sh) — `load_relyloop_env_file` extracts **only** `RELYLOOP_ENGINES RELYLOOP_ES_VERSION RELYLOOP_OS_VERSION RELYLOOP_SOLR_VERSION` from `.env`. `OPENAI_BASE_URL` / `OLLAMA_MODEL` / `RELYLOOP_LLM` set in `.env` are therefore NOT visible to install.sh's bash logic today (→ FR-1 extends this list). Note: Compose itself separately reads `.env` for `${VAR:-…}` substitution, but install.sh's *gating decision* runs in bash and needs the values too.
- [`backend/app/api/health.py:16`](../../../../backend/app/api/health.py) — `subsystems.openai` ∈ `configured | missing_key | incapable`. Option B flips this from `missing_key` to `configured` once the model is ready.
- [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) — `_openai_available()` gates the LLM-dependent demo scenario; under Option B it sees a configured endpoint and exercises the local model.

### Navigation and link impact

N/A — no UI routes or links change. This is an install/Compose feature.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`backend/tests/unit/test_compose_deployment_shape.py`](../../../../backend/tests/unit/test_compose_deployment_shape.py) | asserts Compose service/secret shape | TBD | Extend (don't break) to allow the new `ollama` service + `bundled-llm` profile; assert it is profile-gated (absent from the default `up`). |
| [`scripts/ci/test_parse_relyloop_engines.sh`](../../../../scripts/ci/test_parse_relyloop_engines.sh) | bash helper test pattern | — | Mirror as `scripts/ci/test_parse_relyloop_llm.sh`. |

### Existing behaviors affected by scope change

- **`make up` default:** Current: starts all three engines + auto-seeds; OpenAI `missing_key`. New: **unchanged** — still no LLM container. Decision needed: no (explicitly preserving the lightweight default is the point).
- **`OPENAI_BASE_URL` override:** Current: app uses the operator's endpoint. New: **unchanged**, plus install.sh now skips launching the bundled container when it's set. Decision needed: no.
- **Auto-seed under Option B:** Current: LLM demo scenario skipped when `missing_key`. New: with the bundled LLM configured, the LLM-dependent demo step runs against the local model (slower, CPU-only). The auto-seed is already non-fatal and tolerates LLM-step failures, so this is safe. Decision needed: no.

---

## 3) Scope

### In scope (Phase 1)

- New install-time var `RELYLOOP_LLM` (allowlist `ollama`) → appends `bundled-llm` to `COMPOSE_PROFILES`.
- New `ollama` Compose service behind `profiles: ["bundled-llm"]` serving `qwen3.5:4b`, with model pull + a healthcheck that only goes healthy once the model is served (so `docker compose up --wait` blocks until the LLM is usable).
- install.sh auto-wires `OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_MODEL_CHAT` to the bundled container **only** when Option B is active and the operator has not set `OPENAI_BASE_URL`.
- Precedence: an explicit `OPENAI_BASE_URL` always wins and the bundled container never launches (skip-with-notice).
- `OLLAMA_MODEL` `.env` knob for one-line model swap.
- README documents the three startup options (A/B/C) side-by-side; `docs/08_guides/llm-endpoint-setup.md` + tutorial Step 0 updated.
- Bash unit tests for the helper; Compose-shape test extension; doc updates.

### Out of scope

- **Host-native runtime auto-detection (Metal fast-path)** — deferred to Phase 2 ([phase2_idea.md](phase2_idea.md)).
- GPU passthrough / non-macOS acceleration tuning.
- A new `BaseChatModel` multi-provider abstraction (backlog).
- Bundling LM Studio or HuggingFace TGI (rejected — see idea.md "Runtime selection"; LM Studio needs a display server, TGI is not Apple-Silicon compatible).
- Changing the default model for the cloud path or any app-layer LLM code.

### API convention check

N/A — this feature adds **no HTTP endpoints**. It touches Compose, `install.sh`, `scripts/lib/`, secrets/`.env` conventions, and docs only. The existing `/healthz` `subsystems.openai` field reflects the outcome but is not modified.

### Phase boundaries

- **Phase 1 (this spec):** Options A/B/C, the `ollama` service, `RELYLOOP_LLM` gating, auto-wiring, model swap, README + guide docs, tests. Rationale: delivers the user's full request (lightweight default + one-flag opt-in + override-bypass) end-to-end.
- **Phase 2 (deferred):** host-native runtime detection (D-5) — if a native Ollama (`:11434`) or LM Studio (`:1234`) is already listening, prefer it (Metal speed) over the bundled CPU-only container. Rationale: independent enhancement, needs host-port probing + a precedence decision; not required for the core opt-in. Tracked in [phase2_idea.md](phase2_idea.md).

## 4) Product principles and constraints

- **Lightweight default is sacred.** The bare `make up` must add zero LLM footprint — no image pull, no process, no RAM. (Operator decision, 2026-06-19.)
- **One obvious flag** turns on a *working* LLM, not a half-configured one: model present and served before `make up` returns.
- **Honest health.** With no LLM configured, `/healthz` must keep reporting `openai: missing_key` — never fake "configured."
- **Secrets rule (Absolute #2):** Ollama needs no API key; the empty `openai_key` placeholder stays. No new secret files.
- **Model-name rule (Absolute #8):** model names stay env-driven via `Settings` / Compose `${OPENAI_MODEL:-…}`; install.sh sets env defaults, never hardcodes into service code.
- **Hermetic CI (Common Pitfalls):** CI must not pull a multi-GB model. The `bundled-llm` profile is opt-in, so default CI `up`/build never touches Ollama; any test that needs the service is gated/skipped, not run against a real model pull.
- **Docker-on-macOS is CPU-only.** Docker Desktop has no Metal/GPU passthrough, so the bundled model runs CPU-only regardless of the Mac's GPU. This forces a small model (`qwen3.5:4b`) and modest speed — documented plainly, never implied to be fast.

### Anti-patterns

- **Do not** make the bundled LLM default-on — it violates the explicit lightweight-default decision and forces a multi-GB pull on every `make up`.
- **Do not** add a hard `depends_on: ollama` to `api`/`worker` — a `depends_on` targeting a profile-gated service breaks the default (non-LLM) `up`. The capability check is already async + Redis-cached ([Absolute Rule #11](../../../../CLAUDE.md)); let it reflect readiness, don't block the app on the LLM.
- **Do not** launch the bundled container when `OPENAI_BASE_URL` is set — the operator clearly has an endpoint.
- **Do not** hardcode `qwen3.5:4b` in Python/service code — it's an install/Compose default (`OLLAMA_MODEL`, `OPENAI_MODEL`), overridable in `.env`.
- **Do not** require network egress in CI for this feature — keep the model pull strictly inside the opt-in profile.
- **Do not** add a new Docker secret for Ollama — it has no auth.

## 5) Assumptions and dependencies

- **Dependency:** Ollama official image (`ollama/ollama`, MIT). Why: container-native, headless, OpenAI-compatible `/v1`, trivial model pull. Status: external, stable. Risk if missing: Option B unavailable; Options A/C unaffected.
- **Dependency:** `qwen3.5:4b` present in Ollama's library. Why: default bundled model. Status: confirmed in Ollama's official library (`qwen3.5:2b/4b/9b`, Apache 2.0). Risk: if a tag is unavailable, `OLLAMA_MODEL` overrides it; Qwen3 small instruct is the conservative fallback.
- **Dependency:** `BASE_REGISTRY` corp-proxy convention already in Compose for image pulls; the `ollama/ollama` image reference uses the same `${BASE_REGISTRY:-}` prefix as the engine images. Risk: corp networks blocking the model registry (`registry.ollama.ai`) — documented as a known first-run-pull caveat.
- **Assumption:** first-run model pull (~2–3 GB) happens during `RELYLOOP_LLM=ollama make up` and is cached in a volume for subsequent runs.

## 6) Actors and roles

- Primary actor: the operator running `make up` on a laptop/dev host.
- Role model: N/A — single-tenant install, no auth surface.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — this feature performs no application state mutation (no DB writes, no service endpoints). It is install/Compose orchestration only. (The MVP2 `audit_log` applies to state-mutating app endpoints, of which this feature adds none.)

## 7) Functional requirements

### FR-1: `RELYLOOP_LLM` opt-in selector
- The system **MUST** add a `parse_relyloop_llm` step in `install.sh` (alongside `parse_relyloop_engines`) that reads `RELYLOOP_LLM` from shell/`.env`, validates it against the allowlist `{ollama}`, and **appends** `bundled-llm` to `COMPOSE_PROFILES` when set to `ollama`.
- The system **MUST** default to **unset → no `bundled-llm` profile** (lightweight default; no LLM container).
- The system **MUST** exit non-zero with a clear stderr message for any unknown `RELYLOOP_LLM` value, **before** any `docker compose pull`/`up` (mirroring `parse_relyloop_engines`).
- The helper **MUST** live in `scripts/lib/relyloop_llm.sh` and be unit-testable in isolation (sourced by both install.sh and a `scripts/ci/test_parse_relyloop_llm.sh`).
- The system **MUST** extend `load_relyloop_env_file` ([relyloop_env_file.sh:37](../../../../scripts/lib/relyloop_env_file.sh)) to also selectively extract `RELYLOOP_LLM`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_MODEL_CHAT`, and `OLLAMA_MODEL` by name from `.env` (shell env still wins), so install.sh's gating + precedence logic sees `.env`-only values. Extraction stays by-name (never blind-sources `.env`, preserving the `?`/`#` tolerance the loader was built for).
- Notes: append (not overwrite) `COMPOSE_PROFILES` so engine selection composes with LLM selection (e.g. `RELYLOOP_ENGINES=solr RELYLOOP_LLM=ollama` → `COMPOSE_PROFILES=solr,bundled-llm`).

### FR-2: bundled `ollama` Compose service
- The system **MUST** define an `ollama` service in `docker-compose.yml` with `profiles: ["bundled-llm"]`, using `image: ${BASE_REGISTRY:-}ollama/ollama:${OLLAMA_IMAGE_TAG:-<pinned>}` where `<pinned>` is an explicit, non-`latest` Ollama version chosen at implementation time from the then-current release (mirroring the engines' pinned-tag convention). The compose-shape test **MUST** assert the reference is pinned (not `latest`).
- The service **MUST** serve `${OLLAMA_MODEL:-qwen3.5:4b}` on the OpenAI-compatible endpoint (`http://ollama:11434/v1` on the Compose network).
- The service **MUST** pull the model on first start and **persist it** in a named volume / `./data/ollama` bind so subsequent runs don't re-pull.
- The service **MUST** define a healthcheck that reports healthy only once the model is actually present and served — verified with a tool guaranteed in the `ollama/ollama` image (e.g. `ollama show "$OLLAMA_MODEL"` / `ollama list`, NOT `curl`, which may be absent) — so `docker compose up -d --wait` (install.sh §8) blocks until the LLM is usable. The pull-then-serve mechanism (service entrypoint that runs `ollama serve` and `ollama pull "$OLLAMA_MODEL"`, or a one-shot `ollama-pull` init service also gated by `bundled-llm`) is chosen in the plan; either way the readiness gate is this healthcheck.
- The healthcheck **MUST** carry a **readiness budget generous enough to tolerate a multi-GB first-run pull** (large `start_period` + retries — the engine services' healthcheck budgets are the precedent), so `up --wait` does not false-fail on a slow-but-healthy network while `qwen3.5:4b` downloads. The budget must not be so tight that the model can't finish pulling before retries exhaust.
- The system **MUST NOT** add `depends_on: ollama` to `api`/`worker` (see Anti-patterns — it breaks the default non-LLM `up`).

### FR-3: auto-wire the app endpoint under Option B
- When the `bundled-llm` profile is active **and** the operator has not set `OPENAI_BASE_URL`, install.sh **MUST** export `OPENAI_BASE_URL=http://ollama:11434/v1` (consumed by the api/worker `${OPENAI_BASE_URL:-…}` env) before `docker compose up`.
- It **MUST** likewise default `OPENAI_MODEL` and `OPENAI_MODEL_CHAT` to `${OLLAMA_MODEL:-qwen3.5:4b}` for the bundled path (so judgments/digest + chat both use the local model), unless the operator set those explicitly.
- After `docker compose up -d --wait` returns (ollama healthy = model served), install.sh **MUST** ensure the capability check reflects the now-ready endpoint rather than a stale pre-ready failure cached for 24h — e.g. by restarting `api`+`worker` (re-runs the startup probe against the ready endpoint) or invalidating the Redis capability cache key. Outcome required: under Option B, `/healthz` reaches `openai: configured` without a 24h stale-`incapable` window. Verified in clean-room (FR-7/§16).
- Notes: this keeps app code untouched — only the env the Compose `${VAR:-…}` reads is set, plus the post-`--wait` recheck.

### FR-4: `OPENAI_BASE_URL` precedence (override bypasses the bundle)
- If `OPENAI_BASE_URL` is set (non-empty), the system **MUST NOT** add the `bundled-llm` profile or launch the `ollama` service — even if `RELYLOOP_LLM=ollama` is also set.
- In that contradiction case, install.sh **MUST** print a one-line notice that the bundled LLM was skipped because `OPENAI_BASE_URL` is set (skip-with-notice, not hard-error).
- Notes: matches the tolerant posture of the engines helper.

### FR-5: model swap
- The system **MUST** honor `OLLAMA_MODEL` from `.env`/shell as the bundled model tag (default `qwen3.5:4b`), flowing to both the `ollama` service's pulled model and the app's `OPENAI_MODEL`/`OPENAI_MODEL_CHAT` defaults under Option B.
- Notes: any Ollama tag is accepted; no allowlist (unlike `RELYLOOP_LLM`) — the operator owns model choice.

### FR-6: documentation of the three options
- README **MUST** document, side-by-side, Option A (no LLM, default), Option B (`RELYLOOP_LLM=ollama make up` → bundled `qwen3.5:4b`), and Option C (`OPENAI_BASE_URL` → BYO endpoint, bundle skipped), including the CPU-only-macOS caveat and the first-run pull size.
- The README change **MUST** ship in the **same PR** as the implementation (never ahead of a working command).
- `docs/08_guides/llm-endpoint-setup.md` and the tutorial's Step 0 **MUST** be updated to fold in the bundled opt-in.

### FR-7: lightweight default preserved
- With neither `RELYLOOP_LLM` nor `OPENAI_BASE_URL` set, `make up` **MUST** start no LLM container and `/healthz` **MUST** continue to report `subsystems.openai: missing_key`.
- CI default `up`/build **MUST NOT** pull the Ollama image or any model.

### FR-8: sentinel API key under Option B (and clean revert)
- Because the capability check ([capability_check.py:310](../../../../backend/app/llm/capability_check.py)) and the `openai` SDK both refuse to operate with an empty `api_key`, when Option B is active install.sh **MUST** ensure `./secrets/openai_key` contains a known **sentinel** value (the literal `ollama` — Ollama ignores it) so the SDK constructs and the capability check probes the local endpoint. It **MUST** write the sentinel only when the file is empty OR already equals the sentinel (never overwrite a real key).
- **Clean revert (FR-7 protection):** when Option B is NOT active and `OPENAI_BASE_URL` is unset (reverting to Option A), install.sh **MUST** clear `./secrets/openai_key` back to empty **iff its content equals the sentinel** — so a stale sentinel doesn't get sent to the default `https://api.openai.com/v1`, which would yield `incapable`/auth-failure instead of the honest `missing_key`. A real (non-sentinel) key is never touched.
- The README/guide **MUST** document both transitions: Option B→C (real cloud) requires setting a real key; the sentinel is auto-managed for B↔A.
- Notes: standard "openai SDK against a keyless local endpoint" pattern; the sentinel makes it idempotent and reversible. No new secret file — the existing `openai_key` mount ([docker-compose.yml:443](../../../../docker-compose.yml)) is reused.

## 8) API and data contract baseline

N/A — no HTTP endpoints, request/response shapes, or error codes are added or changed. The only observable API surface is the existing `/healthz` `subsystems.openai` value, which is unchanged in shape (`configured | missing_key | incapable`, [health.py:16](../../../../backend/app/api/health.py)) and merely reflects the configured endpoint.

## 9) Data model and state transitions

N/A — no new or modified tables, no migration. The feature touches Compose, install.sh, `.env`, and docs only.

## 10) Security, privacy, and compliance

- **Threats:** (1) A bundled LLM silently exfiltrating data — mitigated: Ollama is fully local, no telemetry to external services; under Option B no data leaves the host. (2) Model-pull egress in a hermetic/corp network — **two distinct paths must not be conflated**: `BASE_REGISTRY` proxies the **Docker image** pull (`ollama/ollama`), but the first-run `ollama pull qwen3.5:4b` is a **separate** download from Ollama's **model registry** (`registry.ollama.ai` / `ollama.com`) that `BASE_REGISTRY` does NOT proxy. Mitigation: document the required model-registry egress host, an offline/pre-seed path, and Option C (BYO endpoint) as the supported corporate-network fallback — do NOT claim `BASE_REGISTRY` mitigates the model pull. (3) Accidentally exposing the LLM port — mitigation: bind only on the Compose network (no host port mapping required; if one is added, bind `127.0.0.1` like the engines).
- **Controls:** profile-gating ensures the service only exists when explicitly opted in; no new egress in the default/CI path.
- **Secrets/key handling:** no new secret *file*. Under Option B install.sh writes a non-secret placeholder value into the existing `openai_key` mount (FR-8); Ollama ignores it. No real credential is involved.
- **Auditability:** N/A (no app mutation).
- **Data retention:** the model cache volume persists model weights only (no user data).

## 11) UX flows and edge cases

### Information architecture

N/A (no web UI). The "UX" surface is the CLI + README.

### Tooltips and contextual help

N/A (no UI elements).

### Primary flows
1. **Option A (default):** `make up` → search works, LLM features show `missing_key`. Nothing to do.
2. **Option B (opt-in):** `RELYLOOP_LLM=ollama make up` → first run pulls `qwen3.5:4b` (~2–3 GB), ollama healthcheck gates `--wait`, app auto-points at it; chat/judge/digest work.
3. **Option C (BYO):** set `OPENAI_BASE_URL` in `.env` → `make up` uses that endpoint, bundled container never launches.

### Edge/error flows
- **Both `RELYLOOP_LLM=ollama` and `OPENAI_BASE_URL` set:** skip-with-notice (FR-4); endpoint wins.
- **Unknown `RELYLOOP_LLM` value:** install.sh exits 1 with an allowlist message before any pull (FR-1).
- **Model pull fails (no egress / corp model-registry block):** `docker compose up --wait` surfaces the ollama healthcheck failure; install.sh's existing build/up error path applies; documented in the corp-network runbook (model-registry egress, not just image registry). The operator can retry or use Option C.
- **Slow first run / low RAM (Option B on a 16 GB host):** the first `RELYLOOP_LLM=ollama make up` pulls ~2–3 GB and then the auto-seed's LLM-dependent demo step runs against the CPU-only model — this can feel slow/"hung" after Compose readiness. Document this; seed LLM calls must keep bounded timeouts; and surface the existing `RELYLOOP_SKIP_AUTO_SEED=1` escape ([install.sh §9](../../../../scripts/install.sh)) plus `OLLAMA_MODEL=qwen3.5:2b` as the lighter swap.

## 12) Given/When/Then acceptance criteria

### AC-1: lightweight default starts no LLM
- Given a fresh clone with no `RELYLOOP_LLM` and no `OPENAI_BASE_URL`
- When `make up` runs
- Then no `ollama` container is created, and `/healthz` reports `subsystems.openai: missing_key`.
- Example: `docker compose ps --services` does not include `ollama`.

### AC-2: `RELYLOOP_LLM=ollama` enables the profile
- Given `RELYLOOP_LLM=ollama` (shell or `.env`)
- When `install.sh` resolves profiles
- Then `COMPOSE_PROFILES` contains `bundled-llm`, and (with engines) composes, e.g. `RELYLOOP_ENGINES=solr RELYLOOP_LLM=ollama` → profiles include both `solr` and `bundled-llm`.

### AC-3: Option B auto-wires the endpoint + model + placeholder key, reaches configured
- Given `RELYLOOP_LLM=ollama` and unset `OPENAI_BASE_URL` and an empty `openai_key`
- When the stack comes up
- Then the api/worker env `OPENAI_BASE_URL` = `http://ollama:11434/v1` and `OPENAI_MODEL`/`OPENAI_MODEL_CHAT` = `qwen3.5:4b`; `./secrets/openai_key` holds a non-empty placeholder (FR-8); and after the post-`--wait` recheck (FR-3) `/healthz` reports `openai: configured` (not a stale `incapable`/`missing_key`).

### AC-4: `OPENAI_BASE_URL` bypasses the bundle
- Given both `OPENAI_BASE_URL=https://api.openai.com/v1` and `RELYLOOP_LLM=ollama`
- When `install.sh` resolves profiles
- Then `bundled-llm` is NOT added, the `ollama` service is not started, and a skip notice is printed.

### AC-5: unknown selector fails fast
- Given `RELYLOOP_LLM=vllm`
- When `install.sh` runs
- Then it exits non-zero with a message naming the allowlist (`ollama`), before any `docker compose pull`/`up`.
- Example: stderr contains `Unknown` and `ollama`; exit code ≠ 0.

### AC-6: model swap
- Given `RELYLOOP_LLM=ollama` and `OLLAMA_MODEL=qwen3.5:2b`
- When the stack comes up
- Then the ollama service serves `qwen3.5:2b` and the app's `OPENAI_MODEL` defaults to `qwen3.5:2b`.

### AC-7: README documents all three options
- Given the merged PR
- When a reader opens `README.md`
- Then Options A, B, and C are documented side-by-side with the CPU-only-macOS caveat, and the `RELYLOOP_LLM=ollama make up` command is real (the Compose service + helper exist).

### AC-8: default `up` and CI pull no model
- Given a default `make up` (no `RELYLOOP_LLM`) or a CI build
- When images are pulled
- Then neither the `ollama` image nor any model is pulled (profile-gated). Verified via the YAML `profiles: ["bundled-llm"]` assertion (unit) and, if checked at runtime, `docker compose ps --services` after a default `up` not listing `ollama` (never raw `compose config`).

### AC-9: empty key keeps LLM dark only WITHOUT Option B
- Given `OPENAI_BASE_URL` pointed at a keyless local endpoint but `./secrets/openai_key` empty and Option B NOT used (manual misconfig)
- When the capability check runs
- Then it reports `missing_key` and does not probe — confirming FR-8's placeholder is what makes Option B work. (Guards the empty-key gate behavior so a regression in FR-8 is caught.)

## 13) Non-functional requirements

- **Performance:** Option B on macOS is CPU-only (Docker has no Metal). `qwen3.5:4b` Q4 is usable for chat, slow for large judgment runs. Document, don't optimize. No latency SLO — it's a dev/demo convenience.
- **Reliability:** Option B failures (pull/health) must not break Options A/C or the search stack. The ollama service is isolated behind its profile.
- **Operability:** install.sh prints clear messages for the opt-in, the skip-with-notice, and unknown-selector cases. The ollama healthcheck makes `--wait` deterministic.
- **Resource budget:** Option B adds ~3 GB resident (`qwen3.5:4b`); on a 16 GB Mac alongside Solr it's feasible but tight — `qwen3.5:2b` documented as the lighter swap. The default (Option A) adds nothing.

## 14) Test strategy requirements (spec-level)

- **Bash unit (`scripts/ci/test_parse_relyloop_llm.sh`):** mirror `test_parse_relyloop_engines.sh` — assert: unset → no `bundled-llm`; `ollama` → appends `bundled-llm`; composes with engines; unknown value → exit 1 + allowlist message; `OPENAI_BASE_URL` set → no `bundled-llm` + notice (FR-4 precedence).
- **Unit (`backend/tests/unit/test_compose_deployment_shape.py`):** extend to assert, against the **parsed YAML dict** (stable across Compose versions): `ollama` service exists; `services.ollama.profiles == ["bundled-llm"]`; the image is `${BASE_REGISTRY:-}ollama/ollama:<pinned>` and NOT `latest`; no unprofiled service `depends_on` `ollama` (parametrize `api`/`worker`). **Do NOT** assert on `docker compose config` / `config --services` output to prove default-exclusion — they may render profiled services regardless of active profiles, so those assertions are brittle/false. The YAML `profiles` key IS the contract.
- **Unit (`backend/tests/unit/core/` settings test):** assert `selected_engines` ignores `bundled-llm` — `COMPOSE_PROFILES="solr,bundled-llm"` → `selected_engines == {"solr"}` (locks the existing `& known` filter at [settings.py:484](../../../../backend/app/core/settings.py) against regression now that a non-engine profile token can appear).
- **Compose validation:** `docker compose --profile bundled-llm config --quiet` parses. Default-off, if asserted at runtime at all, uses `docker compose ps --services` after a default `up` (not `config`).
- **Doc/contract:** a lightweight check (extend the existing `test_claude_md_sections.py`-style doc test, or a new doc test) that README documents the `RELYLOOP_LLM=ollama` command — keeping README and the helper in lockstep (clean-room discipline).
- **No integration test pulls a real model** — any test exercising Option B end-to-end is opt-in/skipped in CI (hermetic-CI rule).

## 15) Documentation update requirements

- `README.md`: the three-option LLM section (FR-6).
- `docs/01_architecture/deployment.md`: document the `bundled-llm` profile + `RELYLOOP_LLM` var alongside the engine-profile section.
- `docs/01_architecture/llm-orchestration.md`: note the bundled-Ollama option as a first-class local endpoint.
- `docs/08_guides/llm-endpoint-setup.md` + `docs/08_guides/tutorial-first-study.md` Step 0: fold in the opt-in + CPU-only caveat.
- `docs/03_runbooks/corporate-network-install.md`: note the model-pull egress requirement for Option B.
- `CLAUDE.md`: add `RELYLOOP_LLM` to the install-time vars + the `bundled-llm` profile to the ports/compose notes.

## 16) Rollout and migration readiness

- **Feature flag / staged rollout:** the feature *is* opt-in by construction (`RELYLOOP_LLM`); no separate flag.
- **Migration/backfill:** none (no schema).
- **Operational readiness gates:** clean-room validation — a fresh clone must run Option A (no LLM, `missing_key`) and Option B (`RELYLOOP_LLM=ollama make up` → ollama healthy → `/healthz` `openai: configured` → chat reachable) successfully; CI green with no model pull.
- **LLM-compatibility release gate (out-of-CI, manual/maintainer):** because serving an OpenAI-compatible endpoint does not guarantee passing RelyLoop's `function_calling` + `structured_output` probes, the maintainer **MUST** run the real capability check against the chosen `ollama/ollama:<pinned>` image + `qwen3.5:4b` and record the known-good combination. If `qwen3.5:4b` via Ollama fails tool-calling/structured-output, fall back to a model that passes (Qwen3 small instruct is the documented fallback) and update the default before release. This gate is hermetic-CI-exempt (it pulls a real model) and runs in the release checklist, not `pr.yml`.
- **Release gate:** `pr.yml` green (incl. the new bash test + compose-shape test); the LLM-compatibility gate recorded; README/guide docs merged in the same PR.

## 17) Traceability matrix

| FR ID | Acceptance Criteria | Planned stories (indicative) | Test files/suites | Docs |
|---|---|---|---|---|
| FR-1 | AC-2, AC-5 | helper + install.sh wiring | `test_parse_relyloop_llm.sh` | CLAUDE.md, deployment.md |
| FR-2 | AC-1, AC-8 | `ollama` compose service | `test_compose_deployment_shape.py` | deployment.md |
| FR-3 | AC-3 | install.sh endpoint auto-wire | `test_parse_relyloop_llm.sh` (env export) | llm-orchestration.md |
| FR-4 | AC-4 | precedence in helper/install.sh | `test_parse_relyloop_llm.sh` | deployment.md |
| FR-5 | AC-6 | `OLLAMA_MODEL` plumb | `test_parse_relyloop_llm.sh` / compose | llm-endpoint-setup.md |
| FR-6 | AC-7 | README + guides | README doc test | README, guides |
| FR-7 | AC-1, AC-8 | default-off guarantee | compose-shape + bash tests | — |
| FR-8 | AC-3, AC-9 | placeholder key under Option B | `test_parse_relyloop_llm.sh` + capability-check empty-key unit test | README/guide caveat |

## 18) Definition of feature done

- [ ] **CI-verifiable ACs pass in `pr.yml`** (no model pull): AC-2, AC-4, AC-5 (helper logic); AC-1, AC-7, AC-8 (compose-shape YAML, default-off, README doc test); AC-9 (empty-key gate).
- [ ] **Maintainer/release gates (out-of-CI, real model):** AC-3 + AC-6 (Option B → `openai: configured` + chat on `qwen3.5:4b`, swap to `qwen3.5:2b`) and the §16 LLM-compatibility gate — run in the release checklist, NOT as `pr.yml` jobs (hermetic-CI rule forbids a CI model pull).
- [ ] Bash helper test + compose-shape test + `selected_engines` guard test green.
- [ ] README documents Options A/B/C (same PR as code); guides + CLAUDE.md updated.
- [ ] Clean-room validation (manual): Option A starts no LLM (`missing_key`) and reverts cleanly (sentinel cleared); Option B reaches a working chat on `qwen3.5:4b`.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- None blocking. (D-1 model-default coupling, D-7 precedence, model-pull mechanism are resolved below / in the plan.)

### Decision log
- 2026-06-19 — **Bundled LLM is opt-in, not default-on** (operator). Lightweight default stays LLM-free; `RELYLOOP_LLM=ollama` is the one-flag opt-in.
- 2026-06-19 — **Runtime = Ollama** (idea.md analysis): only option that's container-native/headless + OpenAI-compatible + CPU-viable on Apple Silicon + OSS-licensed. LM Studio (display-server/proprietary) and HuggingFace TGI (not Apple-Silicon compatible) rejected for the bundle; LM Studio documented as the native fast-path under Option C.
- 2026-06-19 — **Default model = `qwen3.5:4b`** (Apache 2.0, official Ollama library, agent/tool-calling-oriented; a measured step-change over Qwen3 small models). `qwen3.5:2b` lighter swap; Qwen3 small instruct the conservative fallback.
- 2026-06-19 — **D-7 precedence:** explicit `OPENAI_BASE_URL` wins over `RELYLOOP_LLM` (skip-with-notice).
- 2026-06-19 — **No `depends_on: ollama`** on api/worker: a depends_on across a profile-gated service breaks the default `up`; the async Redis-cached capability check reflects readiness instead.
- 2026-06-19 — **Host-native Metal detection deferred to Phase 2** ([phase2_idea.md](phase2_idea.md)).
- 2026-06-19 — **GPT-5.5 cross-model review cycle 2 (5 new findings; 4 accepted, 1 rejected).** Accepted: FR-8 now uses a **sentinel** key auto-cleared on revert to Option A (a sticky placeholder would send a dummy to api.openai.com → `incapable`, violating FR-7); FR-2 added a generous healthcheck readiness budget for the multi-GB first pull; §14/AC-8/§18 dropped all `compose config`/`config --services` exclusion assertions for the YAML `profiles` contract + `ps --services`; §18 DoD split CI-verifiable ACs from out-of-CI maintainer/real-model gates. **Rejected:** "appending `bundled-llm` to `COMPOSE_PROFILES` breaks engine consumers" — counter-evidence: [settings.py:484](../../../../backend/app/core/settings.py) `selected_engines` already intersects with `{es,os,solr}` (`& known`), dropping `bundled-llm`; added a regression test instead of a code change.
- 2026-06-19 — **GPT-5.5 cross-model review cycle 1 (9 findings, all accepted).** FR-8 added (placeholder `openai_key` — the capability check + SDK refuse an empty key, so Option B would otherwise stay dark). FR-1 extended `load_relyloop_env_file` to read `OPENAI_BASE_URL`/`OLLAMA_MODEL`/etc. from `.env` (loader previously extracted only `RELYLOOP_*`). FR-3 added a post-`--wait` capability recheck (24h cache would otherwise pin a pre-ready failure). §10 corrected to distinguish Docker image registry from Ollama model registry. §14/AC-8 dropped the brittle raw-`compose config` exclusion assertion in favor of the YAML `profiles` contract. §16 added an out-of-CI LLM-compatibility gate (real `function_calling`/`structured_output` probe of the bundled model). FR-2 pinned a non-`latest` image tag + an image-present healthcheck tool (`ollama show`, not `curl`). §11/§13 documented first-run slowness + `RELYLOOP_SKIP_AUTO_SEED=1` escape.
