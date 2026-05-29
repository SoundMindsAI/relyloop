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

## 2. Smoke reliability gate (≥5 consecutive green smoke runs across merged PRs)

Per spec §13 NFR. The smoke job has a 15-minute budget; flake rate must be
zero across the 5 most recently merged PRs before the tag goes out.

`pr.yml` runs only on `pull_request` events (not on `push: main` —
see [`infra_pr_yml_drop_push_main_trigger`](../00_overview/implemented_features/2026_05_28_infra_pr_yml_drop_push_main_trigger/idea.md)),
so the gate is computed from the most recently merged PRs' per-job smoke
conclusions rather than from push-event workflow conclusions.

```bash
# 1. Get up to 30 most recently merged PRs targeting main (oversample to
#    handle docs-only PRs that pr.yml skipped via paths-ignore).
gh pr list --state=merged --base=main --limit=30 \
  --json number,headRefOid,mergedAt \
  --jq 'sort_by(.mergedAt) | reverse | .[] | [.number, .headRefOid] | @tsv' \
  > /tmp/merged_prs
# 2. Walk PRs newest-first until we've evaluated 5 with a real pr.yml run.
#    Docs-only PRs (no completed pr.yml run) are skipped without counting.
CHECKED=0
SUCCESS_COUNT=0
while IFS=$'\t' read -r pr_num head_sha; do
  [ "$CHECKED" -ge 5 ] && break
  RUN_ID=$(gh run list --workflow=pr.yml --event=pull_request \
             --commit="$head_sha" --status=completed \
             --json databaseId,createdAt \
             --jq 'sort_by(.createdAt) | reverse | .[0].databaseId // empty')
  if [ -z "$RUN_ID" ]; then
    echo "PR #$pr_num: skipped (docs-only or no completed pr.yml run)"
    continue
  fi
  CONCL=$(gh run view "$RUN_ID" --json jobs \
            --jq '.jobs[] | select(.name | test("smoke"; "i")) | .conclusion')
  echo "PR #$pr_num smoke: $CONCL"
  CHECKED=$((CHECKED + 1))
  [ "$CONCL" = "success" ] && SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
done < /tmp/merged_prs
if [ "$CHECKED" -lt 5 ]; then
  echo "GATE INCONCLUSIVE: only $CHECKED code-bearing PRs found in last 30 merges"
elif [ "$SUCCESS_COUNT" -eq 5 ]; then
  echo "GATE PASSED"
else
  echo "GATE FAILED ($SUCCESS_COUNT/5)"
fi
```

If the gate fails, identify the failing PR's run, read its `smoke-logs`
artifact, fix or quarantine the cause, land the fix on `main`, and re-run.
Docs-only merged PRs are filtered out of `pr.yml` by `paths-ignore` (by
design) and the loop walks past them without counting them as failures.

## 3. 80% coverage gate verification (AC-3)

The coverage gate already lives in `pyproject.toml`
(`[tool.coverage.report].fail_under = 80`). After
[`infra_pr_yml_drop_push_main_trigger`](../00_overview/implemented_features/2026_05_28_infra_pr_yml_drop_push_main_trigger/idea.md)
the merge SHA on `main` is never validated directly; instead, the coverage
gate fires on the most recently merged non-docs-only PR's head SHA. Verify
it actually fired:

```bash
# Iterate merged PRs newest-first; pick the first that has a pr.yml run.
HEAD_SHA=$(gh pr list --state=merged --base=main --limit=20 \
             --json headRefOid,mergedAt \
             --jq 'sort_by(.mergedAt) | reverse | .[].headRefOid' \
           | while read sha; do
               id=$(gh run list --workflow=pr.yml --event=pull_request \
                      --commit="$sha" --status=completed \
                      --json databaseId --jq '.[0].databaseId // empty')
               [ -n "$id" ] && { echo "$sha"; break; }
             done)
RUN_ID=$(gh run list --workflow=pr.yml --event=pull_request --commit="$HEAD_SHA" \
           --json databaseId --jq '.[0].databaseId')
gh run view "$RUN_ID" --log | grep -E "TOTAL|fail_under" | tail
```

Expected: a `TOTAL` line ≥ 80% and no `fail_under` error.

Note: docs-only merged PRs are skipped (filtered out of `pr.yml` by
`paths-ignore`, by design); the loop's inner `while read` automatically
walks past them to find the most recent code-bearing PR.

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

**Dropped (2026-05-14)** per `/idea-preflight` ship-vs-drop call.

Rationale: single-maintainer alpha-project base rates make the 4–6 hour
record-edit-upload-embed task unlikely to execute, and any pre-MVP4
recording would need to be re-shot once MVP4's auth UI (login + tenant
switcher) lands. [`docs/08_guides/tutorial-first-study.md`](../08_guides/tutorial-first-study.md)
serves the demo's discovery role for the alpha audience: it's text +
screenshots, search-indexable, low-maintenance, complete.

Skip this section entirely when cutting any future release — there is no
demo recording to verify. If the project's audience or maintenance capacity
changes (e.g., a video-marketing collaborator joins for MVP3+), file a
fresh idea at that time; this section will be re-opened in the same
release-checklist revision.

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

- Spec source: [`docs/00_overview/planned_features/chore_tutorial_polish/feature_spec.md`](../00_overview/planned_features/chore_tutorial_polish/feature_spec.md)
- Tutorial: [`docs/08_guides/tutorial-first-study.md`](../08_guides/tutorial-first-study.md)
- Canonical release matrix: [`docs/01_architecture/tech-stack.md`](../01_architecture/tech-stack.md)
