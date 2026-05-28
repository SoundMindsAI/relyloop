---
name: idea-preflight
pipeline-stage: 0
pipeline-role: idea.md → /pipeline-ready idea.md
description: "Audit a planned-feature idea.md against the live codebase before /pipeline runs and APPLY the resulting patches in-place. Verifies every concrete claim (file paths, function names, counts, line numbers), audits current capabilities of any surface the idea claims to preserve/extend, refreshes stale numbers and obsolete deferral rationale, checks the folder name against the prefix + intent-clarity convention, identifies sibling planned features for coordination, and forces decisions on open forks. Default mode is Audit & Patch — patches land as uncommitted edits in the working tree without asking permission first; folder renames remain a confirmation gate. Use when: user asks 'is this idea ready for /pipeline', 'review this idea file', 'is this still needed', or invokes /idea-preflight on a path."
argument-hint: "[path to idea.md — single file. If omitted, infer from the IDE-opened file]"
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Agent
model: claude-opus-4-7
user-invocable: true
---

# Idea Preflight — verify an idea.md is ready for /pipeline

You are auditing a planned-feature `idea.md` file before it enters the `/pipeline` flow (which runs `/spec-gen` → `/impl-plan-gen` → `/impl-execute` → `/guide-gen`). The idea may have been written days, weeks, or months ago. Your job is to ground every concrete claim against the **current** codebase, force decisions on every open fork, and either declare the idea **ready for /pipeline** or emit a concrete patch list.

This skill **defaults to Audit & Patch** — apply the patches you propose, do not ask for permission first. The findings table is still emitted, but the user sees it as "here's what I changed and why," not "here's a list of edits I'd like to make if you say yes."

The skill never commits or opens a PR — that's the user's call. Patches land as uncommitted edits in the working tree; the user reviews `git diff` and decides how to ship them.

## Mode selection

| Mode | When to use | Writing behavior |
|---|---|---|
| **Audit & Patch** (default) | Any invocation of `/idea-preflight` — including the common "review this idea / is this ready" framings. | Applies edits to the idea file. Renames the folder via `git mv` if the audit recommends it. Does NOT commit or open a PR. Reports findings + what was changed. |
| **Audit-only** | User explicitly says "audit only" / "don't apply" / "just findings" / "dry run". | Reports findings only. Does not modify the idea file or rename the folder. |

**When ambiguous, choose Audit & Patch.** The user can always revert via `git checkout` if they disagree with a specific edit. Asking permission before every patch turns a 30-second skill into a multi-turn back-and-forth, and the user invoked the skill specifically because they want the idea ready.

**Hard constraints (never bypassed regardless of mode):**

- **Folder renames require user confirmation.** Applying `git mv` on the folder is a heavier change than editing the idea body — the path may be referenced elsewhere (commit history, sibling docs, search engines). Always pause and ask before renaming, even in Audit & Patch mode.
- **Open product/UX questions stay open.** Questions that genuinely need human judgment (UX call, business call, scope cut) MUST be reported in "Open questions" — do not invent a default and patch it in. The patches you apply are the ones with clear locked decisions; questions remain questions.
- **Stale references with multiple plausible fixes stay surfaced.** If a stale link could go to two different places (e.g., the dependency could be in `implemented_features/` OR a sibling planned folder), surface both and ask. Don't guess.

## Inputs

- **`$ARGUMENTS`** — path to a single `idea.md`. If omitted, fall back to the file the user most recently opened in the IDE (`<ide_opened_file>` context tag), or ask.
- **Project context (always read first):** `CLAUDE.md`, `architecture.md`, `state.md`.
- **Convention reference:** `docs/00_overview/planned_features/feature_templates/README.md` for folder-prefix taxonomy.

## Workflow

### Step 1 — Read the idea + its neighborhood

1. Read the idea file in full.
2. List sibling files in the same folder (`ls <folder>/`). Note any pre-existing `feature_spec.md`, `implementation_plan.md`, `pipeline_status.md`, `phase_*` subfolders. If those exist, the idea may already be partway through /pipeline — surface this immediately and ask the user whether they want to preflight the idea against the current codebase or audit a downstream artifact instead (use `/spec-gen --review` or `/impl-plan-gen --review` for those).
3. Note the date in the idea's frontmatter. Anything older than two weeks should be assumed to contain stale claims until proven otherwise.

