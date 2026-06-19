# Bundled local LLM — one-flag opt-in for out-of-box LLM features

**Date:** 2026-06-19
**Status:** Idea — user request after the clean-room Solr-only quickstart validation (PR #572). With `RELYLOOP_ENGINES=solr make up`, a fresh clone now reaches a running app with a green Solr cluster and demo data — but the LLM-dependent features (chat agent, LLM-as-judge, digest narrative) stay dark because no LLM endpoint is configured by default.
**Priority:** P2
**Origin:** User request: "It would be nice if the default setup could immediately run including the LLM-related features… Is there an open-source LLM we could launch in a Docker container small enough for most corporate developer-grade Macs? … if you overrode `OPENAI_BASE_URL` in `.env`, this LLM container wouldn't even get launched."
**Depends on:** None to start. Builds directly on two shipped capabilities — the single-endpoint LLM flexibility (`OPENAI_BASE_URL`, [settings.py:123](../../../../backend/app/core/settings.py)) and the selective-engine-startup pattern (`RELYLOOP_ENGINES` → `COMPOSE_PROFILES`, [scripts/lib/relyloop_engines.sh](../../../../scripts/lib/relyloop_engines.sh)).

> **Priority guidance:** P2 — important enough to file, not blocking. It improves first-run DX (out-of-box LLM features) but the stack is fully operational without it; an operator can already point `OPENAI_BASE_URL` at OpenAI cloud or a local Ollama today.

## Problem

After `RELYLOOP_ENGINES=solr make up`, the stack is healthy and seeded, but `OPENAI_BASE_URL` defaults to `https://api.openai.com/v1` with an **empty** `openai_key` placeholder, so `/healthz` reports `openai: missing_key` and every LLM feature refuses or degrades:

- **Chat agent** — the front-door conversational surface can't dispatch tools.
- **LLM-as-judge** — `POST /api/v1/judgment-lists/generate-from-ubi` and judgment generation can't run.
- **Digest narrative** — study digests skip the LLM-written summary.

A brand-new evaluator therefore sees a working *search* demo but a dead *agent* demo, and must go find an OpenAI key or stand up their own Ollama before the headline "conversational LLM agent" feature does anything.

**Design decision (operator, 2026-06-19): keep the basic default LLM-free; make the bundled LLM a one-flag opt-in.** The simplest `make up` must stay lightweight — no Ollama process, no multi-GB model pull, fewer moving parts, lower RAM — so the fastest path to a running search demo has nothing extra to download or schedule. But enabling a working local LLM must be *one obvious flag away*: an explicit opt-in that immediately starts Ollama serving `qwen3.5:4b` so chat / LLM-as-judge / digest work with no external key. And when the operator has already pointed `OPENAI_BASE_URL` at their own endpoint, the bundled container must **never** launch. These two startup options must be **clearly documented side-by-side in `README.md`** (see Capability 3).

## The hard constraint (read first — it drives every design fork below)

**Docker Desktop on macOS has no Metal/GPU passthrough.** Containers run in a Linux VM that cannot see Apple Silicon's GPU or Neural Engine, so any LLM running *inside a Docker container on a Mac is CPU-only* — regardless of how powerful the Mac's GPU is. (The native Ollama macOS app *does* use Metal; the same model in a container does not.)

Consequences:
- The bundled model must be **small** (≈1.5B–3B params, 4-bit quantized, ~1–2 GB) to give acceptable CPU-only latency on a typical corporate Mac (Apple Silicon, 16 GB RAM).
- Even small, **judgment generation** (LLM-as-judge over many query×doc pairs) will be slow; the **chat demo** will be usable but not snappy.
- This is a deliberate "it works out of the box" default, **not** a performance recommendation. The docs must say so plainly, and the easy-swap path (below) is how a user upgrades to a fast/remote model.

## Proposed capabilities

### Capability 1 — bundled OpenAI-compatible LLM container (opt-in)

- Add an `ollama` service to `docker-compose.yml` behind a Compose profile (e.g. `profiles: ["bundled-llm"]`), mirroring the engine services' `profiles:` gating.
- **Ollama** is the recommended *bundled* runtime — see the "Runtime selection" section below for the full Ollama vs LM Studio vs HuggingFace rationale. In short: it is the only one of the three that is genuinely container-native/headless, OpenAI-compatible, CPU-viable on Apple-Silicon Macs, and OSS-licensed (MIT) for clean bundling into an Apache-2.0 project. It exposes an OpenAI-compatible `/v1` endpoint (drop-in for the existing `openai` SDK client), manages model pull/serve with one command, and needs no API key (the SDK's required `api_key` is ignored — the empty `openai_key` placeholder is fine).
- Default candidate model: **`qwen3.5:4b`** (Q4-quantized, ~2–3 GB), with **`qwen3.5:2b`** as the lighter-RAM fallback. Rationale: Qwen3.5 is a measured step-change over Qwen3 at small sizes (per Artificial Analysis, the 4B gains ~9 points over Qwen3-4B-2507, with similar jumps at 2B/9B), the line is explicitly agent/tool-calling-oriented (Alibaba's `Qwen-Agent` targets Qwen ≥3.0 for Function Calling/MCP — what the chat orchestrator and the capability check require), it's **Apache 2.0**, and crucially it's in Ollama's **official** library (`qwen3.5:2b/4b/9b`), so it drops straight into the bundled-container plan. Two caveats to validate: (a) Qwen3.5 is recent (~Feb 2026) so less battle-tested than Qwen3 in tool-calling flows — official-library presence is the maturity signal; (b) the Qwen3.5 small models are *natively multimodal*, which RelyLoop doesn't use (text-only) — harmless, just unused. **Benchmark at spec time** against the real capability check (`function_calling` + `structured_output` probes, FR-7) and the chat orchestrator's actual tool schema before locking the default — small models vary on tool-calling reliability, and Qwen3.x's *thinking vs non-thinking* mode interacts with OpenAI-style tool dispatch (test the non-thinking path). Qwen3 small instruct remains the conservative fallback if 3.5 proves rough. See D-4.
- Model is pulled on first start (init step) and cached in a named volume so subsequent `make up` is fast (see D-2 for pull-on-start vs bake-into-image).

### Capability 2 — opt-in launch (default OFF; explicit flag turns it on; BYO endpoint bypasses)

Three startup states, resolved by `install.sh` before any `docker compose` call — mirroring the existing `RELYLOOP_ENGINES` → `COMPOSE_PROFILES` machinery ([install.sh §0 + §5](../../../../scripts/install.sh), [relyloop_engines.sh](../../../../scripts/lib/relyloop_engines.sh)):

| State | Trigger | Result |
|---|---|---|
| **1. Lightweight default** | neither `RELYLOOP_LLM` nor `OPENAI_BASE_URL` set | **No LLM container.** Search works; LLM features (chat/judge/digest) report `missing_key` and refuse — honestly. Fastest start, smallest RAM, nothing to download. |
| **2. Bundled LLM (one-flag opt-in)** | `RELYLOOP_LLM=ollama` | `install.sh` adds the `bundled-llm` profile → Ollama starts, pulls + serves **`qwen3.5:4b`**, and the app's `OPENAI_BASE_URL` is auto-pointed at `http://ollama:11434/v1`. Chat/judge/digest work immediately, no external key. |
| **3. Bring-your-own endpoint** | `OPENAI_BASE_URL=…` set | Use that endpoint; the bundled container is **never** added or launched (even if `RELYLOOP_LLM=ollama` is also set — explicit endpoint wins; see D-7). |

- New install-time env var **`RELYLOOP_LLM`** (allowlist: `ollama` today; room for other bundled runtimes later), read from shell/`.env` and parsed by a small `scripts/lib/` helper that appends `bundled-llm` to `COMPOSE_PROFILES` — mirroring (and unit-tested like) `relyloop_engines.sh`. Default unset → profile absent → no LLM container.
- App side: the `api` + `worker` Compose env sets `OPENAI_BASE_URL=${OPENAI_BASE_URL:-<auto>}`, where `<auto>` is `http://ollama:11434/v1` **only** when the `bundled-llm` profile is active, otherwise empty so the honest `missing_key` state shows in `/healthz`.
- Net result, exactly as requested: bare `make up` → no LLM (lightweight); `RELYLOOP_LLM=ollama make up` → a working local LLM immediately on `qwen3.5:4b`; `OPENAI_BASE_URL=…` → your endpoint with no bundled container.

### Capability 3 — README documentation of the two options + easy model swap

**README is a required deliverable of this feature, shipped in the same PR as the implementation** (never ahead of it — a documented-but-nonexistent command is the exact clean-room failure mode PR #572 eliminated). The Quickstart must present the two startup options side-by-side. Draft copy to land:

> #### LLM features (chat agent, LLM-as-judge, digest) — optional
>
> The basic Quickstart above runs **search only** — it's the fastest, lightest start. The LLM-powered features (the conversational agent, LLM-as-judge, digest narratives) need an LLM endpoint. Pick one:
>
> **Option A — no LLM (default).** Do nothing. Search and the optimization loop work fully; the chat/judge/digest features stay off until you configure an endpoint. `/healthz` shows `openai: missing_key`.
>
> **Option B — bundled local LLM (one flag).** Start a self-contained Ollama serving `qwen3.5:4b`, no API key needed:
> ```bash
> RELYLOOP_LLM=ollama RELYLOOP_ENGINES=solr make up
> ```
> First run pulls the model (~2–3 GB). On macOS this runs **CPU-only** (Docker has no Metal access), so it's usable for the demo but modest in speed — fine for chat, slow for large judgment runs. Swap the model with `OLLAMA_MODEL=qwen3.5:2b` (lighter) or any Ollama tag.
>
> **Option C — bring your own endpoint.** Point `OPENAI_BASE_URL` at any OpenAI-compatible endpoint — OpenAI cloud, a Metal-accelerated **native** Ollama or **LM Studio** on your Mac (`http://host.docker.internal:11434/v1` or `:1234/v1`), or a LiteLLM/OpenRouter proxy. Setting `OPENAI_BASE_URL` means the bundled container never launches. See [`docs/08_guides/llm-endpoint-setup.md`](../../../../docs/08_guides/llm-endpoint-setup.md).

- One-line model swap via `.env`: `OLLAMA_MODEL=qwen3.5:2b` (or any Ollama tag), consumed by the container's pull/serve step and surfaced as the `OPENAI_MODEL` / `OPENAI_MODEL_CHAT` defaults when bundled (respecting Absolute Rule #8 — names come from `Settings`/env, never hardcoded in service code).
- Also update `docs/08_guides/llm-endpoint-setup.md` + the tutorial's "Step 0 Path B" (which already documents local-LLM setup) to fold in the bundled opt-in and the CPU-only-Mac caveat.

## Runtime selection: Ollama vs LM Studio vs HuggingFace

The bundled runtime (the one `RELYLOOP_LLM=ollama` launches — Option B) has a non-negotiable profile: it must be **containerized + headless** (launched by `docker compose`, no GUI), **OpenAI-compatible**, **CPU-viable on Apple-Silicon Macs** (the Docker-on-Mac CPU-only reality above), and **OSS-license-clean** to bundle into an Apache-2.0 project. Against that bar:

| Runtime | Fit as the bundled opt-in runtime? | Why |
|---|---|---|
| **Ollama** | ✅ **Yes — recommended** | Container-native official image, headless server, OpenAI `/v1`, one-command model pull, runs CPU-only on Apple Silicon in Compose, **MIT (OSS)** so it bundles cleanly. |
| **LM Studio** | ❌ No (but ✅ best *native* fast-path) | Desktop **GUI app that requires a display server** — impractical/unsupported for headless Docker; its Docker GPU mode is preview and CPU-only on x86. Also **proprietary/closed-source** (free for personal + commercial use, but awkward to bundle into an OSS project). Its strength is the opposite end: run **natively** on the user's Mac (MLX/**Metal-accelerated**, nice GUI) and point `OPENAI_BASE_URL` at `http://host.docker.internal:1234/v1`. That path already skips the bundled container (Capability 2). |
| **HuggingFace TGI** | ❌ No | **Not compatible with Apple-Silicon Macs**; GPU/datacenter-oriented with only Intel-CPU fallback. Wrong tool for the corporate-Mac default. License has also been turbulent (Apache 2.0 → HFOIL → back to Apache 2.0), adding bundling risk. Relevant only for a future **GPU server** deployment, not the laptop default. Note: "HuggingFace" is also where the **models** come from (the Hub) — Ollama/LM Studio/llama.cpp all pull GGUF weights that originate there, so HF stays in the picture as the model *source* regardless of runtime. |

**Recommendation for most RelyLoop users:** **Ollama as the bundled opt-in runtime** (`RELYLOOP_LLM=ollama` — Option B), with **LM Studio documented as the recommended *native* alternative** for Mac users who want GUI model management + Metal speed (via the `OPENAI_BASE_URL` override — Option C — which by design doesn't launch the bundled container). The bare-`make up` majority get the lightweight no-LLM default (Option A) and turn on LLM features with one flag when they want them. HuggingFace = the model source for all of them, and TGI is parked for an eventual GPU-server profile, not the Mac default. `llama.cpp`'s `llama-server` remains a lighter containerized alternative to Ollama if model auto-management isn't wanted (see D-2).

## Scope signals

- **Backend:** minimal. No service-code change required — `OPENAI_BASE_URL`/`OPENAI_MODEL` are already env-driven through `Settings`. Possible touch: the startup capability check's timing vs first-run model pull (Capability 2 / D-3).
- **Frontend:** none.
- **Migration:** none.
- **Config:** new Compose service (`ollama`) + profile (`bundled-llm`); new install-time var `RELYLOOP_LLM` + `.env` knob `OLLAMA_MODEL`; the `OPENAI_BASE_URL` auto-wiring; `install.sh` profile logic + a small `scripts/lib/` helper mirroring the engines/versions helpers so it's unit-testable in isolation (`scripts/ci/test_*`). Named volume for the model cache.
- **Audit events:** N/A (no state mutations; pre-MVP3 anyway).
- **Resources:** only relevant when **Option B** is opted into — the default adds nothing. With Option B on a 16 GB Mac: Solr (~1 GB heap) + Postgres + Redis + api + ui + Ollama (`qwen3.5:4b` resident ~3 GB) is feasible but tight; `qwen3.5:2b` is the lighter swap (D-4).

## Open design forks (decide at spec / preflight)

- **D-1 — model-name defaults coupled to the active option.** When the bundled LLM is on (Option B), `OPENAI_MODEL` / `OPENAI_MODEL_CHAT` must default to the local tag (`qwen3.5:4b`); otherwise they stay the cloud default (a GPT id). The trap: a user picks Option C against OpenAI cloud but leaves `OPENAI_MODEL` at a local tag → sends `qwen3.5` to OpenAI (invalid), or the reverse. Options: (a) `install.sh` sets the model defaults to match the chosen option; (b) document that each option carries its own model default. Recommend (a), with (b) documented as the fallback.
- **D-2 — model delivery: pull-on-start vs bake-into-image.** Pull-on-start (Ollama entrypoint `ollama pull $OLLAMA_MODEL`) keeps the image small but needs egress to `registry.ollama.ai` on first run — which a locked-down corporate network blocks (same class as the existing `BASE_REGISTRY` corp-proxy handling, [corporate-network-install.md](../../../../docs/03_runbooks/corporate-network-install.md)). Bake-into-image gives a truly offline first-run but produces a multi-GB image. Recommend pull-on-start + a documented corp-proxy/offline path; revisit baking if offline-first becomes a hard requirement.
- **D-3 — capability-check timing.** The startup capability check (FR-7) and `/healthz` may run before the first-run model pull finishes, briefly reporting the LLM as untested/unreachable. Gate `api`'s readiness on an Ollama healthcheck that only goes healthy once the model is served (mirror the `migrate` init-container `depends_on` pattern), or accept a documented warm-up window.
- **D-4 — default model size + tool-calling floor.** 1.5B (lighter, faster, weaker tool-calling) vs 3B (better tool-calling, heavier). The chat agent *needs* reliable function calling; the judge needs reliable structured output. Pick the smallest model that clears the capability-check probes against the real schemas. This must be an empirical benchmark, not a guess.
- **D-5 — Dockerized (CPU-only) vs host-native (Metal) as the recommended fast path.** Because Docker-on-Mac is CPU-only, the genuinely *fast* local options are **host-native** runtimes reached via `host.docker.internal` (Metal-accelerated): native **Ollama** (`:11434/v1`) or native **LM Studio** (`:1234/v1`, GUI). Both require a native install, so neither is "one compose command." Decide whether `install.sh` should *detect* a host-native server already listening on `:11434`/`:1234` and prefer it (skipping the bundled container) before falling back to the bundled CPU-only container when Option B is requested. Best of both: fast when a native runtime exists, the bundled container otherwise.
- **D-6 — release target.** Filed under `02_mvp2/` as the active release (improves the current out-of-box demo). If the team would rather not expand MVP2 surface, it slots cleanly into `99_backlog/` as a DX upgrade. Confirm at preflight.
- **D-7 — `RELYLOOP_LLM` vs `OPENAI_BASE_URL` precedence.** If both `RELYLOOP_LLM=ollama` and a custom `OPENAI_BASE_URL` are set, which wins? Recommend **`OPENAI_BASE_URL` wins** — the operator clearly has an endpoint, so don't launch the bundled container; `install.sh` prints a one-line notice that the bundled LLM was skipped because `OPENAI_BASE_URL` is set. Alternative: hard-error on the contradiction. Recommend skip-with-notice for friendliness (matches the engines helper's tolerant posture).

## Why filed (not implemented now)

It's a real DX win but not blocking: the stack is fully functional without it, and operators already have documented LLM paths (OpenAI cloud, local Ollama, LiteLLM/OpenRouter). It also carries genuine forks (D-1, D-4, D-5) and an honest perf caveat that deserve a spec + cross-model review rather than an inline change. Capturing it now while the clean-room context is fresh; pick up when first-run DX is the priority.

## Relationship to other work

- **Extends** the shipped single-endpoint LLM flexibility (`OPENAI_BASE_URL`) — this is the "batteries-included default endpoint" on top of it, not a replacement.
- **Reuses** the `RELYLOOP_ENGINES` → `COMPOSE_PROFILES` conditional-launch machinery from `feat_selective_engine_startup_and_demo` — the LLM container is gated by the same profile mechanism.
- **Complements** the Solr-only quickstart (PR #572): together they make `make up` a complete, demonstrable product (search + agent) from one command.
- **Distinct from** the backlog "native non-OpenAI provider SDKs" item — this stays entirely within the OpenAI-compatible surface; no new provider abstraction.
