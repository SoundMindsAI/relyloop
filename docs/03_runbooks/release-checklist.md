# Release Checklist — RelyLoop v0.1.0 (MVP1)

> Maintainer-facing runbook for cutting `v0.1.0`. Owner of this checklist:
> the maintainer pushing the tag. Every item is blocking unless explicitly
> marked optional. Source: `chore_tutorial_polish` Story 4.3.

---

## 1. Pre-flight (PRs merged)

Confirm every MVP1 feature has merged to `main` (per `state.md`'s feature
table) and that `chore_tutorial_polish` itself is the most recent merge.

```bash
# Both should match.
gh pr list --state merged --search "milestone:MVP1" --json number,title | jq length
git log --oneline main | head -15
```

If anything is unmerged, stop — the release notes can't honestly claim "MVP1"
until every checked feature is in `main`.

## 2. Smoke reliability gate (≥5 consecutive green smoke runs on main)

Per spec §13 NFR. The smoke job has a 15-minute budget; flake rate must be
zero across 5 consecutive runs before the tag goes out.

```bash
gh run list --workflow=pr.yml --branch=main --limit=20 \
  --json conclusion,name,headSha \
  | jq '[.[] | select(.name | startswith("smoke"))] | .[0:5] | map(.conclusion) | all(. == "success")'
# Expected: true
```

If the answer is `false`, identify the failing run, read its `smoke-logs`
artifact, fix or quarantine the cause, and re-run until 5-in-a-row green.

## 3. 80% coverage gate verification (AC-3)

The coverage gate already lives in `pyproject.toml`
(`[tool.coverage.report].fail_under = 80`). Verify it actually fired on the
merge commit:

```bash
MERGE_SHA=$(git rev-parse main)
RUN_ID=$(gh run list --workflow=pr.yml --commit="$MERGE_SHA" \
           --json databaseId --jq '.[0].databaseId')
gh run view "$RUN_ID" --log | grep -E "TOTAL|fail_under" | tail
```

Expected: a `TOTAL` line ≥ 80% and no `fail_under` error.

## 4. Manual fresh-VM tutorial run (LLM-required path) — AC-1

Spin up a fresh Ubuntu 24.04 VM (16 GB RAM, 4 vCPU). Walk
[`docs/08_guides/tutorial-first-study.md`](../08_guides/tutorial-first-study.md)
top-to-bottom on the **hosted-OpenAI** path. Time the walkthrough.

Acceptance: ≤ 30 minutes from `git clone` to "PR opened in GitHub" (Step 10).

Log the timing + the operator's environment below:

| Date (UTC) | Operator | VM specs | Path | Wall time | Notes |
|---|---|---|---|---|---|
| YYYY-MM-DD | <name> | Ubuntu 24.04, 16 GB / 4 vCPU | hosted-OpenAI | M:SS | <issues / smoothness> |

## 5. Manual local-LLM walkthrough — AC-5

Repeat the tutorial on the local-LLM path. Unset `OPENAI_API_KEY_FILE`,
configure `OPENAI_BASE_URL` + `OPENAI_MODEL` against an Ollama / LM Studio /
vLLM / TGI instance per
[`docs/01_architecture/llm-orchestration.md` §"OpenAI-compatible endpoints"](../01_architecture/llm-orchestration.md).

Verify: judgment generation completes (structured output works) AND the digest
narrative renders (chat works). If your local model is missing structured
output, judgment generation will surface `LLM_PROVIDER_INCAPABLE` and the
walkthrough cannot complete on that model — try a different model from the
tested matrix.

| Date (UTC) | Local LLM tool / model | Wall time | Quality issues |
|---|---|---|---|
| YYYY-MM-DD | <tool> / <model> | M:SS | <issues / NA> |

## 6. Demo recording linked from README — AC-6

