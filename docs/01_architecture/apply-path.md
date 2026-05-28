# Apply Path: Git PR Workflow

**Status:** Adopted for MVP1 with GitHub-only. Multi-Git-provider abstraction (GitLab + Bitbucket) ships at MVP3 per [`tech-stack.md` §"Canonical release matrix"](tech-stack.md).
**Source of truth for product context:** [docs/00_overview/relyloop-spec.md §16](../00_overview/relyloop-spec.md) ("Apply path: Git PR workflow").

---

## The architectural rule

**The tool only edits `*.params.json` files; it never edits templates.** This is the contract.

Why:
- Template changes are structural (new fields, new clauses) and need engineer judgment in code review.
- Parameter changes are scalar and safely automatable.
- The PR diffs are small and reviewable in 2 minutes.
- If a study's winning config requires a NEW param the template doesn't expose, the tool refuses to apply (PR creation fails with `PARAM_NOT_IN_TEMPLATE`); the engineer must update the template manually first.

## Config repo conventions

The user nominates one or more Git repos that hold canonical search-config files. Each `clusters` row references one repo + a path within it. MVP1 supports GitHub only.

Layout for an Elasticsearch cluster:

```
search-configs/
  products-prod-es/
    templates/
      product_search.yaml          # canonical template + locked param values
      product_search.yaml.params.json   # what the tool edits
  products-staging-es/
    templates/
      product_search.yaml
      product_search.yaml.params.json
```

The `*.params.json` file is read by the user's deployment pipeline and injected into the template at deploy time. RelyLoop does not interact with the cluster directly during apply; the boundary is the PR.

## PR creation flow

When a proposal transitions to `pr_opened` (via `POST /api/v1/proposals/{id}/open_pr` per `feat_github_pr_worker`):

1. **Git PR worker** clones (or pulls) the config repo into `./data/repo-clones/<repo-name>/`. Workspace is per-worker; concurrent PRs to the same repo serialize via Postgres advisory lock.
2. Creates a branch `relyloop/study-{study_id}` (or `relyloop/proposal-{proposal_id}` for manual proposals) off the cluster's `pr_base_branch` (default `main`).
3. Reads the existing `*.params.json` for the relevant template+cluster.
4. Applies the proposal's `config_diff` (deep-merge into the params JSON).
5. Validates the resulting JSON parses + every key in the diff exists in the template's `declared_params` (rejects with `PARAM_NOT_IN_TEMPLATE` otherwise).
6. Commits with a structured message:

```
relevance: tune product_search params (study stu_01HXYZ)

Cluster: products-prod-es
Template: product_search v3
Metric: nDCG@10  0.612 → 0.762 (+24.5%)

Top params:
  field_boosts.title:  2.5 → 4.7
  tie_breaker:         0.1 → 0.34
  fuzziness:           "0" → "AUTO"

Study run by: <operator-email when MVP4 brings auth; "system" in MVP1-3>
Trial count: 2000
Run duration: 7h 42m
Best trial: tri_01HXYZ_0987
```

(Commit author is configured via `git config user.email = relyloop-bot@<your-domain>` per the install runbook.)

7. Pushes the branch.
8. Opens a GitHub PR via REST API (`POST /repos/{owner}/{repo}/pulls`). The PR body includes:
   - Link back to the study in the RelyLoop UI (resolved via `RELYLOOP_BASE_URL` config)
   - Parameter importance bar chart (rendered as PNG, attached as a PR comment after PR creation)
   - Top-10 trials table (markdown)
   - Baseline vs achieved metrics table
   - Suggested follow-up studies (from `digests.suggested_followups`)
9. Stores `pr_url` and `pr_state = 'open'` on the proposal row.

## GitHub auth (MVP1)

