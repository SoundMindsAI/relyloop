# Tracking-issue template + stage-sync convention

How RelyLoop creates and maintains the **GitHub tracking issue** for a planned-feature folder, so that:

1. An issue is **self-contained** — a developer can understand the problem, what the work delivers, and where to start *without opening the linked artifact*.
2. The issue **stays in sync** with its folder's artifacts as the feature advances Idea → Spec → Plan → Implement → Done.

> **Scope.** This is the body format for the *machine/agent-generated* tracking issues that mirror `planned_features/` folders (the "issue-coverage sweep" issues, labels `mvp2`/`type/*`). It is **not** a GitHub issue *form* — human/external bug reports and feature requests use the forms in [`.github/ISSUE_TEMPLATE/`](../../../../.github/ISSUE_TEMPLATE/). Those forms shape the New-Issue UI; generated issues bypass the UI entirely, so they need this written convention instead.

---

## Why this exists

A 2026-06-02 accuracy audit of the MVP2 tracking issues found two recurring defects, both mechanical:

- **Drift** — line numbers, counts, and stage/label fields that were true when the issue was filed but went stale as the code and artifacts moved (e.g. a cited `file.py:917-935` that had shifted to `:1393-1414`; a "ready-to-execute" label on a design-ahead feature whose dependency had not merged).
- **Thinness** — a bare slug-doubled title (`chore_x: chore_x`) and a `Definition of done: lives in the linked artifact` placeholder, so the issue list and the issue body both told a reader nothing.

Both are prevented by (a) a consistent body shape and (b) re-syncing the issue at each stage transition instead of writing it once and forgetting it.

---

## Title rule

`<folder-slug>: <one-line human summary>`

- The part after the colon MUST be a real, plain-language summary — **never** the slug repeated. `chore_cluster_detail_rung_badge: chore_cluster_detail_rung_badge` is a defect; `chore_cluster_detail_rung_badge: Surface a UBI-readiness rung badge on the cluster-detail page` is correct.
- Keep it scannable in the issue list — a reader should grasp the work from the title alone.

## Labels

Set on create and updated on every stage transition:

| Dimension | Label | When |
|---|---|---|
| Release bucket | `mvp2` / `mvp3` / `ga` | folder's bucket |
| Work type | `type/bug` · `type/chore` · `type/feature` · `type/infra` | folder prefix |
| Priority | `priority/P0` · `priority/P2` (etc.) | from idea/spec |
| **Stage** | `needs-preflight` (Idea) → `ready-to-execute` (Spec+Plan present) | **swap on transition** |
| **Gated** | `blocked` | when a `Blocked by:` dependency or a design-ahead gate is unmet — **overrides** `ready-to-execute` |

The stage labels are mutually exclusive: an issue is `needs-preflight` **or** `ready-to-execute` **or** `blocked`, never two at once.

---

## Body skeleton (stage-aware)

The first line MUST be a hidden marker `<!-- tracking-slug: <folder-slug> -->`. It is
the deterministic key the [`reconcile-tracking-issues`](../../../../.github/workflows/reconcile-tracking-issues.yml)
workflow uses to match an issue to its folder (so an issue with a plain-English title
is still linked, and auto-create never duplicates it). Hand-created issues must include
it too.

```markdown
<!-- tracking-slug: <folder-slug> -->
## Problem
<2–4 sentences, inline and self-contained: what is wrong / what is missing, and
who feels it. Cite the load-bearing file:line(s) — verified against the current
tree, not copied from a stale artifact.>

## What this delivers
<Plain-language description of the change: the new behavior / files / surface.
For multi-engine work, name the per-engine approach. Omit for a pure idea-stage
item that has no design yet.>

## Status
- **Stage:** IDEA | SPEC | PLAN | IMPLEMENT | DONE
- **Priority:** <P0/P2/…>
- **Blocked by:** <#NNN + one line why, OR "none">   ← include only when gated

## Definition of done
<Idea stage: a short checklist of the observable end-state.
Spec/Plan stage: an inline checklist derived from the spec's acceptance criteria
(AC-1…AC-N) — enough that a reader sees what "done" means without opening the spec.>

## Artifacts
- **Idea:** [idea.md](<path>)
- **Spec:** [feature_spec.md](<path>)         ← add when it exists
- **Plan:** [implementation_plan.md](<path>)  ← add when it exists

## How to execute   ← stage-aware, see below
```

### Stage-aware "How to execute"

- **Idea stage (`needs-preflight`):** point at `/idea-preflight` then `/pipeline … --auto`.
- **Spec+Plan present (`ready-to-execute`):** point at `/impl-execute <plan> --all`, with a one-line "run `/impl-plan-gen` accuracy audit first if it looks stale against `main`."
- **Gated (`blocked`):** lead with a **⚠️ DO NOT `/impl-execute` yet** banner naming the unmet gate (the blocking issue and/or the design-ahead condition), then the command to run *once the gate clears*.

---

## Stage-sync procedure

Run this whenever a folder advances a stage (the pipeline skills call it at each gate — see below). It is idempotent; running it twice is a no-op.

1. **Find the issue** for the folder slug:
   ```bash
   gh issue list --state all --limit 300 --json number,title \
     --jq '.[] | select(.title|startswith("<folder-slug>:")) | .number'
   ```
   Anchor with `startswith("<folder-slug>:")` (the title convention is `<slug>: <summary>`) — a bare `test("<folder-slug>")` is a regex *substring* match that would also match a longer slug containing this one (e.g. `feat_auth` matching `feat_auth_saml`). If none exists, create one from the skeleton above (title rule + Idea-stage labels).
2. **Flip `## Status → Stage:`** to the new stage.
3. **Swap the stage label** per the table. `ready-to-execute` requires **both** spec and plan present, so it is set at the **PLAN** transition — keep `needs-preflight` through the SPEC transition. `blocked` overrides whenever a `Blocked by:`/design-ahead gate is unmet.
4. **Add the new artifact link** (Spec on SPEC, Plan on PLAN) to `## Artifacts`.
5. **Backfill `## Definition of done`** from the spec's acceptance criteria — replace any "lives in the linked artifact" placeholder with a real inline checklist.
6. **Switch `## How to execute`** to the stage-appropriate command block above.
7. **Verify, don't copy.** Any file:line in the body must be re-checked against the current tree (`grep`) before you write it — drift in the artifact must not be propagated into the issue.
8. **On merge (DONE):** close the issue with a comment linking the merged PR. (If the work is captured as `phase*_idea.md` follow-ups, keep the issue open and note what remains.) The fastest path is to put `Closes #<N>` in the PR body so GitHub closes it on merge. **Backstop:** even if both are missed, the [`reconcile-tracking-issues`](../../../../.github/workflows/reconcile-tracking-issues.yml) workflow closes any open issue whose slug has moved into `implemented_features/` on the next push to `main` (or the daily cron) — and creates a templated issue for any roadmap-active planned folder that lacks one. This runs server-side, so it holds regardless of which Claude Code surface drove the merge. Preview locally with `python scripts/reconcile_tracking_issues.py --dry-run`.

---

## Maintainer checklist (manual edits)

When you hand-edit a tracking issue, the same three things matter: the title is a real summary (not the slug), the stage label matches the artifacts present, and every file:line was verified against the current tree. If you advance the folder a stage, run the sync procedure above rather than editing one field in isolation.
