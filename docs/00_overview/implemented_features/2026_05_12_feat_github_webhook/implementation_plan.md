# Implementation Plan — feat_github_webhook

**Date:** 2026-05-12 (Review & Patch cycle 2026-05-12 — see §11 patch log)
**Status:** Complete (PR #56, merged 2026-05-12; squash commit `9805f3e`)
**Primary spec:** [feature_spec.md](feature_spec.md) (Approved 2026-05-12 after Review & Patch cycle)
**Policy sources:**
- [`CLAUDE.md`](../../../../CLAUDE.md) — absolute rules, conventions, MVP1 stack
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — webhook URL convention (`/webhooks/<provider>`, no `/api/v1` prefix), `_err()` envelope contract, cursor pagination
- [`docs/01_architecture/apply-path.md`](../../../01_architecture/apply-path.md) — webhook + polling architecture
- [`docs/04_security/github-token-handling.md`](../../../04_security/github-token-handling.md) — per-repo PAT storage, redaction, token-safe surfaces

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR / AC IDs from `feature_spec.md`.
- Phase gate is a hard stop: end-to-end synthetic-webhook scenario PLUS polling reconciler PLUS auto-registration all green before the PR is merge-eligible.
- Fail-loud tests: every error code asserted explicitly (status code + `error_code` + `retryable`).
- Reuse existing patterns: signature verify, repo functions, GitHub API client, redaction all follow `feat_github_pr_worker` analogues.
- One spec-level shared helper is extracted explicitly (Story 1.5): the GitHub API call helpers currently inlined in `backend/workers/git_pr.py` (the POST-only `_github_post` at line 593 plus `_parse_retry_after`, `_is_secondary_rate_limit`, `_body_mentions_rate_limit`, `_parse_rate_limit_reset`) move to a shared module so the new polling worker + register-webhook worker don't duplicate them. Story 1.5 is **not** a pure rename — the polling reconciler needs `GET /repos/.../pulls/{n}`, so `_github_post` is generalised to a method-agnostic `github_request(client, method, url, *, json_body=None, token=...)`. The existing `_github_post` call sites in `git_pr.py` retain a thin POST wrapper that calls through, so feat_github_pr_worker's tests stay the regression gate.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (Webhook endpoint) | Epic 2 / Story 2.1 | `POST /webhooks/github`: signature verify, dispatch, all 4 action handlers |
| FR-2 (Polling reconciler) | Epic 3 / Story 3.1 | `reconcile_pr_state` Arq cron job + `WorkerSettings.cron_jobs` wiring |
| FR-3 (Webhook auto-registration) | Epic 4 / Stories 4.1 + 4.2 | 4.1 ships the `register_webhook` Arq worker; 4.2 extends `POST /api/v1/config-repos` to enqueue it post-commit |
| FR-4 (Migration + Settings) | Epic 1 / Story 1.1 | New migration `0006_proposals_pr_url_idx` + `relyloop_pr_poll_minutes` Settings field + `.env.example` |
| AC-1, AC-2, AC-4, AC-5 (webhook behavior) | Epic 2 / Story 2.1 tests | Integration + contract tests in the same story |
| AC-3, AC-8 (polling) | Epic 3 / Story 3.1 tests | Cassette-replayed `GET /repos/.../pulls/{n}` |
| AC-6, AC-7 (auto-registration) | Epic 4 / Stories 4.1 + 4.2 | Cassette-replayed `GET /hooks` (dedup) + `POST /hooks` (happy / 404 / 422 paths) |

**Single phase.** Spec §3 "Phase boundaries" defines one phase: "merge a PR on GitHub → within 30 seconds the RelyLoop UI shows `pr_state = merged`. Even if the webhook delivery fails, within 15 minutes the polling reconciler catches it." No deferred phases — nothing to track in a `phase2_idea.md`.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Four epics, 11 stories. Epic 1 ships foundations (the new migration + Settings + helpers + repo functions + shared GitHub client extraction); Epic 2 ships the webhook receiver; Epic 3 ships the polling reconciler; Epic 4 ships auto-registration + docs.

### Project conventions

- Backend code lives under `backend/app/...`. Workers live under `backend/workers/` (plural). Migrations under `migrations/versions/`.
- Routers are registered via `app.include_router(...)` in `backend/app/main.py`. The webhook router mounts unprefixed (no `/api/v1`) per `docs/01_architecture/api-conventions.md:14` + CLAUDE.md Rule #6 — same exception as `/healthz`.
- Error envelope: `{"detail": {"error_code", "message", "retryable"}}` via the `_err()` helper. The webhook router uses the same envelope (spec Decision log 2026-05-12).
- All new code is `mypy --strict` clean. Lint via `ruff check` + `ruff format --check`. 80% coverage gate per `pyproject.toml`.
- LLM model names are never hardcoded; this feature touches no LLM code so the rule is vacuously satisfied.
- Repo functions: `db: AsyncSession` first arg, `await db.flush()` for staging changes, caller commits, return `Model | None` for single-row fetches.
- Conditional UPDATE pattern (proposal pr_state writes): mirror `mark_proposal_pr_opened` (`backend/app/db/repo/proposal.py:184`) — `WHERE` clause guards the expected pre-state, `returning(Proposal)`, `await db.flush()`, return `Proposal | None`.
- All log lines from this feature MUST pass through structlog's existing `RedactTokensProcessor` (`backend/app/domain/git/redaction.py`) which redacts GitHub PAT patterns. Webhook secrets are operator-chosen strings (not PAT-formatted) — they are NEVER logged anywhere by this feature; story 2.1 includes a static-grep audit asserting no log call sites take the secret.

### AI agent execution protocol

Standard execution order per the template:
1. Load `CLAUDE.md`, `architecture.md`, `state.md`, this plan, and the spec.
2. Read each story's full scope: outcome, new/modified files, endpoints, key interfaces, DoD.
3. Implement in order: domain helpers → repo functions → migration → Settings → workers → router → main.py registration → tests → docs.
4. Run `make fmt && make lint && make typecheck && make test-unit && make test-integration && make test-contract` after each story.
5. Round-trip the migration (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`) per CLAUDE.md Rule #5 — verified in Story 1.1.

---

## Epic 1 — Foundations

Outcomes from this epic:
- New migration `0006_proposals_pr_url_idx` adds the partial B-tree index used by the webhook receiver's `lookup_proposal_by_pr_url`.
- New `Settings.relyloop_pr_poll_minutes` field with `.env.example` line.
- HMAC-SHA256 signature verifier + URL normalization helper in `backend/app/domain/git/` (alongside existing redaction + validation).
- Pure-domain event dispatcher (`event_type, payload → WebhookAction`).
- 7 new repo functions across `proposal.py` (5) + `config_repo.py` (2 — including the `lookup_config_repo_by_owner_repo` added in the cross-model review F4 patch).
- GitHub API call helpers extracted from `backend/workers/git_pr.py` to a shared module so Epic 3 + Epic 4 don't duplicate retry / rate-limit logic.

**Epic 1 gate:** `make test-unit` green; migration round-trips cleanly; ruff + mypy clean.

### Story 1.1 — Migration `0006_proposals_pr_url_idx` + Settings field

**Outcome:** New partial B-tree index `proposals_pr_url_idx` exists on `proposals(pr_url) WHERE pr_url IS NOT NULL`. The `Settings.relyloop_pr_poll_minutes` field is available (default 15, bounded 1..1440). `.env.example` documents the new env var.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0006_proposals_pr_url_idx.py` | Alembic migration: `op.create_index("proposals_pr_url_idx", "proposals", ["pr_url"], postgresql_where=sa.text("pr_url IS NOT NULL"))` + the matching `downgrade()`. |
| `backend/tests/integration/test_pr_url_index_migration.py` | Round-trip test: `upgrade head → downgrade -1 → upgrade head` leaves the index in pg_indexes; downgrade removes it. Mirror `test_clusters_migration.py` shape. |
| `backend/tests/unit/core/test_settings_pr_poll.py` | Verifies `Settings.relyloop_pr_poll_minutes` defaults to 15, validates `1 <= v <= 1440`, picks up `RELYLOOP_PR_POLL_MINUTES` env var override. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | Add `relyloop_pr_poll_minutes: int = Field(default=15, ge=1, le=1440, description="…")` between existing `relyloop_*` fields. |
| `.env.example` | Add one-line comment + `# RELYLOOP_PR_POLL_MINUTES=15`. |

**Endpoints**

None — infra story.

**Key interfaces**

```python
# Alembic migration revision identifiers
revision = "0006"
down_revision = "0005"

def upgrade() -> None:
    op.create_index(
        "proposals_pr_url_idx",
        "proposals",
        ["pr_url"],
        postgresql_where=sa.text("pr_url IS NOT NULL"),
    )

def downgrade() -> None:
    op.drop_index("proposals_pr_url_idx", table_name="proposals")
```

**Tasks**
1. Create `migrations/versions/0006_proposals_pr_url_idx.py` mirroring `0005_digests.py` header style (docstring, revision identifiers, upgrade/downgrade).
2. Add the Settings field with the exact bounds + description from the spec FR-4.
3. Update `.env.example`.
4. Write the two test files. Round-trip migration test asserts `pg_indexes.indexname = 'proposals_pr_url_idx'` exists post-upgrade and is gone post-downgrade. Settings test exercises default, override, lower-bound (`0` raises), upper-bound (`1441` raises).
5. Run `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`. Verify clean output.
6. Run `make fmt && make lint && make typecheck && make test-unit`.

**Definition of Done**
- [ ] `0006_proposals_pr_url_idx.py` exists at `migrations/versions/` with both `upgrade()` and `downgrade()`.
- [ ] Round-trip migration completes cleanly (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`).
- [ ] `Settings.relyloop_pr_poll_minutes` field present; default 15; bounds enforced.
- [ ] `.env.example` line added.
- [ ] `test_pr_url_index_migration.py` + `test_settings_pr_poll.py` green.
- [ ] `make fmt && make lint && make typecheck` clean.

### Story 1.2 — Signature verifier + URL normalization helpers

**Outcome:** Two pure-domain helpers exist in `backend/app/domain/git/`: `verify_webhook_signature(body, signature_header, secret)` returning `bool`, and `parse_repository_full_name(s) -> tuple[str, str] | None` for the GitHub-webhook `owner/repo` short form. The URL side (`config_repos.repo_url`) is parsed via the existing `validate_repo_url` per spec FR-1 (`docs/01_architecture/...` + `backend/app/domain/git/validation.py:37`). No `httpx`, no DB, no I/O — pure functions.

**Why two parsers, not one** (cross-model review F1): Spec FR-1 says "extract `{owner}/{repo}` from both sides via the same regex (`backend/app/domain/git/validation.py:validate_repo_url`)". `validate_repo_url`'s regex only matches `https://github.com/<owner>/<repo>[.git]` — it does NOT accept the bare `owner/repo` short form GitHub sends in `repository.full_name`. Rather than weaken `validate_repo_url` or duplicate its regex, this feature pairs `validate_repo_url(config_repo.repo_url)` (already enforced at registration) with a small `parse_repository_full_name` helper for the webhook payload side, then compares the two `(owner, repo)` tuples case-insensitively.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/git/webhook_signature.py` | `verify_webhook_signature(body: bytes, signature_header: str \| None, secret: str) -> bool`. Compares `sha256=<hex>` from header against `hmac.new(secret, body, sha256).hexdigest()` using `hmac.compare_digest`. Returns False on missing header / malformed prefix / mismatch / empty secret. |
| `backend/app/domain/git/repository_name.py` | `parse_repository_full_name(value: str) -> tuple[str, str] \| None`. Accepts only the canonical `owner/repo` short form GitHub emits in webhook payloads; rejects SSH URLs, HTTPS URLs, enterprise hosts, and malformed input by returning `None`. Tightly scoped — does NOT duplicate URL parsing. |
| `backend/tests/unit/domain/test_webhook_signature.py` | 8+ cases: valid signature, mismatched signature, missing header, malformed `sha256=` prefix, empty body, empty secret returns False, body-bytes vs body-str sanity, constant-time comparison asserted via `mock.patch('hmac.compare_digest')` spy. |
| `backend/tests/unit/domain/test_repository_name.py` | 10+ cases: canonical `owner/repo`, owner with hyphens, repo with dots, uppercase normalized to lowercase, leading/trailing whitespace stripped, malformed inputs return `None` (HTTPS URL form returns `None` — that's `validate_repo_url`'s job; SSH form returns `None`; just a slash; just an owner; empty string; three-segment `owner/repo/extra`). |
| `backend/tests/unit/domain/test_url_owner_repo_parity.py` | Cross-validates that `validate_repo_url("https://github.com/Foo/Bar.git")` and `parse_repository_full_name("foo/bar")` produce comparable `(owner, repo)` tuples when canonicalised (lowercased, `.git` stripped). Covers the spec §14 "trailing `.git` + https vs ssh + enterprise hosts" matrix as negative tests. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/git/__init__.py` | Re-export `verify_webhook_signature` + `parse_repository_full_name` alongside existing `redact_token` / `validate_repo_url` / `UnsupportedProviderError`. |

**Endpoints**

None — pure helpers.

**Key interfaces**

```python
# backend/app/domain/git/webhook_signature.py
import hmac
from hashlib import sha256


def verify_webhook_signature(body: bytes, signature_header: str | None, secret: str) -> bool:
    """Compare GitHub's `sha256=<hex>` header against HMAC-SHA256 of body.

    Returns True iff header is well-formed AND digest matches AND secret
    is non-empty. Uses `hmac.compare_digest` for constant-time comparison.
    """


# backend/app/domain/git/repository_name.py
def parse_repository_full_name(value: str) -> tuple[str, str] | None:
    """Parse GitHub's `repository.full_name` (`owner/repo`) form ONLY.

    Returns `(owner.lower(), repo.lower())` for the canonical short form;
    returns `None` for HTTPS URLs (use `validate_repo_url` for those),
    SSH URLs, enterprise hosts, or any non-canonical input.
    """


# Canonicalisation pattern used at the webhook router (Story 2.1):
#
#   owner_repo = parse_repository_full_name(payload["repository"]["full_name"])
#   if owner_repo is None:
#       raise _err(403, "INVALID_SIGNATURE", ...)
#   for cr in candidate_config_repos:
#       try:
#           if validate_repo_url(cr.repo_url) == owner_repo:
#               matched = cr
#               break
#       except UnsupportedProviderError:
#           continue  # bad registration — skip
```

**Tasks**
1. Write `webhook_signature.py` using `hmac.compare_digest`.
2. Write `repository_name.py`. Regex `^([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)/([a-z0-9._-]+?)(?:\.git)?$` against `value.strip().lower()`. Reject inputs containing `:` (SSH), `://` (URL), or `.` in the owner component.
3. Re-export both in `__init__.py`.
4. Write the three unit-test files (the parity file is a single fixture-driven test).
5. Run `make fmt && make lint && make typecheck && make test-unit`.

**Definition of Done**
- [ ] Both helpers exist, exported from `backend.app.domain.git`.
- [ ] 18+ unit tests across signature + repository-name files, plus the parity test cross-validating `validate_repo_url`/`parse_repository_full_name` produce comparable tuples.
- [ ] Coverage on both new modules ≥ 95% (pure logic, no fixtures needed).
- [ ] No second URL-parsing regex introduced — the URL side stays in `validate_repo_url` (spec FR-1 compliance).

### Story 1.3 — Event dispatcher (pure-domain)

**Outcome:** `backend/app/domain/git/webhook_dispatch.py` exists with `dispatch_event(event_type, payload) → WebhookDecision`. Pure function: no DB, no I/O. The dispatcher decides what `mark_proposal_pr_*` mutation the router should perform — it never sets `"unknown_pr"`. The router converts a `mutation`-requesting decision into the wire `"unknown_pr"` action when `lookup_proposal_by_pr_url` returns `None`. This split keeps the dispatcher pure (no DB) and gives the router a single deterministic override point.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/git/webhook_dispatch.py` | `WEBHOOK_ACTION_VALUES = frozenset({"applied", "noop", "unknown_pr", "ping"})` (the spec §8.4 source of truth — re-exported by the webhook router module in Story 2.1 so spec §8.4's grep cite at `backend/app/api/webhooks/github.py` also passes). `HANDLED_EVENT_TYPES = frozenset({"ping", "pull_request"})`. `WebhookDecision` dataclass; `dispatch_event(event_type, payload) → WebhookDecision`. |
| `backend/tests/unit/domain/test_webhook_dispatch.py` | One test per case in the spec FR-1 matrix: ping (action=ping, mutation=none), closed+merged=true (mutation=merged, action=applied), closed+merged=false (mutation=closed, action=applied), reopened (mutation=reopened, action=applied), opened/edited/synchronize/review_requested (action=noop, mutation=none), unknown event_type (action=noop, mutation=none). **Negative assertion**: `dispatch_event` never returns `action="unknown_pr"` (that's router-owned). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/git/__init__.py` | Re-export `WEBHOOK_ACTION_VALUES`, `HANDLED_EVENT_TYPES`, `WebhookDecision`, `dispatch_event`. |

**Endpoints**

None — pure helper.

**Key interfaces**

```python
# backend/app/domain/git/webhook_dispatch.py
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

WEBHOOK_ACTION_VALUES: frozenset[str] = frozenset({"applied", "noop", "unknown_pr", "ping"})
HANDLED_EVENT_TYPES: frozenset[str] = frozenset({"ping", "pull_request"})


@dataclass(frozen=True)
class WebhookDecision:
    # action emitted by the dispatcher — never "unknown_pr".
    action: Literal["applied", "noop", "ping"]
    pr_url: str | None
    pr_merged_at: datetime | None
    mutation: Literal["merged", "closed", "reopened", "none"]


def dispatch_event(event_type: str, payload: dict[str, Any]) -> WebhookDecision:
    """Decide the next mutation given a verified webhook payload.

    Returns a WebhookDecision. The router:
      - For `mutation in {merged, closed, reopened}`: calls
        `lookup_proposal_by_pr_url(decision.pr_url)`. If the proposal is
        found, invokes the matching `mark_proposal_pr_*` repo function and
        emits `{"status": "ok", "action": decision.action}` (i.e. "applied").
        If lookup returns None, the router OVERRIDES the wire action to
        `"unknown_pr"` and skips the mutation entirely.
      - For `mutation == "none"`: returns `{"status": "ok", "action": decision.action}`
        without any DB work (covers ping + noop branches).

    The dispatcher is pure-domain and has no DB session, so it MUST NOT
    emit `"unknown_pr"` — that translation is the router's job.
    """
```

**Tasks**
1. Write `webhook_dispatch.py` per the spec FR-1 matrix. `action` Literal excludes `"unknown_pr"` so static typing enforces the contract.
2. Write the unit-test file (~12 cases covering every branch). Each test asserts the exact `WebhookDecision` tuple. Include a `test_dispatcher_never_emits_unknown_pr` parametrised case covering all FR-1 branches.
3. Re-export in `__init__.py`.
4. Run `make fmt && make lint && make typecheck && make test-unit`.

**Definition of Done**
- [ ] `dispatch_event` returns the documented `WebhookDecision` for every action in spec FR-1.
- [ ] 12+ unit tests covering every branch + 1 negative assertion that `"unknown_pr"` is never emitted by the dispatcher.
- [ ] `WEBHOOK_ACTION_VALUES` + `HANDLED_EVENT_TYPES` frozensets are the source-of-truth for spec §8.4 (re-exported by `backend.app.api.webhooks.github` so the spec §8.4 cite at that path also passes a static grep).

### Story 1.4 — New proposal + config_repo repo functions

**Outcome:** 7 new repo functions exist with the documented conditional-UPDATE / SELECT contracts. (Was 6 before cross-model review F4 surfaced that the webhook receiver + polling worker + register_webhook worker all need a `lookup_config_repo_by_owner_repo` call that wasn't defined anywhere.)

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_proposal_repo_webhook.py` | Round-trip tests for `mark_proposal_pr_merged`, `mark_proposal_pr_closed`, `mark_proposal_pr_reopened`, `lookup_proposal_by_pr_url`, `list_pr_opened_proposals_for_reconcile`. Each function gets: happy path, wrong pre-state (returns None), boundary case (e.g. lookup-by-pr-url returns None on no match; list excludes proposals older than 90 days). |
| `backend/tests/integration/test_config_repo_repo_webhook.py` | Round-trip tests for (a) `set_webhook_registration_error` — UPDATE semantics + NULL-clears-the-column path; (b) `lookup_config_repo_by_owner_repo` — happy path (`https://github.com/foo/bar` and `https://github.com/foo/bar.git` both match `("foo", "bar")`), case-insensitive match, returns None when no row matches, returns None when the row is soft-deleted (`deleted_at IS NOT NULL`). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/proposal.py` | Add 5 new async functions: `mark_proposal_pr_merged`, `mark_proposal_pr_closed`, `mark_proposal_pr_reopened`, `lookup_proposal_by_pr_url`, `list_pr_opened_proposals_for_reconcile`. All mirror the `mark_proposal_pr_opened` (`:184`) conditional-UPDATE pattern. |
| `backend/app/db/repo/config_repo.py` | Add 2 new async functions: `set_webhook_registration_error(db, config_repo_id, error)` (UPDATE-only; `error=None` clears the column on subsequent successful retries) and `lookup_config_repo_by_owner_repo(db, owner, repo)` (single-row SELECT; canonicalises `config_repos.repo_url` via `validate_repo_url` then case-insensitive `(owner, repo)` compare; excludes soft-deleted rows). |

**Endpoints**

None — repo layer.

**Key interfaces**

```python
# backend/app/db/repo/proposal.py — new functions

async def mark_proposal_pr_merged(
    db: AsyncSession,
    proposal_id: str,
    *,
    pr_merged_at: datetime,
) -> Proposal | None:
    """Conditional UPDATE: pr_opened+open → pr_merged.

    WHERE status='pr_opened' AND pr_state='open'. Returns the row or
    None if zero rows matched (proposal was already merged via the
    other delivery path, or was rejected by the operator). Caller commits.
    """

async def mark_proposal_pr_closed(db: AsyncSession, proposal_id: str) -> Proposal | None:
    """Conditional UPDATE: pr_opened+open → pr_opened+closed.

    Status STAYS pr_opened so the operator can re-open_pr (spec §9
    state-transitions + §11 downstream-invariant audit). WHERE
    status='pr_opened' AND pr_state='open'. Returns row or None.
    """

async def mark_proposal_pr_reopened(db: AsyncSession, proposal_id: str) -> Proposal | None:
    """Conditional UPDATE: pr_opened+closed → pr_opened+open.

    WHERE status='pr_opened' AND pr_state='closed'. Returns row or None.
    """

async def lookup_proposal_by_pr_url(db: AsyncSession, pr_url: str) -> Proposal | None:
    """Single-row SELECT keyed on pr_url. Returns the row or None.

    Uses the partial index proposals_pr_url_idx (Story 1.1) — sub-millisecond
    even at 100K proposals.
    """

async def list_pr_opened_proposals_for_reconcile(db: AsyncSession) -> list[Proposal]:
    """Returns rows where status='pr_opened' AND pr_state='open' AND
    pr_url IS NOT NULL AND created_at > now() - interval '90 days'.

    Consumed by reconcile_pr_state (Story 3.1). 90-day cap avoids
    unbounded polling growth (spec FR-2).
    """

# backend/app/db/repo/config_repo.py — new functions

async def set_webhook_registration_error(
    db: AsyncSession,
    config_repo_id: str,
    error: str | None,
) -> ConfigRepo | None:
    """UPDATE config_repos SET webhook_registration_error = :error
    WHERE id = :id RETURNING *.

    Pass error=None to clear the column on a subsequent successful retry.
    Returns the row or None if the config_repo doesn't exist.
    """


async def lookup_config_repo_by_owner_repo(
    db: AsyncSession,
    owner: str,
    repo: str,
) -> ConfigRepo | None:
    """Locate a registered (non-deleted) config_repo by `(owner, repo)`.

    Canonicalises every candidate row's ``repo_url`` via ``validate_repo_url``
    and compares case-insensitively against the provided ``(owner, repo)``
    tuple. The webhook receiver (Story 2.1), polling reconciler (Story 3.1),
    and register-webhook worker (Story 4.1) all consume this.

    Returns the row or None. Excludes ``deleted_at IS NOT NULL`` rows.
    Rows whose ``repo_url`` no longer parses via ``validate_repo_url`` (e.g.
    historic non-GitHub URLs from before MVP1 hardening) are skipped silently.
    """
```

**Tasks**
1. Add the 5 proposal repo functions following the `mark_proposal_pr_opened` pattern exactly (conditional UPDATE, RETURNING, `await db.flush()`, return Optional[Proposal]).
2. Add `set_webhook_registration_error` + `lookup_config_repo_by_owner_repo` in `config_repo.py`.
3. Export the new functions from `backend/app/db/repo/__init__.py` `__all__`.
4. Write the two integration tests (mark `@pytest.mark.integration`). Each test uses the `db_session` fixture from `tests/integration/conftest.py` to insert fixture data, exercise the function, assert via fresh SELECT.
5. Run `make fmt && make lint && make typecheck && make test-integration`.

**Definition of Done**
- [ ] All 7 new repo functions exported and unit-typed.
- [ ] Integration tests cover: happy path, wrong pre-state returns None, lookup_by_pr_url returns None on miss, list_pr_opened excludes >90-day-old rows, `lookup_config_repo_by_owner_repo` happy path + case-insensitive + soft-deleted skip + no-match returns None.
- [ ] No new mypy errors.

### Story 1.5 — Extract + generalise shared GitHub API client

**Outcome:** GitHub HTTP helpers currently inlined in `backend/workers/git_pr.py` (the POST-only `_github_post` at `:593` plus `_parse_retry_after:655`, `_is_secondary_rate_limit:663`, `_body_mentions_rate_limit:670`, `_parse_rate_limit_reset:685`) move to `backend/app/git/github_client.py`. The polling reconciler (Story 3.1) needs `GET /repos/.../pulls/{n}` and `register_webhook` (Story 4.1) needs `GET /hooks` plus `POST /hooks`, so the move is **not** a pure rename — `_github_post`'s POST-only signature is generalised to a method-agnostic `github_request(client, method, url, *, json_body=None, token=...)`. The existing `_github_post` call sites keep working via a thin wrapper that calls `github_request(..., method="POST", ...)`; `feat_github_pr_worker`'s test suite is the regression gate.

**Namespace choice** (cross-model review F14): CLAUDE.md's documented repo structure lists `backend/app/git/` as the canonical home for Git provider clients ("MVP1: GitHub; MVP3: + GitLab + Bitbucket"). The earlier draft of this plan introduced `backend/app/integrations/github/`, which would have added a brand-new top-level layer not in CLAUDE.md. This story uses `backend/app/git/` instead.

**New files**

| File | Purpose |
|---|---|
| `backend/app/git/__init__.py` | Re-exports `github_request`, `parse_retry_after`, `is_secondary_rate_limit`, `body_mentions_rate_limit`, `parse_rate_limit_reset`, plus the per-attempt timeout/backoff constants the workers reference. |
| `backend/app/git/github_client.py` | Method-agnostic generalisation of `_github_post`: `github_request(client, method, url, *, json_body=None, token=...)` with the existing retry policy (RequestError + 5xx + 429 Retry-After + 403 secondary-rate-limit). The 4 inspection helpers (`parse_retry_after`, `is_secondary_rate_limit`, `body_mentions_rate_limit`, `parse_rate_limit_reset`) are public copies of today's private counterparts. |
| `backend/tests/unit/git/test_github_client.py` | Unit tests for retry policy via `httpx.MockTransport` (the codebase's actually-established mocking pattern — see `backend/tests/unit/adapters/test_request_retry.py:38`): 5xx triggers backoff, 403 with `X-RateLimit-Remaining: 0` retries, 403 with Retry-After retries, 403 with `"rate limit"` body retries, 403 with no retry signal returns immediately, 429 honours Retry-After, network error retries to budget, RequestError beyond budget propagates. **GET coverage**: parametrise over `method in {"GET", "POST"}` so the method-agnostic generalisation is exercised on both verbs. |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/git_pr.py` | Remove the inlined helpers (`_github_post:593`, `_parse_retry_after:655`, `_is_secondary_rate_limit:663`, `_body_mentions_rate_limit:670`, `_parse_rate_limit_reset:685` — range 593..690 inclusive). Add `from backend.app.git.github_client import github_request, ...`. Replace each `await _github_post(client, url, json_body=..., token=...)` call site with `await github_request(client, "POST", url, json_body=..., token=...)`. The 4 inspection helpers are no longer used directly by `git_pr.py` after the move — they live behind `github_request`'s retry loop now. |

**Endpoints**

None.

**Key interfaces**

```python
# backend/app/git/github_client.py
import httpx
from typing import Any

HTTP_TIMEOUT_S: float = 30.0
"""Default per-request httpx timeout for GitHub REST calls."""


async def github_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    token: str,
    max_retries: int = 3,
) -> httpx.Response:
    """Method-agnostic GitHub REST call with the retry policy from `_github_post`.

    Retries on RequestError + 5xx + 429 (Retry-After) + 403 secondary
    rate-limit (X-RateLimit-Remaining=0 OR Retry-After present OR body
    mentions `rate limit`/`abuse`). Terminal on other 4xx. Token is
    supplied by the caller and never logged (the existing
    `RedactTokensProcessor` strips PAT-format strings as a defense-in-
    depth; the helper itself never includes the token in any log call).
    Returns `httpx.Response` — caller checks `.status_code`.
    """
```

**Tasks**
1. Create the `backend/app/git/` package.
2. Copy the 5 existing helpers (`_github_post` + 4 inspection helpers) verbatim into `github_client.py`. Rename leading-underscore symbols to public names. Generalise `_github_post` → `github_request` by adding a `method` parameter and dropping the hardcoded `client.post(...)`.
3. Update `git_pr.py` to import + call `github_request`. Run the full `feat_github_pr_worker` test suite (`pytest backend/tests/ -k git_pr`) to confirm the refactor is behaviour-preserving for the POST path — these are the regression gate.
4. Write the new `test_github_client.py` covering each retry branch via `httpx.MockTransport`. Parametrise method ∈ {GET, POST} so the method-agnostic path is exercised.
5. Run `make fmt && make lint && make typecheck && make test-unit`.

**Definition of Done**
- [ ] `backend.app.git` package exists and re-exports `github_request` + the 4 inspection helpers.
- [ ] `git_pr.py` imports from the new module — `grep -n '_github_post\|_parse_retry_after\|_is_secondary_rate_limit\|_body_mentions_rate_limit\|_parse_rate_limit_reset' backend/workers/git_pr.py` returns no hits.
- [ ] Existing `feat_github_pr_worker` tests still green.
- [ ] New `test_github_client.py` adds ≥ 10 retry-policy cases × 2 methods (GET + POST) with `httpx.MockTransport`.
- [ ] `json_body=` keyword used consistently everywhere — `grep -n "json=" backend/app/git/ backend/workers/git_pr.py` returns no hits in the patched files.

---

## Epic 2 — Webhook receiver

Outcomes from this epic:
- `POST /webhooks/github` endpoint live at the API root (unprefixed per CLAUDE.md Rule #6 + api-conventions.md:14).
- Signature verification + repository lookup → signature mismatch / unknown repo → 403 `INVALID_SIGNATURE`.
- Event dispatch wires to the repo functions; 4 success actions produce the documented `{status: "ok", action: <…>}` body.
- Structlog logs every delivery (`event="webhook_received"`) with `delivery_id`, `event`, `action`, `proposal_id` (if matched), and `result` per spec §13 NFR-Operability. Failed signatures log at WARN with `delivery_id`. **The `result` field is the wire `action` string (`applied | noop | unknown_pr | ping`)** — same value as the response body so log + response stay consistent.

**Epic 2 gate:** AC-1, AC-2, AC-4, AC-5 pass. Synthetic webhook flips a proposal in <5s.

### Story 2.1 — Webhook router + handler + tests

**Outcome:** `backend/app/api/webhooks/github.py` exports a `router` mounted at `/webhooks/github`. The handler verifies the signature, looks up the proposal (if `pull_request.html_url` is present), dispatches via `dispatch_event`, calls the matching repo function (or no-op), and returns 200 with the documented body. Errors return 403 with the standard `_err()` envelope.

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/webhooks/__init__.py` | Package marker. |
| `backend/app/api/webhooks/github.py` | The webhook router. Single endpoint `POST /webhooks/github`. Reads raw body bytes (FastAPI `Request`), verifies signature, extracts `(owner, repo)` from `repository.full_name` via `parse_repository_full_name` (Story 1.2), resolves the matching `config_repos` row via `lookup_config_repo_by_owner_repo` (Story 1.4), reads `webhook_secret_ref` mounted secret, verifies signature, calls `dispatch_event` (Story 1.3), looks up the proposal by `pr_url` when `decision.mutation != "none"`, applies the matching `mark_proposal_pr_*` repo function (or overrides `action="unknown_pr"` if lookup returns None), commits, logs the structured `webhook_received` line with `result` field, returns 200. Single error path (signature fail / unknown repo) raises `_err(403, "INVALID_SIGNATURE", ...)`. **Re-exports `WEBHOOK_ACTION_VALUES`** from `backend.app.domain.git.webhook_dispatch` so spec §8.4's grep cite at this path also passes. |
| `backend/tests/integration/test_webhook_pr_merged.py` | AC-1 — merged. Builds a synthetic GitHub `pull_request` body, signs it with a known secret, POSTs to `/webhooks/github` via `async_client`, asserts `proposal.pr_state="merged"` + `pr_merged_at` populated + `status="pr_merged"` + response body `{status:"ok", action:"applied"}`. |
| `backend/tests/integration/test_webhook_pr_closed_unmerged.py` | **NEW** — covers FR-1 closed+merged=false branch (cross-model review B5). Asserts proposal transitions to `pr_state="closed"` while `status` stays `pr_opened` (per spec §11 downstream-invariant note), response body `{status:"ok", action:"applied"}`. |
| `backend/tests/integration/test_webhook_pr_reopened.py` | **NEW** — covers FR-1 reopened branch (cross-model review B5). Starts from `pr_state="closed"`, asserts transition back to `pr_state="open"`, response body `{status:"ok", action:"applied"}`. |
| `backend/tests/integration/test_webhook_pr_noop_actions.py` | **NEW** — parametrised over `pull_request` actions other than closed/reopened (`opened`, `edited`, `synchronize`, `review_requested`, `assigned`). Each returns 200 with `{status:"ok", action:"noop"}`. No DB mutation. |
| `backend/tests/integration/test_webhook_unknown_event.py` | **NEW** — `X-GitHub-Event: deployment_status` (or any unhandled event) returns 200 with `{status:"ok", action:"noop"}`. No DB mutation. |
| `backend/tests/integration/test_webhook_invalid_signature.py` | AC-2. Tests three failure modes (bad signature, missing signature header, unknown repo) all return 403 with `error_code: INVALID_SIGNATURE`. **`caplog` assertion**: every failure logs at WARN with `delivery_id` from the `X-GitHub-Delivery` header. |
| `backend/tests/integration/test_webhook_unknown_pr.py` | AC-5. Valid signature, valid repo, but `pull_request.html_url` doesn't match any proposal → 200 with `{status:"ok", action:"unknown_pr"}`. **`caplog` assertion**: `webhook_received` log line carries `result="unknown_pr"` + `proposal_id` absent or null. |
| `backend/tests/integration/test_webhook_ping.py` | AC-4. `X-GitHub-Event: ping` with valid signature → 200 with `{status:"ok", action:"ping"}`. No mutation. **`caplog` assertion**: `result="ping"`. |
| `backend/tests/integration/test_webhook_logging.py` | **NEW** — covers spec §13 NFR-Operability log fields end-to-end. For each of the 4 happy-path actions (applied, noop, unknown_pr, ping), assert the `webhook_received` log record contains `delivery_id`, `event`, `action`, `result`, and `proposal_id` (None for unknown_pr / ping). Uses pytest's `caplog` + structlog's testing helpers. |
| `backend/tests/contract/test_webhook_api_contract.py` | Static contract: (a) the webhook endpoint is registered in OpenAPI; (b) handler source re-exports `WEBHOOK_ACTION_VALUES` (the response-shape source of truth — both the dispatch module and the router module pass the spec §8.4 grep); (c) handler raises only `INVALID_SIGNATURE` (negative-grep against the §8.5 catalog); (d) handler source does NOT reference the webhook secret string in any log call (`grep -n 'webhook_secret_ref' backend/app/api/webhooks/github.py` returns 0 hits in log call sites). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Add `from backend.app.api.webhooks import github as webhook_github_router` import; `app.include_router(webhook_github_router.router)` (no prefix — same exception as `health.router` at `:148`). |

**Endpoints consumed / produced**

| Method | Path | Request body | Headers (consumed) | Success response | Error codes |
|---|---|---|---|---|---|
| `POST` | `/webhooks/github` | GitHub webhook payload (JSON; see https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request) | `X-Hub-Signature-256`, `X-GitHub-Event`, `X-GitHub-Delivery` | 200 with `{"status":"ok", "action": "applied"\|"noop"\|"unknown_pr"\|"ping"}` | 403 `INVALID_SIGNATURE` (signature mismatch OR unknown repo). 5xx errors are framework-level (Postgres write failure surfaces via FastAPI's default exception handler → GitHub retries per spec §4); they do not appear in spec §8.5 and are not feature-specific. |

**Pydantic schemas**

None — this endpoint accepts free-form GitHub webhook JSON (we don't validate the full schema since GitHub adds fields over time). The handler reads only the specific fields it needs (`repository.full_name`, `pull_request.html_url`, `pull_request.merged`, `pull_request.merged_at`, `action`) with explicit `.get()` defaults + bail-to-noop on missing fields.

**Key interfaces**

```python
# backend/app/api/webhooks/github.py
from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.post("/github", status_code=status.HTTP_200_OK)
async def github_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Receive a GitHub webhook event.

    Order of operations:
      1. Read raw body bytes (NEEDED for HMAC verification).
      2. Parse JSON; extract repository.full_name via parse_repository_full_name.
      3. Look up the config_repo via lookup_config_repo_by_owner_repo. If no
         match → 403 INVALID_SIGNATURE (don't reveal repo enumeration).
      4. Read the webhook_secret_ref mounted secret.
      5. Verify HMAC-SHA256 against X-Hub-Signature-256. Mismatch → 403.
      6. Dispatch via dispatch_event(X-GitHub-Event, payload). The
         dispatcher returns a WebhookDecision with action ∈ {applied,
         noop, ping} — it NEVER returns unknown_pr (router-only).
      7. If decision.mutation != "none":
           a. Look up proposal by decision.pr_url.
           b. If found, call the matching mark_proposal_pr_* repo function
              and `await db.commit()`. wire_action = decision.action ("applied").
           c. If NOT found, OVERRIDE wire_action = "unknown_pr"; do NOT
              mutate the DB.
         Else (mutation == "none"): wire_action = decision.action.
      8. Log structured event: logger.info(
             "webhook_received",
             delivery_id=request.headers.get("X-GitHub-Delivery"),
             event=event_type,
             action=wire_action,
             proposal_id=proposal.id if proposal else None,
             result=wire_action,   # spec §13 NFR field
         ).
         On 403 (steps 3 or 5): logger.warning("webhook_invalid_signature",
             delivery_id=..., event=..., reason="bad_signature"|"unknown_repo").
      9. Return {"status": "ok", "action": wire_action}.

    Forbidden in this handler: synchronous calls to GitHub, anything that
    blocks >500ms, anything that logs the webhook secret.
    """
```

**Tasks**
1. Create `backend/app/api/webhooks/` package + `github.py` with the handler per spec FR-1. Re-export `WEBHOOK_ACTION_VALUES` from the domain dispatch module so spec §8.4's grep cite at this path passes.
2. Read raw body via `await request.body()` BEFORE any JSON parsing (HMAC needs the exact bytes GitHub sent).
3. Wire `_err()` helper (copy from `backend/app/api/v1/clusters.py:73` per the project's deferred-hoist note — `_err()` exists in 7 routers today; webhook router copies the same shape, no shared hoist in this PR).
4. Register the router in `main.py` (the router itself carries `prefix="/webhooks"`; `app.include_router(...)` is called without an extra prefix — final mount is `/webhooks/github`).
5. Implement the 9 steps in the docstring above. Step 7's `wire_action = "unknown_pr"` override is the ONLY place that string is produced — assert this via a unit test on the router module.
6. Static-grep audits at the bottom of the contract test: (a) `WEBHOOK_ACTION_VALUES` is re-exported from `backend.app.api.webhooks.github` (source-of-truth tie-back to spec §8.4); (b) the only error_code raised by the router is `INVALID_SIGNATURE` (negative grep over the spec §8.5 catalog); (c) no log call site in the router references `webhook_secret_ref` (no secret leakage).
7. Write the 9 integration tests (`pr_merged`, `pr_closed_unmerged`, `pr_reopened`, `pr_noop_actions`, `unknown_event`, `invalid_signature`, `unknown_pr`, `ping`, `logging`) + 1 contract test.
8. Run the full quality gate: `make fmt && make lint && make typecheck && make test-unit && make test-integration && make test-contract`.

**Definition of Done**
- [ ] `POST /webhooks/github` registered + visible in `GET /openapi.json`.
- [ ] AC-1 (merged → state flips < 5s), AC-2 (403 on bad sig OR unknown repo), AC-4 (ping → 200 action=ping), AC-5 (unknown PR → 200 action=unknown_pr) all green.
- [ ] FR-1 closed+unmerged, reopened, noop (other actions), and unknown_event branches each exercised by an integration test asserting DB state + response body.
- [ ] Contract test asserts all 4 `WEBHOOK_ACTION_VALUES` returned for the 4 happy paths.
- [ ] Structured log line `webhook_received` carries `delivery_id`, `event`, `action`, `proposal_id`, `result` for every handled delivery (asserted in `test_webhook_logging.py`).
- [ ] Failed signatures log at WARN with `delivery_id` (asserted in `test_webhook_invalid_signature.py`).
- [ ] No `webhook_secret_ref` content appears in any log line (static grep audit in the contract test).
- [ ] Synthetic webhook smoke test (in the integration suite) flips a proposal in <5s on a developer laptop.

---

## Epic 3 — Polling reconciler

Outcomes from this epic:
- `reconcile_pr_state` Arq cron job runs every `RELYLOOP_PR_POLL_MINUTES` (default 15) minutes.
- Each tick lists `pr_opened` + `open` proposals (90-day cap), polls GitHub for the current state, and updates via `mark_proposal_pr_merged` / `mark_proposal_pr_closed`.
- 404, 5xx, 401/403 from GitHub all log at WARN and leave the proposal unchanged (next tick retries).

**Epic 3 gate:** AC-3 + AC-8 pass.

### Story 3.1 — `reconcile_pr_state` Arq cron job + WorkerSettings wiring + tests

**Outcome:** `backend/workers/pr_reconcile.py:reconcile_pr_state` exists and is registered via `WorkerSettings.cron_jobs` with the cron parameters derived from `Settings.relyloop_pr_poll_minutes`. The job completes in <60s for ≤100 proposals. **Cron derivation honours both intra-hour (n ≤ 60, divisor of 60) and multi-hour (n > 60, multiple of 60, divisor of 1440) values** — earlier draft silently snapped any n > 60 to the 15-minute default (cross-model review F3 / A4).

**New files**

| File | Purpose |
|---|---|
| `backend/workers/pr_reconcile.py` | The Arq job function. Reads the list of candidate proposals, looks up the per-repo PAT, calls `GET /repos/{o}/{r}/pulls/{n}` via the shared GitHub client, applies the matching `mark_proposal_pr_*` repo function. |
| `backend/tests/unit/workers/test_poll_cron_kwargs.py` | Unit test for the `_poll_cron_kwargs()` helper. Covers all 18 supported values (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440), asserts every unsupported value (7, 8, 9, 11, …, 90, 100, …) falls back to the 15-minute default with a WARN log line. |
| `backend/tests/integration/test_polling_reconciler.py` | Mocks the shared GitHub client via `httpx.MockTransport` (the codebase's established pattern — `pytest-recording` cassettes are NOT yet established here despite the dep being installed; `feat_github_pr_worker` deferred its cassette tests per `state.md`). AC-3 happy paths: 200/merged, 200/state=closed+merged=false, 200/state=open. AC-3 error paths: 404 (no mutation, WARN logged with `delivery_id`-like correlation field), 401 (WARN, no mutation), 403 (WARN, no mutation), 5xx (WARN, no mutation), `httpx.RequestError` after retry budget exhaustion (WARN, no mutation), 429 (the job logs WARN and short-circuits the remaining proposals per spec §10). AC-8: 50 candidate proposals × stubbed 200 responses complete in <30s; `caplog` asserts ≤ 60 HTTP attempts (50 + a few retries) per spec AC-8. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | (already added in Story 1.1) — Story 3.1 narrows the `relyloop_pr_poll_minutes` field validator to the supported set via a Pydantic `field_validator` that rejects values outside `{1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440}` with a clear error message. **This narrowing is a coordinated spec patch** — see the spec-patch note in §11. |
| `backend/workers/all.py` | Add `from backend.workers.pr_reconcile import reconcile_pr_state` import. Add `cron_jobs: list[Any] = [cron(reconcile_pr_state, **_poll_cron_kwargs())]` attribute on `WorkerSettings`. Add `from arq import cron` (the canonical import; `arq.cron.cron` is re-exported at top level). Add helper `_poll_cron_kwargs()`. |

**Endpoints**

None.

**Key interfaces**

```python
# backend/workers/pr_reconcile.py
from typing import Any
import httpx
from backend.app.git.github_client import github_request

async def reconcile_pr_state(ctx: dict[str, Any]) -> dict[str, int]:
    """Periodic reconciliation of pr_state for stale-pr_opened proposals.

    Returns a summary dict {reconciled: N, unchanged: N, errored: N,
    rate_limited: N} for observability (logged at INFO).

    Each candidate proposal:
      1. Parse {owner, repo, number} from pr_url.
      2. Look up the config_repo's auth_ref → read PAT from ./secrets/{auth_ref}.
      3. github_request(client, "GET", "/repos/{o}/{r}/pulls/{n}", token=<PAT>).
      4. If 200: branch on response body (merged/state).
      5. If 404: log WARN, leave proposal alone.
      6. If 401/403/5xx: log WARN, leave proposal alone.
      7. If 429: log WARN with `x-ratelimit-reset` header, mark rate_limited++,
         and BREAK the proposal loop (spec §10 — skip remaining; next tick retries).
      8. If `httpx.RequestError` (network error after retry budget exhausted):
         log WARN, leave proposal alone, continue to next.

    No in-job retry loop — the cron tick is the retry. Idempotent: a
    no-op on a stable proposal is cheap.
    """


# backend/workers/all.py — additions
from arq import cron

# 18 supported values — every divisor of 60 (≤60min cadence) plus every
# multiple of 60 up to 1440 that divides 1440 (multi-hour cadence). Earlier
# draft only covered the divisor-of-60 set, silently snapping n=120/240/720/1440
# to the 15-min default (cross-model review F3).
_SUPPORTED_POLL_MINUTES: frozenset[int] = frozenset(
    {1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440}
)
_FALLBACK_POLL_MINUTES: int = 15


def _poll_cron_kwargs() -> dict[str, Any]:
    """Translate Settings.relyloop_pr_poll_minutes into arq.cron(...) kwargs.

    Returns dict suitable for `cron(reconcile_pr_state, **kwargs)`:
      - n ≤ 60 (divisor of 60): {"minute": set(range(0, 60, n))}
      - n > 60 (multiple of 60, divides 1440): {"hour": set(range(0, 24, n//60)),
        "minute": {0}}
    Unsupported values fall back to the 15-min default with a WARN log
    (operator gets documented default behaviour rather than silent breakage).
    """
    n = get_settings().relyloop_pr_poll_minutes
    if n not in _SUPPORTED_POLL_MINUTES:
        log.warning("pr_poll_minutes_unsupported", configured=n,
                    falling_back_to=_FALLBACK_POLL_MINUTES,
                    supported=sorted(_SUPPORTED_POLL_MINUTES))
        n = _FALLBACK_POLL_MINUTES
    if n <= 60:
        return {"minute": set(range(0, 60, n))}
    return {"hour": set(range(0, 24, n // 60)), "minute": {0}}


class WorkerSettings:
    functions: list[Any] = [...]  # existing
    cron_jobs: list[Any] = [cron(reconcile_pr_state, **_poll_cron_kwargs())]
```

**Tasks**
1. Implement `pr_reconcile.py` per the docstring above. Use `github_request` from Story 1.5 (note: `github_request`, not `call_github_api` — the earlier draft used a name that didn't exist; see Story 1.5).
2. Add `cron_jobs` slot + `_poll_cron_kwargs()` helper to `WorkerSettings`. Narrow the `relyloop_pr_poll_minutes` Settings validator to the 18 supported values (coordinated spec patch — see §11).
3. PAT resolution: read `./secrets/{config_repo.auth_ref}` via the existing pattern from `feat_github_pr_worker` Story 1.4. If a helper extraction is warranted, place it at `backend/app/git/secrets.py` (the canonical `backend/app/git/` namespace per Story 1.5) — but prefer inline reads if it's a one-line `(Path("./secrets") / auth_ref).read_text().strip()`.
4. Write `test_poll_cron_kwargs.py` (unit) + `test_polling_reconciler.py` (integration via `httpx.MockTransport` — see Story 1.5 rationale on why MockTransport is the established pattern).
5. Run `make fmt && make lint && make typecheck && make test-unit && make test-integration`.

**Definition of Done**
- [ ] `reconcile_pr_state` registered in `WorkerSettings.cron_jobs` via `_poll_cron_kwargs()`.
- [ ] `_poll_cron_kwargs()` honours all 18 supported `relyloop_pr_poll_minutes` values (unit test); falls back with WARN on unsupported values.
- [ ] Integration tests cover the 7 response paths (200/merged, 200/closed+unmerged, 200/open, 404, 401, 403, 5xx) plus 429-skip-remaining and `RequestError`-after-budget.
- [ ] AC-3 passes (a proposal whose webhook delivery was simulated-missed gets reconciled within the cron tick).
- [ ] AC-8 passes (50 candidate proposals complete in <30s; ≤ 60 HTTP attempts).

---

## Epic 4 — Webhook auto-registration + docs

Outcomes from this epic:
- `register_webhook` Arq worker creates a GitHub hook (idempotent via `GET /hooks` pre-check).
- `POST /api/v1/config-repos` enqueues `register_webhook` post-commit when `webhook_secret_ref` is populated.
- Failures populate `config_repos.webhook_registration_error` (visible to operators via `GET /api/v1/config-repos/{id}` — the existing endpoint already returns the column).
- Runbook + docs updates (CLAUDE.md status flip, state.md recent-changes entry, US-20/US-21 marked Implemented).

**Epic 4 gate:** AC-6 + AC-7 pass. Runbook merged.

### Story 4.1 — `register_webhook` Arq worker

**Outcome:** `backend/workers/register_webhook.py:register_webhook` exists and is registered in `WorkerSettings.functions`. The job is idempotent: calling it twice for the same config_repo does NOT create duplicate hooks. All four failure classes the spec calls out (4xx-no-scope, 422-bad-payload, 5xx-GitHub-down, network-timeout) populate `config_repos.webhook_registration_error` and do not raise — cross-model review B3.

**New files**

| File | Purpose |
|---|---|
| `backend/workers/register_webhook.py` | The Arq job function. Steps: (1) load config_repo by id; (2) call `GET /repos/{o}/{r}/hooks?per_page=100` via shared client; (3) parse `config.url == "{RELYLOOP_BASE_URL}/webhooks/github"` matching hooks; (4) if a match exists, skip create + clear any prior `webhook_registration_error`; (5) else `POST /repos/{o}/{r}/hooks` with the spec FR-3 payload; (6) on success, clear `webhook_registration_error`; (7) on failure (4xx / 5xx / `httpx.RequestError` propagated from `github_request` after retries), call `set_webhook_registration_error(db, config_repo.id, "<short human-readable message>")`. The handler MUST NOT raise — failures are recorded in the column for the operator to see. |
| `backend/tests/integration/test_register_webhook_worker.py` | AC-6 (happy path: no existing hook → create succeeds → error column NULL). AC-6.5 (dedup: existing hook → skip create → error column NULL). AC-7 (404 from GitHub → row created, error populated with the PAT-scope message). **NEW** (cross-model review B3): AC-7.422 (422 from GitHub → error column populated with the documented validation message); AC-7.5xx (5xx after retry budget exhausted → error column populated with the "GitHub returned 503 — transient" message); AC-7.network (`httpx.RequestError` after retry budget → error column populated with the "GitHub unreachable — network error" message). |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/all.py` | Add `register_webhook` to `WorkerSettings.functions`. |

**Endpoints**

None.

**Key interfaces**

```python
# backend/workers/register_webhook.py
async def register_webhook(ctx: dict[str, Any], config_repo_id: str) -> dict[str, str]:
    """Idempotent webhook creation against GitHub for a single config_repo.

    Returns {status: "created" | "exists" | "failed"} for observability.

    Steps (per spec FR-3):
      1. Load config_repo; if webhook_secret_ref is NULL → "skipped" (shouldn't enqueue but defensive).
      2. Extract (owner, repo) from config_repo.repo_url.
      3. Read PAT from ./secrets/{config_repo.auth_ref}.
      4. Read webhook_secret content from ./secrets/{config_repo.webhook_secret_ref}.
      5. GET /repos/{o}/{r}/hooks?per_page=100; scan for config.url == "{RELYLOOP_BASE_URL}/webhooks/github".
      6. If found: set_webhook_registration_error(None) + return {"status":"exists"}.
      7. Else: POST /repos/{o}/{r}/hooks with the spec payload.
         - 2xx: set_webhook_registration_error(None) + return {"status":"created"}.
         - non-2xx: set_webhook_registration_error("GitHub returned XYZ — <reason>") + return {"status":"failed"}.
    """
```

**Tasks**
1. Implement `register_webhook.py` per the docstring. Wrap the `github_request` calls in a `try/except httpx.RequestError` so network-after-retries failures resolve to a `set_webhook_registration_error` call rather than propagating to Arq's retry loop (the column is the durable signal; Arq retries would just churn the same error).
2. Register in `WorkerSettings.functions` next to existing functions like `open_pr`.
3. Mock the 5 paths via `httpx.MockTransport` (the established pattern — see Story 1.5 / Story 3.1 rationale on why MockTransport, not pytest-recording cassettes): no-existing-hook (201 on POST), existing-hook (200 on GET, no POST), 404 on POST, 422 on POST, 503 after retries on POST, `httpx.RequestError` after retries on POST.
4. Run the quality gate.

**Definition of Done**
- [ ] AC-6 passes: happy path config-repo create → worker creates hook → `webhook_registration_error` is NULL.
- [ ] Dedup: re-enqueue the same job → worker finds the existing hook → no second `POST /hooks` call.
- [ ] AC-7 passes for **all four** failure classes (404, 422, 5xx-after-retries, network-after-retries) → `webhook_registration_error` populated with the documented per-class message; worker returns `{"status": "failed"}` without raising.
- [ ] Token never appears in any log line (covered by the existing `RedactTokensProcessor` chain).

### Story 4.2 — Extend `POST /api/v1/config-repos` to enqueue post-commit

**Outcome:** `POST /api/v1/config-repos` (in `backend/app/api/v1/config_repos.py`) now enqueues `register_webhook` after the existing DB commit when the new row has `webhook_secret_ref IS NOT NULL`. The route's response shape and 201 status code are unchanged. **Enqueue failure (Redis down, Arq pool absent, network blip) does NOT break the 201 response** — the failure is logged at WARN and the operator gets the documented "register_webhook didn't run; re-enqueue manually" path in the runbook (cross-model review B2 + AC-7 contract).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_config_repos_extension.py` | Asserts: (a) existing happy-path response shape on `POST /api/v1/config-repos` is unchanged (status 201, body shape per `ConfigRepoDetail`); (b) when `webhook_secret_ref` is populated, the job is enqueued (mock `app.state.arq_pool.enqueue_job` and assert called once with `register_webhook` + the config_repo id); (c) when `webhook_secret_ref` is NULL, the job is NOT enqueued; (d) when `app.state.arq_pool` is absent (Redis-down test fixture), the route still returns 201 + the WARN log line carries `event="register_webhook_enqueue_skipped_no_pool"`; (e) when `enqueue_job` raises (mock-raises), the route still returns 201 + the WARN log line carries `event="register_webhook_enqueue_failed"` with the exception class. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/config_repos.py` | After the existing `await db.commit()` in the create handler, if the new row's `webhook_secret_ref is not None`, fetch the Arq pool from `request.app.state` (the established pattern — see `backend/app/api/v1/proposals.py:516`, `studies.py:167`, `judgments.py:158`) and call `arq_pool.enqueue_job(...)` inside a `try/except` that swallows the exception, logs at WARN, and falls through to the 201 response. The `_job_id` ensures dedup against concurrent re-tries (mirrors the `feat_github_pr_worker` `open_pr` deterministic job id pattern). |

**Endpoints**

(unchanged — extending existing route)

| Method | Path | Behavior change |
|---|---|---|
| `POST` | `/api/v1/config-repos` | After commit: if `webhook_secret_ref IS NOT NULL`, enqueue `register_webhook` Arq job (best-effort). Response shape + 201 status unchanged regardless of enqueue outcome. |

**Key interfaces**

```python
# backend/app/api/v1/config_repos.py — handler change (excerpt)
@router.post("/config-repos", status_code=201, response_model=ConfigRepoDetail)
async def create_config_repo(
    body: CreateConfigRepoRequest,
    request: Request,                                # NEW — access app.state.arq_pool
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigRepoDetail:
    # ... existing create logic + db.commit() ...

    # NEW: post-commit best-effort enqueue for webhook auto-registration.
    # Earlier draft used `Depends(get_arq_pool)` — that factory does NOT exist
    # in the codebase. The established pattern (proposals.py:516, studies.py:167,
    # judgments.py:158) is `getattr(request.app.state, "arq_pool", None)`.
    if new_row.webhook_secret_ref is not None:
        arq_pool = getattr(request.app.state, "arq_pool", None)
        if arq_pool is None:
            logger.warning(
                "register_webhook_enqueue_skipped_no_pool",
                config_repo_id=new_row.id,
            )
        else:
            try:
                await arq_pool.enqueue_job(
                    "register_webhook",
                    new_row.id,
                    _job_id=f"register_webhook:{new_row.id}",
                )
            except Exception as exc:  # noqa: BLE001 — best-effort enqueue
                logger.warning(
                    "register_webhook_enqueue_failed",
                    config_repo_id=new_row.id,
                    exc_type=type(exc).__name__,
                )

    return _to_detail(new_row)
```

**Tasks**
1. Add the `request: Request` parameter + the post-commit best-effort enqueue block to the create handler (note: `Request` import is from `fastapi` — already imported in the existing file? confirm at impl time; mirror `proposals.py:497` which imports `Request`).
2. Read the existing test file for the `POST /config-repos` route to ensure the response shape contract is preserved — write the new test as an extension, not a replacement.
3. Mock the Arq pool by setting `app.state.arq_pool = MagicMock()` in the test fixture (mirror the pattern in `tests/integration/test_proposals_open_pr.py` from `feat_github_pr_worker`).
4. Run the quality gate.

**Definition of Done**
- [ ] Existing `test_config_repos_*` tests still green (no contract regression).
- [ ] New `test_config_repos_extension.py` covers the 5 cases above (happy path; ref populated; ref null; pool absent; enqueue raises).
- [ ] No new endpoint in the `OpenAPI` schema (this is a behavior extension, not a contract change).
- [ ] Static-grep audit: `grep -n 'get_arq_pool' backend/app/api/v1/config_repos.py` returns 0 hits (no fictional `Depends()` factory).

### Story 4.3 — Runbook + docs + state flips

**Outcome:** Operators have a clear playbook for diagnosing failed webhook deliveries; US-20/US-21 are marked Implemented; CLAUDE.md feature-status row flips; state.md gets a recent-changes entry.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/webhook-debugging.md` | Operator playbook: (1) Inspect last delivery via GitHub's webhook delivery panel; (2) Re-fire a webhook (GitHub provides a "Redeliver" button); (3) Verify our log line for the delivery via `make logs \| rg "webhook_received"`; (4) Rotate webhook secret (procedure: update GitHub side, update RelyLoop's mounted secret, restart api container); (5) Force-reconcile a specific proposal (run the cron tick manually via `arq backend.workers.all.WorkerSettings --queue-name arq:queue --burst` after enqueuing `reconcile_pr_state`); (6) Polling reconciler not running (`docker compose logs worker \| rg "reconcile_pr_state"`); (7) `register_webhook` failed paths and their fixes (PAT scope, network reachability of `RELYLOOP_BASE_URL` from GitHub). |

**Modified files**

| File | Change |
|---|---|
| `docs/03_runbooks/README.md` | Index entry for `webhook-debugging.md`. |
| `docs/02_product/mvp1-user-stories.md` | Flip US-20 + US-21 from "Planned" / no-status → "Implemented — feat_github_webhook". |
| `CLAUDE.md` | Flip row 8 (feat_github_webhook) from "Spec approved, plan pending" → "Complete (PR #N, merged YYYY-MM-DD)" at finalization. |
| `state.md` | Add a recent-changes entry summarizing the feature; flip the "in flight" line; note Alembic head moved `0005 → 0006`. |

**Tasks**
1. Write the runbook.
2. Add the index entry.
3. Flip US-20/US-21 status lines.
4. The CLAUDE.md + state.md updates happen at finalization (after PR #N number is known) — included here for completeness.

**Definition of Done**
- [ ] Runbook merged at `docs/03_runbooks/webhook-debugging.md` with all 7 sections.
- [ ] US-20/US-21 marked Implemented.
- [ ] state.md + CLAUDE.md updates land in the finalization commit.

---

## 3) Testing workstream

### 3.1 Unit tests (`backend/tests/unit/`)

- [ ] `domain/test_webhook_signature.py` — 8+ cases (Story 1.2)
- [ ] `domain/test_repository_name.py` — 10+ cases (Story 1.2)
- [ ] `domain/test_url_owner_repo_parity.py` — cross-validate `validate_repo_url` + `parse_repository_full_name` produce comparable tuples; SSH + enterprise hosts as negative cases (Story 1.2)
- [ ] `domain/test_webhook_dispatch.py` — 12+ cases covering FR-1 matrix + 1 negative `dispatcher_never_emits_unknown_pr` parametrised case (Story 1.3)
- [ ] `core/test_settings_pr_poll.py` — Settings field default/override/bounds + the 18 supported-values whitelist (Story 1.1 + tightening in Story 3.1)
- [ ] `git/test_github_client.py` — ≥ 10 retry-policy cases × 2 methods (GET + POST) via `httpx.MockTransport` (Story 1.5)
- [ ] `workers/test_poll_cron_kwargs.py` — `_poll_cron_kwargs()` covers all 18 supported values + fallback path (Story 3.1)

### 3.2 Integration tests (`backend/tests/integration/`)

- [ ] `test_pr_url_index_migration.py` — round-trip migration (Story 1.1)
- [ ] `test_proposal_repo_webhook.py` — 5 new proposal repo functions (Story 1.4)
- [ ] `test_config_repo_repo_webhook.py` — `set_webhook_registration_error` + `lookup_config_repo_by_owner_repo` (Story 1.4)
- [ ] `test_webhook_pr_merged.py` — AC-1 (Story 2.1)
- [ ] `test_webhook_pr_closed_unmerged.py` — closed+merged=false branch (Story 2.1)
- [ ] `test_webhook_pr_reopened.py` — reopened branch (Story 2.1)
- [ ] `test_webhook_pr_noop_actions.py` — other PR actions parametrised (Story 2.1)
- [ ] `test_webhook_unknown_event.py` — unknown X-GitHub-Event (Story 2.1)
- [ ] `test_webhook_invalid_signature.py` — AC-2 + WARN log assertion (Story 2.1)
- [ ] `test_webhook_unknown_pr.py` — AC-5 + result-field log assertion (Story 2.1)
- [ ] `test_webhook_ping.py` — AC-4 + result-field log assertion (Story 2.1)
- [ ] `test_webhook_logging.py` — spec §13 NFR-Operability log fields end-to-end (Story 2.1)
- [ ] `test_polling_reconciler.py` — AC-3 + AC-8 + 401/403/5xx/network/429 paths (Story 3.1)
- [ ] `test_register_webhook_worker.py` — AC-6, AC-6.5 (dedup), AC-7 across 404/422/5xx/network (Story 4.1)
- [ ] `test_config_repos_extension.py` — contract preservation + enqueue behaviour across happy path / pool-absent / enqueue-raises (Story 4.2)

### 3.3 Contract tests (`backend/tests/contract/`)

- [ ] `test_webhook_api_contract.py` — webhook endpoint registered in OpenAPI; success body matches `{status, action}`; failure body matches `_err()` envelope; static-grep audits on (a) `WEBHOOK_ACTION_VALUES` re-exported from `backend.app.api.webhooks.github`, (b) only `INVALID_SIGNATURE` raised by the router, (c) no `webhook_secret_ref` log-call sites (Story 2.1)

### 3.4 E2E tests

N/A in MVP1. This feature has no UI surface (`feat_proposals_ui` will display `pr_state` once it ships).

### 3.5 CI gates

- [ ] `make test-unit && make test-integration && make test-contract` — all green.
- [ ] `make lint && make typecheck` — clean.
- [ ] `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` — round-trip clean.
- [ ] Coverage: ≥80% on `backend/app/api/webhooks/`, `backend/workers/pr_reconcile.py`, `backend/workers/register_webhook.py`, `backend/app/git/`.

---

## 4) Documentation update workstream

### 4.1 Architecture docs

- [ ] `docs/01_architecture/apply-path.md` — already references the webhook + polling architecture (spec §15); confirm the implementation matches; patch if any divergence.

### 4.2 Product docs

- [ ] `docs/02_product/mvp1-user-stories.md` — mark US-20 + US-21 Implemented (Story 4.3).

### 4.3 Runbooks

- [ ] `docs/03_runbooks/webhook-debugging.md` — new (Story 4.3).
- [ ] `docs/03_runbooks/README.md` — index entry (Story 4.3).

### 4.4 Security docs

- [ ] No changes — the existing `docs/04_security/github-token-handling.md` already covers the per-repo PAT + webhook secret storage model. Confirm at implementation time that no new redaction patterns are needed (webhook secrets are operator-chosen — they're never logged because the handler never echoes them).

### 4.5 Core context files

- [ ] `state.md` — recent-changes entry + flip in-flight (Story 4.3 at finalization).
- [ ] `CLAUDE.md` — flip row 8 feature-status (Story 4.3 at finalization).

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Extract the inlined GitHub HTTP helpers from `backend/workers/git_pr.py` (lines 593–690 — `_github_post` + 4 inspection helpers) to `backend/app/git/github_client.py` so this feature's new workers (`pr_reconcile`, `register_webhook`) don't duplicate the retry / rate-limit logic. Generalise `_github_post` to a method-agnostic `github_request` so the polling reconciler's `GET /pulls/{n}` and the register-webhook worker's `GET /hooks` share the same retry envelope.

### 5.2 Planned refactor tasks

- [ ] Story 1.5 — Extract shared GitHub API client. Behavior-preserving; `feat_github_pr_worker`'s existing tests are the regression gate.

### 5.3 Refactor guardrails

- [ ] No expansion of refactor scope into other workers (`generate_judgments_llm`, `generate_digest`) in this feature — capture for a follow-up if needed.
- [ ] No rename of public symbols inside `git_pr.py` other than the helper imports.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `infra_foundation` | All stories | Complete (PR #4) | Build/lint/test toolchain broken |
| `infra_adapter_elastic` | All stories using `config_repos.webhook_secret_ref` / `webhook_registration_error` | Complete (PR #16) | Columns missing |
| `feat_github_pr_worker` | Stories 1.5, 3.1, 4.1, 4.2 | Complete (PR #45) | `config_repos.auth_ref`, `_github_post` + 4 inspection helpers in `git_pr.py`, `mark_proposal_pr_opened` pattern all missing |

All dependencies merged. No external blockers.

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `RELYLOOP_BASE_URL` is localhost (laptop install) — GitHub can't reach the webhook URL | High (MVP1 default) | Auto-registration still records `webhook_registration_error`; polling reconciler catches all state changes. Runbook documents the ngrok / tunnel workaround. | Spec already addresses (Decision log 2026-05-09); Runbook adds operator-facing playbook. |
| Cron-job `minute=` set is wrong if `RELYLOOP_PR_POLL_MINUTES` doesn't divide 60 evenly | Low | WARN logged at startup; fall back to 15 (the default). Documented in `_poll_minute_set()` docstring. | Settings test asserts the fallback behavior (Story 1.1). |
| GitHub PAT lacks `admin:repo_hook` scope → auto-registration always errors | Medium | `webhook_registration_error` surfaces the exact message; runbook documents PAT scope requirements. Polling reconciler still works. | Runbook (Story 4.3). |
| Refactor of `git_pr.py` helpers breaks existing PR worker tests | Low | Story 1.5 makes the refactor behavior-preserving and gates on existing `feat_github_pr_worker` test green. | Test gate. |
| Webhook secret leaks into logs | Low | Spec §10 + §6 require never-log; handler never echoes the secret; structlog `RedactTokensProcessor` is a defense-in-depth (though it only matches PAT patterns, not arbitrary secrets). Static-grep audit in the contract test asserts no log call site takes the secret. | Static-grep audit (Story 2.1 contract test). |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| GitHub down (5xx) | GitHub Statuspage incident | Polling tick logs WARN per proposal, leaves state unchanged | Auto (next tick) |
| GitHub PAT lost permissions | Operator rotated/revoked the token | Polling logs 401/403 WARN; auto-registration writes `webhook_registration_error` | Operator: update `./secrets/{auth_ref}` |
| Webhook delivery never arrives | Network / GitHub-side delivery failure | Polling tick catches it within `RELYLOOP_PR_POLL_MINUTES` minutes | Auto |
| Webhook secret rotated on GitHub side but not RelyLoop | Operator forgot to update mounted secret | All future webhooks return 403 INVALID_SIGNATURE; polling still works | Operator: update `./secrets/{webhook_secret_ref}` + restart api |
| Multiple deliveries of same merge event | GitHub retried after a transient 5xx on our side | Conditional UPDATE `WHERE status='pr_opened' AND pr_state='open'` — second delivery hits 0 rows, returns `action: noop` | Auto (idempotent by state-machine semantics) |
| `register_webhook` job enqueued twice | Operator re-`POST /api/v1/config-repos` for same repo | Deterministic `_job_id` ensures Arq dedup; even if both run, the worker's `GET /hooks` pre-check skips duplicate creation | Auto |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** in story order — 1.1 → 1.2 → 1.3 → 1.4 → 1.5. Foundations have no internal dependencies between sibling stories; the suggested order is reading-rank (migration + Settings first since they're the smallest, then domain helpers, then repo functions, then the refactor). **Stories 1.2 + 1.3 can run in parallel** (both pure-domain, separate files, separate tests).
2. **Epic 2 Story 2.1** — depends on 1.2 (signature verifier), 1.3 (dispatcher), 1.4 (repo functions), 1.1 (index for `lookup_proposal_by_pr_url`). Single big story.
3. **Epic 3 Story 3.1** — depends on 1.5 (shared GitHub client), 1.4 (repo function `list_pr_opened_proposals_for_reconcile`). Single big story.
4. **Epic 4 Story 4.1** — depends on 1.5 (shared GitHub client), 1.4 (`set_webhook_registration_error`).
5. **Epic 4 Story 4.2** — depends on 4.1 (the worker function must exist before the API enqueues it).
6. **Epic 4 Story 4.3** — docs; lands last so the runbook references the merged behavior.

### Parallelization opportunities

- Stories 1.1, 1.2, 1.3, 1.4 can be developed in parallel (no shared files). 1.5 must follow at least 1.4 because it touches existing `git_pr.py`.
- After Epic 1 lands, Stories 2.1, 3.1, 4.1 can develop in parallel (no shared files; they share only the helpers from Epic 1).
- Story 4.2 must follow 4.1.

## 8) Rollout and cutover plan

- **Rollout stages:** local dev only (MVP1 has no remote staging). Operator runs `make migrate` after `git pull` to land the new `0006` migration, then `make restart` to pick up the new router + worker functions.
- **Feature flag strategy:** none.
- **Migration/cutover steps:**
  1. `make migrate` runs `alembic upgrade head` → applies `0006_proposals_pr_url_idx`.
  2. `make restart` restarts api + worker containers; worker boot registers the new cron job.
  3. First polling tick fires within `RELYLOOP_PR_POLL_MINUTES` minutes (default 15) and reconciles any open proposals.
- **Reconciliation:** N/A — the polling reconciler IS the reconciliation. Operators don't need to do anything special on first deploy.

## 9) Execution tracker

### Current sprint
- [x] Epic 1 — Story 1.1 (Migration `0006` + Settings field) — commit `c500a46`
- [x] Epic 1 — Story 1.2 (Signature verifier + URL normalizer) — commit `2287d6f`
- [x] Epic 1 — Story 1.3 (Event dispatcher) — commit `4f7ae9b`
- [x] Epic 1 — Story 1.4 (New repo functions) — commit `c532305`
- [x] Epic 1 — Story 1.5 (Extract shared GitHub API client) — commit `66ab068`
- [x] Epic 2 — Story 2.1 (Webhook router + handler + tests) — commit `2842a7d`
- [x] Epic 3 — Story 3.1 (`reconcile_pr_state` cron job + tests) — commit `4ec50ae`
- [x] Epic 4 — Story 4.1 (`register_webhook` worker) — commit `9bea914`
- [x] Epic 4 — Story 4.2 (Extend `POST /api/v1/config-repos`) — commit `1fcdf86`
- [x] Epic 4 — Story 4.3 (Runbook + docs + state flips)

### Blocked items
- None.

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope (New/Modified file tables).
- [ ] Endpoint behavior matches the spec's §7-§8 (where applicable).
- [ ] `make test-unit && make test-integration && make test-contract` all green.
- [ ] `make lint && make typecheck` clean.
- [ ] Migration round-trips cleanly (Story 1.1 + any other migration; only Story 1.1 ships one).
- [ ] If new backend `Literal` / `frozenset` introduced: cited in spec §8.4 and consumed by the spec source-of-truth comment (`# Values must match …`).

## 11) Plan consistency review

Performed before marking the plan Ready for Execution. **Updated 2026-05-12 after cross-model (GPT-5.5) review + Opus codebase audit** — see "Patch log" below.

**Counts to verify:**

- **Spec FRs:** 4 (FR-1 through FR-4) → all mapped in §1 traceability. ✓
- **Spec ACs:** 8 (AC-1 through AC-8). All assigned: AC-1, AC-2, AC-4, AC-5 → Story 2.1; AC-3 + AC-8 → Story 3.1; AC-6, AC-7 → Stories 4.1 + 4.2. ✓
- **Endpoints (spec §8.1):** 1 new (`POST /webhooks/github`) + 1 extended (`POST /api/v1/config-repos` enqueue behavior). Stories 2.1 + 4.2. ✓
- **Error codes (spec §8.5):** 1 (`INVALID_SIGNATURE`). Asserted by Story 2.1's contract test. ✓
- **New repo functions:** 7 (5 on proposal.py, 2 on config_repo.py — adds `lookup_config_repo_by_owner_repo` after cross-model review F4). Story 1.4. ✓
- **New Settings fields:** 1 (`relyloop_pr_poll_minutes`). Story 1.1; validator tightening in Story 3.1. ✓
- **New migrations:** 1 (`0006_proposals_pr_url_idx`). Story 1.1. ✓
- **Test files:** **20** (7 unit + 12 integration + 1 contract). All assigned to specific stories' DoD. (Was 16 before adding the closed-unmerged / reopened / noop-actions / unknown-event / logging integration tests + the `test_poll_cron_kwargs.py` + `test_url_owner_repo_parity.py` units. Earlier draft's "14" was an arithmetic error; the actual pre-patch count was 16.) ✓
- **Phase coverage:** single-phase per spec §3. ✓ No deferred phases.

**Codebase verification:**

| Claim | Verified by | Status |
|---|---|---|
| Alembic head is `0005_digests` | `ls migrations/versions/ \| tail -1` | Verified |
| Next migration ID is `0006` | Numbering convention | Verified |
| `config_repos.webhook_secret_ref` + `webhook_registration_error` exist | `backend/app/db/models/config_repo.py:48,51` + migration `0002` | Verified |
| `proposals.pr_url` + `pr_state` + `pr_merged_at` + `status` exist | `backend/app/db/models/proposal.py:64-72` + CHECK `:39,42-43` | Verified |
| `mark_proposal_pr_opened` is the analogous pattern for new repo functions | `backend/app/db/repo/proposal.py:184` | Verified — conditional UPDATE + RETURNING + flush |
| GitHub HTTP helpers exist inline in `git_pr.py` | `backend/workers/git_pr.py` — `_github_post:593`, `_parse_retry_after:655`, `_is_secondary_rate_limit:663`, `_body_mentions_rate_limit:670`, `_parse_rate_limit_reset:685` | **Corrected** — earlier draft cited `_call_github` (which does not exist) at `:594`. The real function is `_github_post` (POST-only). Story 1.5 generalises to method-agnostic `github_request`. |
| `RedactTokensProcessor` wired in structlog chain | `backend/app/core/logging.py:64` | Verified |
| `health.router` mounts unprefixed | `backend/app/main.py:148` | Verified — webhook router follows same exception |
| `WorkerSettings.functions` slot exists | `backend/workers/all.py:203` | Verified — `cron_jobs` slot added next to it |
| `arq.cron` API for minute-set scheduling | `from arq import cron; cron(coro, *, minute=set\|int, hour=set\|int, ...)` — verified via `inspect.signature(arq.cron.cron)` | Verified |
| HTTP mocking pattern in this project | `httpx.MockTransport` is the established pattern: `backend/tests/unit/adapters/test_request_retry.py:38`, `test_capability_check.py:107`, `test_elastic_health.py:51`. `pytest-recording` is in `pyproject.toml:55` but **no cassettes are yet checked in** — `feat_github_pr_worker` deferred its cassette tests per `state.md`. | **Corrected** — earlier draft claimed cassettes were the established pattern via `feat_github_pr_worker`. Plan switches all new integration tests to `httpx.MockTransport`. |
| `_err()` helper is per-router (no shared module yet) | `backend/app/api/v1/clusters.py:73` + 6 other v1 routers | Verified — webhook router copies the same shape |
| No existing webhook router exists | `ls backend/app/api/webhooks/` → not found | Verified — this feature creates the package |
| `backend/app/git/` is the canonical Git-provider home | CLAUDE.md "Repository Structure" → `git/  # Git provider clients` | Verified — Story 1.5 uses this path (earlier draft used `backend/app/integrations/github/`, a namespace not in CLAUDE.md). |
| `get_arq_pool` `Depends()` factory does NOT exist | `grep -rn 'def get_arq_pool\|get_arq_pool' backend/app/` → no matches in source | **Corrected** — earlier draft used `Depends(get_arq_pool)` in Story 4.2. The established pattern is `getattr(request.app.state, "arq_pool", None)` — see `proposals.py:516`, `studies.py:167`, `judgments.py:158`. Story 4.2 updated. |
| `arq_pool` is exposed on `app.state` post-startup | `backend/app/main.py:84-87` — `_app.state.arq_pool = await create_pool(...)` | Verified |
| `lookup_config_repo_by_owner_repo` is required by Stories 2.1 + 3.1 + 4.1 | Spec FR-1 + FR-2 + FR-3 all describe lookup by `(owner, repo)` | **Added** — Story 1.4 now ships this 7th repo function (was missing in earlier draft per cross-model review F4). |
| `WEBHOOK_ACTION_VALUES` is the source-of-truth for spec §8.4 | Spec §8.4 cites `backend/app/api/webhooks/github.py` | **Resolved** — plan places the frozenset in `backend/app/domain/git/webhook_dispatch.py` (cleaner domain home) AND re-exports from `backend/app/api/webhooks/github.py`, so both paths pass the spec §8.4 grep cite. |
| `cron(reconcile_pr_state, minute=...)` honours all supported `relyloop_pr_poll_minutes` values | Spec FR-4 `ge=1, le=1440`. `cron()` accepts both `minute=` and `hour=` sets — multi-hour intervals expressible via `hour=` + `minute={0}` | **Resolved** — `_poll_cron_kwargs()` now covers 18 supported values (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440). Settings field tightened to a whitelist; coordinated spec patch noted below. |

**Open spec questions:** None remaining per spec §19. ✓

**Coordinated spec patches landing alongside this plan** (drift the plan surfaced; spec is being patched in this same PR for consistency):

1. **Spec FR-4 / §17 — `relyloop_pr_poll_minutes` field constraint.** Earlier wording (`Field(default=15, ge=1, le=1440)`) allowed values like `90` or `100` that no Arq `cron(...)` invocation can express. Spec patched to the whitelist `{1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440}` (divisors of 60 plus multiples of 60 that divide 1440). Documented in the spec's Decision log.

### Patch log (Review & Patch cycle, 2026-05-12)

16 findings raised across the Opus + GPT-5.5 review passes; all accepted + applied in this plan revision. Grouped by severity:

- **High (7):** Story 1.2 reuses `validate_repo_url` rather than introducing a parallel URL regex (spec FR-1 compliance); `dispatch_event` never emits `"unknown_pr"` — router-only override; cron arithmetic covers all 18 supported values, not just divisors of 60; Story 1.4 ships `lookup_config_repo_by_owner_repo`; Story 4.2 wraps `enqueue_job` in try/except (best-effort enqueue per AC-7); Story 1.5 corrects `_call_github` → `_github_post` (the real function) and is framed as a generalisation, not pure extraction; Story 4.2 uses the established `request.app.state.arq_pool` pattern instead of a non-existent `Depends(get_arq_pool)` factory.
- **Medium (8):** Test-count arithmetic corrected (14 → 20); register-webhook worker covers 4 failure classes (404 / 422 / 5xx / network), not just 404; polling reconciler covers 401/403/5xx/network/429-skip-remaining, not just 404; router integration tests cover closed-unmerged / reopened / noop / unknown-event branches; `result` log field added per spec §13; Story 1.5 keyword consistency (`json_body=` everywhere); namespace switched to canonical `backend/app/git/` (was `backend/app/integrations/github/`); cassette claim corrected — plan uses `httpx.MockTransport` (the actually-established pattern).
- **Low (1):** `INTERNAL_ERROR` removed from the Story 2.1 endpoint table (it's a framework-level 5xx, not a feature contract code).

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests.
- [x] Every story specifies New/Modified files, Endpoints (where applicable), Key interfaces, Tasks, DoD.
- [x] Test layers (unit, integration, contract) scoped; E2E correctly marked N/A.
- [x] Documentation updates across docs/01-04 + state.md/CLAUDE.md are planned and assigned.
- [x] Lean refactor scope bounded (only the GitHub API client extraction + method-agnostic generalisation).
- [x] Epic gates measurable.
- [x] Verification gate (§10) included.
- [x] Plan consistency review (§11) passed.
- [x] Cross-model review completed (Opus 4.7 internal Pass 1 + Pass 2; GPT-5.5 cross-model review). 16 findings raised; all 16 accepted + applied. See §11 Patch log.
- [x] Coordinated spec patches applied in this PR (FR-4 whitelist + Decision log entry).