| Auth kind | Mechanism | Stored as | Notes |
|---|---|---|---|
| Personal Access Token (PAT) | `Authorization: token <pat>` header on REST calls; HTTP basic for clone (`https://x-access-token:<pat>@github.com/...`) | `./secrets/<config_repos.auth_ref>` (per-repo mounted file — see [`github-token-handling.md`](../04_security/github-token-handling.md)) | MVP1 default. Per-`config_repo` token; needs `repo` scope on the configured config repo. |
| GitHub App | Installation token via JWT-signed App auth | App private key + installation_id in mounted secrets | Reserved for **MVP3** (production-stack hardening; finer-grained perms + audit). |

PAT is the only path in MVP1. The PAT is resolved per-`config_repo` at job time: the worker reads `./secrets/<auth_ref>` named on the proposal's parent cluster's `config_repos.auth_ref` column. If the file is missing or empty, `POST /api/v1/proposals/{id}/open_pr` returns `GITHUB_NOT_CONFIGURED` and the proposal's `status` stays `pending`.

## Webhook receiver

Per [`feat_github_webhook`](../02_product/planned_features/feat_github_webhook/feature_spec.md):

- Endpoint: `POST /webhooks/github` (no auth, signature-verified)
- Verifies the `X-Hub-Signature-256` HMAC against the `webhook_secret_ref` mounted secret (per repo)
- On `pull_request` events with `action ∈ {closed, merged}`: looks up the proposal by `pr_url`, updates `proposals.pr_state` and `pr_merged_at`
- On `pull_request_review` events: optional MVP2+ enhancement (Slack notifications)

**Polling fallback** (MVP1): a periodic worker tick (every 15 minutes) reconciles PR state for proposals with `status='pr_opened'` whose `pr_state` hasn't been updated in >15 min. Catches missed webhooks.

## Concurrency and consistency

- **One PR per proposal.** Re-running `open_pr` on a proposal that's already `pr_opened` returns `INVALID_STATE_TRANSITION`.
- **Per-repo serialization.** The Git PR worker takes a Postgres advisory lock per `config_repo_id` before touching the local clone. Concurrent proposals targeting different repos run in parallel.
- **Branch naming uniqueness.** `relyloop/study-{study_id}` is unique by construction; if the branch already exists upstream (e.g., re-running after a partial failure), the worker fails with `BRANCH_EXISTS` rather than force-pushing.

## Reserved for later releases

| Capability | Activates at |
|---|---|
| Multi-Git-provider abstraction (`GitProvider` Protocol) with GitLab + Bitbucket implementations | **Backlog** (was MVP3 in the prior plan) |
| GitLab (project token / app, project-level webhooks, MR + approval rules) | Backlog |
| Bitbucket (workspace tokens, webhook UUID, default reviewers + branch restrictions) | Backlog |
| GitHub App auth (installation tokens, JWT signing) | Backlog |
| Per-provider webhook signature verification beyond GitHub HMAC-SHA256 | Backlog |
| Apache Solr apply path (PR edits `*.params.json`; CI writes to Solr via Request Parameters API or `solrconfig.xml` swap) | MVP2 (with Solr adapter) |
| Slack notifications on PR open / review-requested / merged | MVP3 (observability layer) |
| Validation re-run on prod after staging win (top user story #2 from umbrella §6) | MVP3 |

## Cross-references

- Stack choices (httpx async for GitHub REST, `gh` CLI for clones): [`tech-stack.md`](tech-stack.md)
- `proposals` and `config_repos` schemas: [`data-model.md`](data-model.md)
- API conventions for the `/webhooks/github` endpoint: [`api-conventions.md`](api-conventions.md)
- Service topology (Git PR worker as one of three queue consumers): [`system-overview.md`](system-overview.md)
- Owning feature specs:
  - [`feat_github_pr_worker/feature_spec.md`](../02_product/planned_features/feat_github_pr_worker/feature_spec.md) — PR creation worker
  - [`feat_github_webhook/feature_spec.md`](../02_product/planned_features/feat_github_webhook/feature_spec.md) — webhook receiver + polling reconciler
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
