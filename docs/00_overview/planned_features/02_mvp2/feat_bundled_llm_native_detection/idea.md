# Bundled local LLM — host-native runtime auto-detection (Metal fast-path)

**Date:** 2026-06-19
**Status:** Idea — split out at finalization from Phase 2 of the shipped `feat_bundled_local_llm` (PR #573, merged 2026-06-19). See the archived [feature_spec.md](../../../implemented_features/2026_06_19_bundled_local_llm/feature_spec.md) §3 Phase boundaries + §19 decision-log D-5.
**Priority:** P2
**Origin:** Phase boundary in the shipped feature's `feature_spec.md` §3; design fork D-5.
**Depends on:** `feat_bundled_local_llm` (shipped) — the `bundled-llm` profile, `RELYLOOP_LLM` selector, and the `OPENAI_BASE_URL` auto-wiring it added must exist first (they do).

> **Priority guidance:** P2 — a speed/UX enhancement on top of the working Phase-1 opt-in. Not blocking; Phase 1 already delivers a working local LLM.

## Problem

Phase 1's bundled Ollama runs **inside Docker**, which on macOS is **CPU-only** (no Metal passthrough) — usable but slow. The genuinely fast local path is a **host-native** runtime (native Ollama on `:11434` or LM Studio on `:1234`), which is Metal-accelerated. Today a user gets that only by manually setting `OPENAI_BASE_URL=http://host.docker.internal:11434/v1` (Option C). Phase 2 makes it automatic.

## Proposed capabilities

### Host-native detection in install.sh

- When `RELYLOOP_LLM=ollama` is requested AND `OPENAI_BASE_URL` is unset, probe the host for an already-listening native runtime: Ollama on `host.docker.internal:11434` (`/api/tags`) and/or LM Studio on `:1234` (`/v1/models`).
- If found, **prefer the native runtime** — set `OPENAI_BASE_URL` to it (Metal speed) and **skip launching the bundled CPU-only container** entirely.
- If not found, fall back to the Phase-1 bundled container (current behavior).
- Make the detection explicitly skippable (e.g. `RELYLOOP_LLM=ollama-bundled` to force the container, or a `RELYLOOP_LLM_PREFER_NATIVE=0` knob) so the choice stays the operator's.

### Model presence check on the native runtime

- If the native runtime is present but the chosen `OLLAMA_MODEL` isn't pulled there, either prompt/instruct the operator to `ollama pull` it, or fall back to the bundled container. Decide the UX at spec time.

## Scope signals

- **Backend:** none.
- **Config:** install.sh probe logic + a precedence knob; no new Compose service (reuses Phase 1's, just may not start it).
- **Migration / audit:** none.
- **Risk:** `host.docker.internal` resolution differs across Docker engines/OSes; the probe must fail-safe (probe failure → use the bundled container, never error out the install).

## Why deferred

Phase 1 already gives a working one-flag local LLM. Native detection is a speed optimization that adds host-port probing + a precedence decision (native vs bundled vs BYO) that benefits from its own spec/review cycle. Splitting it keeps Phase 1's reviewable surface tight.

## Relationship to other work

- Extends Phase 1 (`RELYLOOP_LLM` / `bundled-llm` profile / `OPENAI_BASE_URL` auto-wiring).
- Complements Option C (BYO endpoint) — this automates what Option C does manually for the common native-runtime case.
- LM Studio's native fast-path (idea.md "Runtime selection") is realized here, not in Phase 1.
