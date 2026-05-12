# bug_dockerfile_missing_prompts — RESOLVED in feat_chat_agent

**Type:** bug (latent regression)
**Date:** 2026-05-12
**Origin:** First-run testing of `feat_chat_agent` PR #60 — operator saw 404
on `GET /api/v1/conversations` after `docker compose build && up`.
**Status:** Fixed inline in PR #60 commit; left as a documentation artifact
because the same root cause silently affected `feat_llm_judgments` and
`feat_digest_proposal` since their respective merges.

## Problem

The `Dockerfile` at the repo root copies `backend/`, `migrations/`,
`alembic.ini`, and `pyproject.toml` into `/app/` but does NOT copy
`prompts/`. Any code that loads a file from `prompts/` at module-import
time fails with `FileNotFoundError` inside the runtime container.

Symptoms:
- `feat_chat_agent`: API container crashes on import — every chat-feature
  endpoint 404s because the router is never registered.
- `feat_llm_judgments`: judgment generation worker would crash on first
  call to `load_judgment_prompts()` — but the failure is gated behind
  `OPENAI_API_KEY_FILE` being populated, so operators without an OpenAI
  key never trigger it.
- `feat_digest_proposal`: same — gated behind the same `OPENAI_API_KEY`
  preflight in `agent_judgments_dispatch`.

The latent failure has been in the image since `feat_llm_judgments`
merged (PR #35, 2026-05-11). It only surfaced now because `feat_chat_agent`
does the file load at module-import time (the orchestrator caches
`SYSTEM_PROMPT` at import) rather than lazily on first request.

## Fix (applied in PR #60)

1. `Dockerfile`: added `COPY --chown=relyloop:relyloop prompts/ /app/prompts/`
   alongside the existing backend/migrations COPY block.
2. `backend/app/agent/orchestrator.py`: switched `SYSTEM_PROMPT_PATH` from
   `Path("prompts/orchestrator.system.md")` (CWD-relative — fragile if the
   container's working dir ever changes) to
   `Path(__file__).resolve().parents[3] / "prompts" / "orchestrator.system.md"`,
   matching the existing `backend.app.llm.prompt_loader.PROMPTS_DIR`
   convention. This makes the loader CWD-independent so even an operator
   running `python -m backend.app.main` from a non-repo-root directory works.

## Why this should have been caught earlier

CLAUDE.md "Operator-path verification" rule (added by `infra_foundation`)
explicitly mandates `make up` end-to-end before declaring any story complete.
The chat-feature stories ran `make test-unit` + `make typecheck` + `make lint`
but never the full `make up` smoke until PR review. The smoke would have
caught this in seconds.

The systemic fix (CI smoke that runs `make up`) is tracked at
`infra_ci_smoke_makeup/idea.md` (created during `infra_foundation` PR #4
post-mortem). This idea file documents one more concrete failure mode the
CI smoke would have caught, strengthening the case for that follow-up.

## Tangential — verify before MVP1 ships

Spot-check a few other module-load file reads to make sure no other
prompts-style assets are missing from the Docker image:
- `prompts/digest_narrative.system.md` — used by digest worker
- `prompts/judgment_generation.system.md` — used by judgments worker
- `samples/` — referenced by `chore_tutorial_polish` (planned)
- `templates/` — query template definitions (`infra_adapter_elastic` slot)

Probably need to add `samples/` and `templates/` to the Dockerfile when
those features land.