### Step 2 — Is the feature still needed?

Grep the codebase for the proposed table names, column names, function names, file paths, and class names the idea introduces. If they already exist, the work is done or partly done — surface this and ask whether to:
- Move the folder to `implemented_features/<YYYY_MM_DD>_<name>/` (if shipped)
- Update the idea to reflect the partial-completion state (if some parts shipped)
- Close as won't-do (if the idea was superseded by another shipped feature)

Also: `ls docs/00_overview/implemented_features/` and search for any feature whose **deferral rationale** pointed at this idea. If such a feature has shipped recently, the deferral notes in this idea are now obsolete — flag them.

### Step 3 — Verify every concrete claim

For each named entity in the idea, run a quick Grep / Read pass:

- File paths → does the file exist? Read its frontmatter or top of file to confirm purpose.
- Function names → does the function exist with that signature? On what line?
- Line numbers in `[file.py:N-M]` references → do the lines still match what the idea says they do? (Files move; functions get refactored.)
- Doc paths in the "Related" / "References" section → does the doc exist? If renamed/moved, surface it as a broken link.
- Counts ("~42 callers across 8 files") → recount via Grep. Anything in the original idea that uses words like "approximately" or "~" against numbers should be re-measured.
- Type/enum/option-list values → match against the source-of-truth file (per CLAUDE.md "no option lists from memory" rule).

### Step 4 — Audit current capabilities of any "preserved / extended" surface

If the idea claims to "preserve all existing capabilities" of a UI panel, API endpoint, or service, **do not take the claim at face value**. Read the actual current source (`Read`) and table out every capability it provides today. Compare to the idea's capabilities list. Anything in the source that's not in the idea is at risk of being silently dropped — surface every gap.

This step has the highest leverage of the whole skill. Skip it and the spec will be written against a fictional baseline.

### Step 5 — Audit the folder name

Per CLAUDE.md "planned-features folder naming":

1. **Prefix:** must be `feat_`, `bug_`, `chore_`, `infra_`, or `epic_`. Legacy `feature_` is no longer used. If the folder uses `feature_`, recommend a rename.
2. **Intent clarity:** the name should telegraph **why** the feature exists, not just what file it touches. Examples:
   - `feat_judgment_freshness` → `feat_judgment_30day_refresh` ("freshness" was vague; the locked design is a 30-day re-grading job).
   - `epic_proposal_auto_apply` → `feat_proposal_pr_open_and_merge` (after auto-apply was scoped down to opening a PR for human review, "auto_apply" no longer reflected the MVP intent).
   - `feat_dedicated_study_status_history` → `feat_study_status_audit_log` ("dedicated history" buries the audit-log mechanism).
3. **Length:** prefer 4–6 underscore-separated tokens. Single-token names (`feat_billing`) are too vague; 8+ token names (`feat_role_change_audit_log_table_for_admin_oversight`) are too verbose.

If a rename is recommended, propose the new name with one-line rationale and 2–3 alternatives considered.

### Step 6 — Cross-check siblings + recently implemented features

1. `ls docs/00_overview/planned_features/*/` (two-level — top level holds MVP buckets `00_unsure/`, `01_mvp1/`, `02_mvp2/`, `03_mvp3/`, `04_ga/`, `99_backlog/` plus `feature_templates/`; siblings live one level deeper) — for any sibling whose name overlaps the idea's domain, check whether the two coordinate or conflict. The idea's "Relationship to other work" section should mention each sibling that touches the same table/service/UI surface.
2. `git log --since="<idea date>" --oneline -- docs/00_overview/implemented_features/` — list features that shipped after the idea was written. For each, ask: does its ship retire any deferral rationale in this idea? Does it create any new precedent the idea should reference (e.g. scheduler 5-touch-point checklist after the worker-runtime work shipped)?
3. Note any sibling that the idea should explicitly coordinate with for ordering (not blocking — coordinate-only is the common case).