**Deferred to MVP3 release polish** (decided 2026-05-12 post-merge of
`chore_tutorial_polish` PR #64). Tracked at
[`docs/02_product/planned_features/chore_demo_recording_mvp3/idea.md`](../02_product/planned_features/chore_demo_recording_mvp3/idea.md).

Reasoning: the demo's value depends on UX stability (won't rot in 4 weeks)
+ a credible "production" story to tell. MVP1 is alpha for technical
evaluators who'll read code, not a video. MVP3 ships TLS install + Lucidworks
Fusion adapter + multi-Git-provider — the first release polished enough to
warrant a demo. MVP2 wouldn't change the demo content; MVP4 (multi-tenant
auth) would invalidate any pre-MVP4 video.

For `v0.1.0` specifically: the `What it looks like` placeholder has been
removed from `README.md`; the quickstart + tutorial link is sufficient
audience-fit for the alpha. Skip this section entirely when cutting `v0.1.0`.

## 7. Tag + Release procedure

```bash
# 1. Confirm clean local checkout on the merge commit.
git fetch origin main
git checkout main
git reset --hard origin/main
git status   # must be clean

# 2. Annotated tag.
git tag -a v0.1.0 -m "RelyLoop v0.1.0 — MVP1 alpha"
git push origin v0.1.0

# 3. Author release notes locally (gitignored draft).
$EDITOR release-notes-v0.1.0.md   # use the template below

# 4. Publish.
gh release create v0.1.0 \
  --title "RelyLoop v0.1.0 — MVP1 alpha" \
  --notes-file release-notes-v0.1.0.md

# 5. Verify.
gh release view v0.1.0
open https://github.com/SoundMindsAI/relyloop/releases/tag/v0.1.0
```

### Release-notes template (`release-notes-v0.1.0.md`)

```markdown
## What's in MVP1

- The Karpathy loop end-to-end: register an Elasticsearch / OpenSearch
  cluster → upload a query set → generate LLM judgments → run an Optuna
  study → review the digest → open a PR against your search-config repo.
- One UI, one workflow, one schema. ES + OpenSearch both supported via a
  single adapter.
- LLM provider abstraction: OpenAI by default; works against any
  OpenAI-compatible endpoint (Ollama / LM Studio / vLLM / TGI) via
  `OPENAI_BASE_URL`.
- Sample data + a 30-minute tutorial that walks the entire flow on a
  fresh laptop (`docs/08_guides/tutorial-first-study.md`).
- See `docs/02_product/mvp1-user-stories.md` for the full feature list.

## Audience

Technical evaluators, Relevance Engineers, and search-platform teams
considering an open-source query-tuning tool. Not yet
production-deployable — see `docs/01_architecture/deployment.md` for the
MVP1 → MVP3 → GA v1 deployment maturity ramp.

## How to install

Follow the tutorial:
[`docs/08_guides/tutorial-first-study.md`](https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/tutorial-first-study.md).

**Operators build images locally via `make up`.** Pre-built GHCR images ship
at MVP3 per the canonical release matrix; until then, `make up` triggers a
local Docker build of `relyloop/api` and `relyloop/ui` on first run.

## How to provide feedback

- GitHub Discussions:
  https://github.com/SoundMindsAI/relyloop/discussions
- Issues (bug reports, feature requests):
  https://github.com/SoundMindsAI/relyloop/issues/new/choose
```

## 8. Post-release

- Open a feedback Discussion: `gh discussion create --repo SoundMindsAI/relyloop --title "Feedback on v0.1.0" --body "..."`.
- Share via design-partner channels (#relyloop-alpha, etc.).
- Add a row to `state.md` recording the release date + tag SHA.

---

## Cross-references

- Spec source: [`docs/02_product/planned_features/chore_tutorial_polish/feature_spec.md`](../02_product/planned_features/chore_tutorial_polish/feature_spec.md)
- Tutorial: [`docs/08_guides/tutorial-first-study.md`](../08_guides/tutorial-first-study.md)
- Canonical release matrix: [`docs/01_architecture/tech-stack.md`](../01_architecture/tech-stack.md)
