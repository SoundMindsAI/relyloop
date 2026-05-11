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
- Status: Not started. Next: `/pipeline` → `impl-plan-gen` against this spec.

## Implementation
- Status: Not started.

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

```bash
/pipeline docs/02_product/planned_features/feat_github_pr_worker/ --auto
```

Or, if you want to skip the orchestrator and call the planner directly:

```bash
/impl-plan-gen docs/02_product/planned_features/feat_github_pr_worker/feature_spec.md
```
