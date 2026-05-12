# Pipeline Status — feat_github_webhook

## Idea
- Status: Skipped (spec authored directly 2026-05-09; no separate idea file).

## Spec
- Status: Approved
- Date: 2026-05-09 (Review & Patch cycles: 2026-05-12 spec review + 2026-05-12 plan-review coordinated spec patch)
- File: [feature_spec.md](feature_spec.md)
- Cross-model review: 2 cycles total — (1) 2026-05-12 spec review, 15 findings → 14 accepted + applied, 1 rejected with cited counter-evidence; (2) 2026-05-12 plan-review coordinated patch, 1 spec patch applied (FR-4 / Decision log: tighten `relyloop_pr_poll_minutes` to the whitelist of 18 cron-expressible values).
- Phases: single-phase (per §3 "Phase boundaries").
- Key contract decisions pinned in these cycles (see Decision log in spec):
  - Error envelope = standard `_err()` shape
  - HTTP 403 (not 401) for `INVALID_SIGNATURE`
  - FR-3 transaction model = post-commit Arq fire-and-forget with `GET /hooks` dedup pre-check
  - Secret resolution via `repository.full_name` (works for `ping` too)
  - Polling PAT sourced from per-repo `config_repos.auth_ref`
  - FR-4 added for the `proposals(pr_url)` partial index migration + `relyloop_pr_poll_minutes` Settings field
  - 7 new repo functions explicitly enumerated so impl-plan-gen can produce stories (5 on proposal.py + 2 on config_repo.py, including `lookup_config_repo_by_owner_repo` added in the plan-review patch)
  - `relyloop_pr_poll_minutes` constrained to the whitelist `{1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440}` so every supported value is expressible as `arq.cron(minute=…, hour=…)` kwargs

## Plan
- Status: Approved (cross-model reviewed, ready for `/impl-execute`)
- Date: 2026-05-12
- File: [implementation_plan.md](implementation_plan.md)
- Cross-model review: 1 cycle (Opus 4.7 internal Pass 1 + Pass 2; GPT-5.5 Pass A + Pass B). 16 findings raised → 16 accepted + applied (7 High, 8 Medium, 1 Low). See plan §11 Patch log.
- Stories: 11 across 4 epics. Epic 1 (foundations — migration + Settings + signature/dispatch/repo-function helpers + shared GitHub client extraction): 5 stories. Epic 2 (webhook receiver): 1 story. Epic 3 (polling reconciler): 1 story. Epic 4 (auto-registration + docs): 3 stories. (Story 4.3 is the docs/state-flip finalization.)
- Phases covered: single-phase per spec §3 — no deferred phases.
- Coordinated spec patches applied alongside the plan: FR-4 whitelist + Decision log entry tightening `relyloop_pr_poll_minutes`.
- Next action: `/impl-execute docs/02_product/planned_features/feat_github_webhook/implementation_plan.md --all` (when MVP1 sequencing reaches this feature — `feat_studies_ui` PR #50 is the current blocker per `state.md`).

## Implementation
- Status: Not started