### Step 7 — Cross-check against CLAUDE.md absolute rules

For each claim in the idea, mentally walk the project's "Absolute Rules — Never Violate" section. RelyLoop's CLAUDE.md (when it exists per `infra_foundation`) will codify these; until then, derive from the umbrella spec + `docs/01_architecture/`. Common rules to check:

- Adding a migration? → reversible downgrade + idempotency guards mentioned (per [`infra_foundation/feature_spec.md`](../../docs/00_overview/planned_features/infra_foundation/feature_spec.md) FR-5).
- Adding a webhook handler (e.g., `/webhooks/github`)? → signature verification on raw body + idempotency.
- Adding a state-machine transition (e.g., `studies.status`)? → routed through the centralized service-layer guard (`backend/services/study_state.py`); direct ORM writes raise.
- Adding a `<select>` / dropdown / status badge? → option list grounded in a backend source-of-truth file (Pydantic `Literal[...]`, `frozenset`, or DB CHECK) with a `// Values must match <path>` comment.
- Calling an LLM? → uses the configured `OPENAI_BASE_URL` (per [`llm-orchestration.md`](../../docs/01_architecture/llm-orchestration.md)); reads the capability cache before relying on tool-calling or structured-output; respects the daily-budget gate.
- Adding API endpoints? → follows the conventions in [`api-conventions.md`](../../docs/01_architecture/api-conventions.md) (URL prefix, error envelope, cursor pagination, X-Total-Count + ?since on list endpoints).
- Mutating tenant-visible state (studies, trials, judgments, judgment_lists, proposals, query_sets, query_templates, clusters, config_repos)? → audit_log INSERT required in the same transaction (MVP2+ when audit_log lands per [`data-model.md`](../../docs/01_architecture/data-model.md)). Grep the proposed write paths for adjacent `audit_log` writes; if the idea adds a new mutation site without addressing emission, flag as a finding.
- Adding a secret? → mounted file via `*_FILE` env var (per [`deployment.md` §"Secrets"](../../docs/01_architecture/deployment.md)); never bare env vars.

If the idea quietly violates any of these, that's a hard blocker, not a "fix-up."

### Step 8 — Force decisions on open forks

Scan the idea for "Option A vs Option B" forks. For each:

- If the fork has a clear default and the idea doesn't pick one, propose locking it. Use the same "(locked)" header pattern this codebase uses; structure the locked decisions as a Decision-log entry similar to the §19 sections in the existing MVP1 feature specs under `docs/00_overview/planned_features/`.
- If the fork genuinely needs user input (UX call, product call, business call), keep it but reframe in the "Open questions for /spec-gen" section with a recommended default so /spec-gen doesn't start from zero.

A "locked decision" is a decision someone reading the idea cold can act on without re-litigating.

### Step 9 — Surface non-obvious migration concerns

If the idea proposes a migration:

- Column rename → also rename any indexes that reference the old column. Run `grep -rn "ix_<old_name>" backend/alembic backend/app` to find them.
- Table rename → same, plus FK references (`grep "ForeignKey.*<table>\|REFERENCES <table>"`).
- Migration must include `downgrade()` per CLAUDE.md.
- Round-trip verification (`alembic downgrade -1 && alembic upgrade head`) called out.
- All `add_column` / `drop_column` / `create_table` operations idempotency-guarded.
- Revision ID ≤ 32 chars (alembic_version VARCHAR(32) limit).

### Step 10 — Emit a structured readiness verdict

Output, in order:

1. **Verdict:** **ready** / **not ready** / **partially shipped — re-evaluate**.
2. **Blocking issues** (one bullet each, file:line refs where applicable). Each blocker has a concrete remediation — no vague "needs work."
3. **Recommended folder rename** (if any), with new name + 2–3 alternatives.
4. **Stale claims to refresh** (counts, paths, dates).
5. **Decisions to lock** (one bullet per fork, with proposed default).
6. **Open questions for /spec-gen** (genuinely needs spec-time decision; not just deferred).
7. **Sibling coordination notes**.
8. **Patches applied** — one paragraph per file, exact edits that landed (Audit & Patch is the default). For each edit, cite the section (Origin / Depends on / Capability N / etc.) and one-line summary of the change. If a folder rename is recommended, present it as a proposal and pause before running `git mv` (folder renames are the one hard-confirmation gate per "Mode selection" above).

