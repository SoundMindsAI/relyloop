# Pipeline Status — feat_github_webhook

## Idea
- Status: Skipped (spec authored directly 2026-05-09; no separate idea file).

## Spec
- Status: Approved
- Date: 2026-05-09 (Review & Patch cycle: 2026-05-12)
- File: [feature_spec.md](feature_spec.md)
- Cross-model review: 1 cycle (Opus internal Pass 1 + Pass 2; GPT-5.5 corroboration). 15 findings → 14 accepted + applied, 1 rejected with cited counter-evidence (`docs/01_architecture/api-conventions.md:14` documents `/webhooks/<provider>` as the canonical no-prefix mount, not a contradiction).
- Phases: single-phase (per §3 "Phase boundaries").
- Key contract decisions pinned in this cycle (see Decision log in spec):
  - Error envelope = standard `_err()` shape
  - HTTP 403 (not 401) for `INVALID_SIGNATURE`
  - FR-3 transaction model = post-commit Arq fire-and-forget with `GET /hooks` dedup pre-check
  - Secret resolution via `repository.full_name` (works for `ping` too)
  - Polling PAT sourced from per-repo `config_repos.auth_ref`
  - New FR-4 added for the `proposals(pr_url)` partial index migration + `relyloop_pr_poll_minutes` Settings field
  - 6 new repo functions explicitly enumerated so impl-plan-gen can produce stories

## Plan
- Status: Not started
- Next action: `/pipeline docs/02_product/planned_features/feat_github_webhook` (will invoke `impl-plan-gen`)

## Implementation
- Status: Not started
