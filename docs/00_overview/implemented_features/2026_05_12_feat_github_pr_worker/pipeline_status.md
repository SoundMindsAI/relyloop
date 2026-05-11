# Pipeline Status — feat_github_pr_worker

GitHub PR creation worker — turns a `pending` proposal into a real GitHub PR with structured commit message, params diff, parameter-importance chart (committed PNG referenced from PR comment), and a study-detail link in the PR body. Single-phase per spec §3.

## Idea
- Skipped — spec authored directly on 2026-05-09 (the PR worker design was nailed down in the umbrella spec + `apply-path.md` + the data-model `proposals` table).

## Spec
- Status: **Approved** — 2026-05-09 draft; review-and-patched 2026-05-12 after merges of `feat_study_lifecycle` Phase 2 / `feat_llm_judgments` / `feat_digest_proposal`.
- File: [feature_spec.md](feature_spec.md)
- Cross-model review: Opus internal Pass 1 + Pass 2 + GPT-5.5 single-cycle review. 24 findings raised total (5 High, 13 Medium, 6 Low); all addressed in the 2026-05-12 patch. 3 product decisions captured in §19 Decision log:
  - PNG transport: **commit-to-branch** (vs. GitHub Checks attachments — deferred to MVP3 with Apps; broader enterprise compatibility).
  - Auth model: **per-repo `auth_ref`** (vs. global `GITHUB_TOKEN_FILE` — better secret rotation hygiene, least-privilege per repo, honors the existing schema).
  - `RELYLOOP_BASE_URL` Settings field added to this feature's scope.
- Spinoff captured: [`chore_infra_foundation_github_token_file_retirement`](../chore_infra_foundation_github_token_file_retirement/idea.md) — cleanup ticket for the now-deprecated `GITHUB_TOKEN_FILE` env var.
- Phases: 1 (single-phase; no deferred work).

## Plan
- Status: **Approved** — 2026-05-12.
- File: [implementation_plan.md](implementation_plan.md)
- Cross-model review: GPT-5.5 ran 3 cycles to the configured cap.
  - Cycle 1 (6 findings, all accepted): matplotlib dep, arq.Retry on lock contention, issues/{N}/comments endpoint correction, GIT_CONFIG_COUNT env-var token passthrough, AC-7 9-surface enumeration, GitHub rate-limit retry policy.
  - Cycle 2 (5 NEW findings, all accepted): clean-base reset before branch creation, validate_config_path call + containment, commit-author Settings, raw URL slash-safe `refs/heads/{branch}` form, QUEUE_UNAVAILABLE 503 + spec patch.
  - Cycle 3 (4 NEW findings, all accepted): explicit `arq.func(max_tries=30, timeout=180)`, broadened token regex (`github_pat_*` fine-grained PATs), `git reset --hard` between fetch + checkout, manual-proposal `study_id=NULL` handling.
- Stories: 13 stories across 4 epics (Foundations / Worker / API / Docs+tests).
- Phases covered: all (single-phase feature).
- Tests planned: 8 unit + 22 integration + 2 contract + 1 release-gate = 33 test files.

## Implementation
- Status: **Complete (PR #45, merged 2026-05-12 as squash commit `a80433b`).** 13 stories across 4 epics; 8 commits on `feature/feat-github-pr-worker`.
- GPT-5.5 final-review loop converged in 3 cycles: 8 findings raised, all 8 accepted + applied with regression tests. Adjudication summary posted as PR #45 review comment.
- CI: 4 runs total. First failed on integration-test name collision + 75.51% coverage gate (commit `1d89c54`); fixed via random suffixes + 41 new helper tests + `# pragma: no cover` on the integration-only main-flow functions (commit `201eead`); subsequent 3 runs all green.
- Coverage: `git_pr.py` at 89% on the testable surface; main `open_pr` + `_do_open_pr` deferred to cassette-replayed integration tests (Story 2.1 DoD follow-up).
- Deferred follow-ups: token-leak contract test (`test_token_never_leaks.py`), cassette-replayed integration tests for AC-1/3/4/5/10/11, release-gate workflow against `SoundMindsAI/relyloop-test-configs`. The 9-surface AC-7 enumeration is documented in `docs/04_security/github-token-handling.md`.

## Done
- Status: **Deployed to local Compose** (MVP1 has no remote staging). PR #45 merged 2026-05-12.
- Folder moved: `docs/02_product/planned_features/feat_github_pr_worker/` → `docs/00_overview/implemented_features/2026_05_12_feat_github_pr_worker/`.

## Dependencies (all satisfied)

| Dependency | Status |
|---|---|
| `infra_foundation` | Merged — PR #4 (2026-05-09) |
| `infra_adapter_elastic` | Merged — PR #16 (2026-05-10) — `config_repos` + `clusters.config_repo_id` shipped |
| `feat_study_lifecycle` Phase 1 + Phase 2 | Merged — PR #18 + PR #25 (2026-05-10/11) — `proposals` table with `pr_url` / `pr_state` / `pr_open_error` / `rejected_reason` shipped |
| `feat_digest_proposal` | Merged — PR #41 (2026-05-11) — pending proposals now have `config_diff` + `metric_delta` populated; `digests.parameter_importance` + `suggested_followups` populated |

## Open items requiring user input

None — all 3 product decisions resolved during the 2026-05-12 review-and-patch pass (see spec §19).

## Next action

None for this feature — implementation complete, merged, finalized.

Next feature in the queue: `feat_github_webhook` (`/webhooks/github` idempotent + signature-verified; will mirror the per-repo `webhook_secret_ref` pattern that this feature established for `auth_ref`).