Then: report `git diff --stat` so the user can see file-level scope. If Audit-only mode is in effect, swap section 8 to "Patch plan" and end by asking whether to apply.

## Output format

Use plain prose with markdown tables for capability audits. **Do not** invent a heavyweight "Verification Ledger" section like /spec-gen and /impl-plan-gen produce — those are for downstream artifacts. The preflight output is consumed by the user, not piped into another skill.

Cap each section at what fits on screen. If the audit produces 20+ findings, group them by severity and emit the top 5 inline + the rest as an indented appendix.

## Common gotchas

- **The "shared component" trap.** When an idea says "extract X into a reusable component for surfaces A and B," verify that A and B actually have parallel feature sets. They often don't — for example, a study-detail trials table (live-polling, sortable) and a proposal-detail diff table (static, read-only) might both be "tables" but render very different shapes. Skipping the per-surface capability audit silently drops capabilities at extraction time.
- **The "regenerate" trap.** Idea claims an existing capability that doesn't actually exist. Always grep for the named action / endpoint / button before listing it as something to "preserve."
- **Stale call-site counts.** Anything written more than two weeks ago and quoting a number ("~42 calls") is almost certainly wrong now. Re-measure with `grep -rn "<symbol>(" backend/ | wc -l`.
- **Deferral rationale obsolescence.** Many ideas say "deferred until X ships." Check whether X shipped — if so, the rationale needs to flip from "why later" to "why now."
- **Doc path drift.** Architecture docs get reorganized. Test every `[](path)` link in the idea's "Related" / "References" sections.
- **The "broad enough to skip the rules" trap.** Even tiny ideas need to walk the Absolute Rules in Step 7. Innocuous-looking ideas often surface a rule violation (e.g., a proposed config knob that needs to be `_FILE`-mounted, not bare env).
- **The folder-name-buries-intent trap.** A folder named `feat_role_change_tracking` sounds clear until you ask: what does it actually deliver? An audit_log entry. Folder names should match the deliverable, not the description.
- **The silent-mutation trap.** An idea proposes new endpoints, new service functions, or new webhook handlers that mutate tenant-visible state without saying anything about audit-event emission. The mutations ship, the audit_log shows nothing, and weeks later someone asks "who changed this?" with no answer. Always cross-check proposed write paths against the audit_log event-type catalog ([`data-model.md` §"Forthcoming: audit_log"](../../docs/01_architecture/data-model.md)). Activates at MVP2 when audit_log lands; pre-MVP2 ideas can mark audit-events as "N/A — pre-MVP2".

## What this skill does NOT do

- Generate a `feature_spec.md` — that's `/spec-gen`.
- Generate an implementation plan — that's `/impl-plan-gen`.
- Implement anything — that's `/impl-execute`.
- Create or update guides — that's `/guide-gen`.
- Open a PR or commit changes — that's the user's call.
- Decide product / UX questions that genuinely need human judgment — those go in "Open questions for /spec-gen" with a recommended default.

## Termination

End with one of:

- **"Ready for /pipeline."** — no patches needed (rare on first audit; common after a re-audit). No blockers, all decisions locked, folder name correct.
- **"Patches applied. N edits across M files. Idea is now ready for /pipeline."** — the default termination after Audit & Patch. Include a short bullet list of what changed and a `git diff --stat` line. If a folder rename was recommended but skipped pending user confirmation, surface that explicitly: **"One pending decision: rename folder to `<new>`? Run `git mv` to apply."**
- **"Not ready. N blockers remain after patching (see above)."** — Audit & Patch landed the safe edits but blockers requiring human decision remain. Each blocker has a remediation path the user must drive (product/UX call, schema design call, scope cut, etc.).
- **"Audit-only output (no patches applied per `--audit-only` flag). Want me to apply?"** — Audit-only mode termination. The default termination above replaces this for normal invocations.
