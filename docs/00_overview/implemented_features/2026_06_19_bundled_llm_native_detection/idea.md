# Local LLM — native-first (use the host's Metal-accelerated Ollama; demote the Docker bundle)

**Date:** 2026-06-19
**Status:** Idea — re-scoped from the deferred Phase 2 of the shipped `feat_bundled_local_llm` (PR #573). **Operator decision this session:** the Dockerized bundled LLM (Option B) is CPU-only on Docker-for-Mac and too slow to be useful (a 256-token reply exceeded 10 min on a dev Mac), so the *native* Metal-accelerated path should be THE local-LLM story, not a deferred enhancement.
**Priority:** P1
**Origin:** Validation of `feat_bundled_local_llm` surfaced that Docker-on-Mac CPU-only inference is impractically slow; the operator chose "native-first, drop/demote the Docker bundle." Builds on `feat_bundled_local_llm`'s `RELYLOOP_LLM` selector + `OPENAI_BASE_URL` auto-wiring + the `bundled-llm` Compose service (which becomes the escape hatch).
**Depends on:** `feat_bundled_local_llm` (shipped) — its `scripts/lib/relyloop_llm.sh`, install.sh wiring, sentinel-key handling, and `ollama` Compose service are reused/re-scoped here.

> **Priority guidance:** P1 — this is the version of the local-LLM feature that's actually usable. The shipped Docker bundle works but is too slow on Mac to be a real option; this delivers Metal speed with one flag.

## Problem

`RELYLOOP_LLM=ollama make up` today starts a Dockerized Ollama. On Docker-for-Mac that's **CPU-only** (no Metal passthrough) and impractically slow — a "proves the agent runs" novelty, not something an operator would use interactively or for a judgment run. The genuinely fast local path — a **host-native** Ollama (the Mac app uses Metal) — works today only via the manual Option C (`OPENAI_BASE_URL=http://host.docker.internal:11434/v1`). The default local-LLM flag should deliver the fast path automatically, and the slow Docker container should stop being the headline behavior.

## Proposed capabilities

### Capability 1 — `RELYLOOP_LLM=ollama` becomes native-first

- When `RELYLOOP_LLM=ollama` and `OPENAI_BASE_URL` is unset, install.sh (running on the host) **probes for a native Ollama** on `http://localhost:11434/api/tags`.
- **Found** → auto-wire the app at the host-native Ollama (`OPENAI_BASE_URL=http://host.docker.internal:11434/v1`), Metal-fast, no Docker LLM container started. Write the sentinel key + default the model as today.
- **Not found** → do **not** start the slow Docker container. Print a clear, actionable message and bring the stack up LLM-free (`/healthz` `missing_key`), e.g.:
  > `RELYLOOP_LLM=ollama: no native Ollama detected on localhost:11434. Install Ollama (https://ollama.com), then 'ollama serve' + 'ollama pull qwen3.5:4b' and re-run — or set OPENAI_BASE_URL to any OpenAI-compatible endpoint. (For the slow CPU-only Docker fallback: RELYLOOP_LLM=ollama-docker.)`

### Capability 2 — Docker bundle demoted to an explicit escape hatch

- The Phase-1 Dockerized container moves behind `RELYLOOP_LLM=ollama-docker` (the only value that adds the `bundled-llm` Compose profile). Kept for the genuinely-zero-install case and for Linux hosts where the operator can attach a GPU — but never the default `ollama` behavior.
- `relyloop_llm.sh` allowlist becomes `{ollama, ollama-docker}`; only `ollama-docker` appends the `bundled-llm` profile. Native detection lives in install.sh (it needs host network access the pure helper shouldn't assume).

### Capability 3 — native model-presence check

- If a native Ollama is detected but the chosen `OLLAMA_MODEL` (default `qwen3.5:4b`) isn't pulled there, either instruct the operator to `ollama pull <model>` (and proceed LLM-degraded), or attempt the pull. Decide the UX at spec time (D-3).

## Scope signals

- **Backend:** none (still env-driven; no service-code change).
- **Config / install:** install.sh native-probe + branch rework; `relyloop_llm.sh` allowlist + semantics (`ollama` = detect-native, `ollama-docker` = container); the `ollama` Compose service stays (now only started by `ollama-docker`). New `.env`/docs.
- **Migration / audit:** none.
- **Tests:** bash-test rework for the new allowlist + the native-detect/not-found branches (mock the probe); compose-shape unchanged.

## Open design forks (decide at spec)

- **D-1 — Linux `host.docker.internal`.** It doesn't resolve on Linux by default. Native-detect on Linux needs `--add-host=host.docker.internal:host-gateway` (or `172.17.0.1`) wired into the api/worker services, or the feature degrades to "Linux users use Option C / `ollama-docker`." Decide the cross-platform contract.
- **D-2 — not-found UX:** warn + proceed LLM-free (recommended — never block the stack) vs hard-error. Recommend warn+proceed.
- **D-3 — native model-presence:** instruct-and-degrade vs auto-pull on the native daemon.
- **D-4 — LM Studio:** also probe `:1234` (LM Studio) under a broader value, or keep `ollama` Ollama-only and leave LM Studio to Option C? Recommend Ollama-only for `ollama`; document LM Studio via Option C.
- **D-5 — keep vs remove the Docker container:** keep behind `ollama-docker` (recommended — preserves zero-install + Linux-GPU) vs remove entirely. Recommend keep-behind-escape-hatch.

## Why now (no longer deferred)

The shipped Docker bundle is too slow to be the local-LLM answer on the primary target platform (Mac). Native-first makes the feature actually usable while reusing nearly all of the Phase-1 plumbing. Priority raised Backlog/P2 → **P1**.

## Relationship to other work

- Re-scopes the shipped `feat_bundled_local_llm`: `OPENAI_BASE_URL` precedence, sentinel key, and the `ollama` Compose service are reused; the `ollama` selector value changes meaning (native-first), and `ollama-docker` is added.
- Subsumes the manual Option C for the common native-Ollama case (auto-detect instead of a hand-set env var); Option C stays for arbitrary endpoints (cloud, LM Studio, LiteLLM, remote).
