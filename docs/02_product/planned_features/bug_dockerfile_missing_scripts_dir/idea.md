# API container crashes — `Dockerfile` doesn't copy `scripts/` but `demo_seeding.py` imports from it

**Date:** 2026-05-24
**Status:** **Fixed** in PR #232 commit (this branch). Idea file captures the bug + the fix + the systemic lesson for future contributors.
**Priority:** Was P0 (smoke gate broken for all PRs on main; api container crashes at startup).
**Origin:** Surfaced during PR #232 (`feature/digest-executable-followups-swap-template`) smoke-gate investigation on 2026-05-24. Root cause traced to PR #228 (`feat_home_demo_reseed_endpoint`, merged earlier same day as `ad6ff826`).

## Problem

[`backend/app/services/demo_seeding.py:39`](../../../../backend/app/services/demo_seeding.py#L39) imports four constants from `scripts/seed_meaningful_demos.py`:

```python
from scripts.seed_meaningful_demos import (
    SCENARIOS,
    TRUNCATE_TABLES,
    DEMO_ES_INDICES,
    DEMO_OS_INDICES,
)
```

This is per PR #228's locked decision D2 (reuse the CLI's constants rather than refactor them into a shared module).

But the [`Dockerfile`](../../../../Dockerfile) at the runtime stage (line 93-97 pre-fix) only copies:
- `backend/`
- `migrations/`
- `prompts/`
- `alembic.ini`
- `pyproject.toml`, `uv.lock`, `README.md`, `LICENSE`

It does **NOT** copy `scripts/`. So when the api container starts and `backend.app.api.v1._test` imports `demo_seeding`, Python raises:

```
ModuleNotFoundError: No module named 'scripts'
```

…and the api container exits with code 1 during startup. `make up` fails: `dependency failed to start: container relyloop-api-1 exited (1)`. The smoke gate fails for every PR.

## Why it slipped through

- **PR #228's own CI passed** because the docker buildx job builds the image but doesn't run it; the smoke job DID run it, but maybe was passing on a stale image cache, OR PR #228's specific smoke run was hitting the now-resolved OPENAI_API_KEY_TEST issue that masked the deeper Dockerfile error.
- **No `from scripts.` import existed in `backend/` before PR #228** — so the missing-scripts gap in the Dockerfile was latent until someone added the first import.
- The smoke job's API container error went to `docker compose logs` (uploaded as the `smoke-logs` artifact) — visible only after downloading the artifact, not in the inline `gh run view --log-failed` output.

## Fix (already applied in this PR)

One-line addition to [`Dockerfile`](../../../../Dockerfile) runtime stage:

```dockerfile
COPY --chown=relyloop:relyloop scripts/ /app/scripts/
```

With a comment explaining the dependency on `demo_seeding.py` so future contributors don't innocently delete it.

## Systemic prevention (deferred — leaving as a follow-up)

The deeper question: how do we catch "code imports a directory that isn't in the runtime image" before it lands on main? Two reasonable hardenings:

1. **Smoke-build sanity test at PR time** — `docker compose up -d` + `curl /healthz` inside the docker-buildx CI job, not just the smoke job. The docker-buildx job currently only `docker buildx build`s (no push, no run). Extending it to a quick `docker run --rm <image> python -c "from backend.app.main import app"` would catch missing-module errors at image-build time.
2. **Runtime-image module-import smoke** — a test that imports every `backend.app.*` module against the built image's Python environment. Catches missing dependencies even when no code path triggers the import in normal operation.

Neither is in scope for THIS bug fix (which is just "copy the directory"); capturing for future infra-hardening work. Owner: TBD — could be a `chore_ci_image_import_smoke` or `infra_pr_docker_run_smoke` idea.

## Related work

- PR #228 `feat_home_demo_reseed_endpoint` introduced the `from scripts.` import.
- PR #232 `feat_digest_executable_followups_swap_template` discovered + fixed the bug.
- The `chore_tutorial_polish` PR #64 (2026-05-12) added the smoke gate that now catches this class of regression.
