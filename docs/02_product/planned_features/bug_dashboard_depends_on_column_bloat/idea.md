# Dashboard "Depends on" column bloat — shipped features list future ideas as dependencies

**Date:** 2026-05-22
**Status:** Idea — surfaced by Gemini Code Assist review on PR #200 (2026-05-22). Pre-existing bug; this PR only made one more entry visible.
**Priority:** P2 — dashboard is internal planning surface; the bloat doesn't break navigation, it just makes the "Depends on" column meaningless. No daily cost; not unblocking anything.
**Origin:** Gemini Code Assist findings on [PR #200](https://github.com/SoundMindsAI/relyloop/pull/200) flagged 4 instances of completed features (`feat_chat_agent`, `chore_tutorial_polish`) listing `feat_ubi_judgments` as a dependency. Verified by `git show main:docs/00_overview/MVP1_DASHBOARD.md | sed -n '35p'` — pre-PR-200, `feat_chat_agent` already had **45** backtick'd feature names in its "Depends on" column, including dozens of features that shipped *after* it. PR #200 only added one more (`feat_ubi_judgments`) to the existing list; the underlying bug is in the dashboard-regen script's parser, not in the planning artifacts.
**Depends on:** None.

## Problem

[`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) (2,084 lines) generates the "Depends on" column for each planned-feature row in [`MVP1_DASHBOARD.md`](../../../00_overview/MVP1_DASHBOARD.md) and `mvp1_dashboard.html`. The current output produces logical impossibilities:

- **`feat_chat_agent`** shipped 2026-05-12 (PR #60). Its "Depends on" column lists 46 features, including `feat_pr_metric_confidence` (shipped 2026-05-21), `feat_study_clone_from_previous` (idea only), `feat_ubi_judgments` (idea only, dated 2026-05-22). A merged feature can't depend on ideas that didn't exist yet.
- **`chore_tutorial_polish`** shipped 2026-05-12 (PR #64). Same pattern — lists 46 features, most shipped weeks later or still unscoped.
- The shape suggests the regen script is treating **every backtick'd feature-name reference in a spec/idea body** as a forward "depends on" relationship — including cases where the reference is in a "Relationship to other work" section, a "Future extensions" paragraph, or a comparison to a sibling feature.

The "Depends on" column should reflect the **forward dependency graph** — i.e., what each planned feature needs to ship *before* it. The canonical source is the `**Depends on:**` line in each `idea.md` / `feature_spec.md` ([`feature_templates/idea-template.md`](../feature_templates/idea-template.md) requires it). Parsing that line directly (instead of grep'ing the whole document for backtick'd feature names) would fix the bloat.

## Proposed capabilities

Single tier — fix the parser; no schema or UI change.

### Parser correction

- **Locate the "Depends on" extraction logic** in [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py). Likely a regex sweep over the whole document body; needs to be scoped to the `**Depends on:**` line only.
- **Spec format:** `**Depends on:** <list of feature names or "None">`. The line lives near the top of every idea.md (per the template) and every implemented feature_spec.md.
- **Edge cases:**
  - `Depends on: None` → empty list (rendered as `—` in the markdown).
  - `Depends on:` followed by a paragraph of prose with multiple backtick'd names → parse all backtick'd names on that line only.
  - Multiple "Depends on:" lines (shouldn't exist, but defensive) → use the first.
  - Implemented features whose canonical `feature_spec.md` predates the convention → fall back to scanning the first 30 lines for an explicit "Depends on" mention; if none, emit `—`.
- **Add a regression test:** new unit test in `backend/tests/unit/scripts/test_dashboard_depends_on.py` (or wherever existing tests for the regen script live) asserts that for a fixture set of idea.md files, only the `**Depends on:**` line is parsed — not body-level backtick references.

### Verify the bloated rows shrink

After the fix, re-run `python scripts/build_mvp1_dashboard.py`. Expected outcomes:

- `feat_chat_agent` "Depends on" column drops from 46 entries to whatever its actual spec lists (likely 1-3: `infra_foundation`, `infra_adapter_elastic`, possibly `feat_study_lifecycle`).
- Every implemented feature's "Depends on" column drops to its real forward dependency graph.
- Spot-check 3-5 rows against the source `feature_spec.md` "Depends on:" line to confirm parity.

### Out of scope

- Adding a "Depended on by" (reverse-dependency) column. The current dashboard has no such surface; reverse lookups can come later if useful.
- UI / HTML styling changes. The bug is purely in the data layer.

## Scope signals

- **Backend:** 0 LOC (no API change).
- **Scripts:** ~30–80 LOC in `scripts/build_mvp1_dashboard.py` — narrowing the parser. Plus ~80 LOC test coverage.
- **Frontend:** 0 LOC.
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A.
- **Tests:** 1 new unit test file with ~5–10 cases covering the parser's edge cases. After the fix, run the regen end-to-end and visually spot-check 5 rows.

## Why not implemented inline in PR #200

PR #200 is doc-only — it adds the MVP1.5 release tier and the `feat_ubi_judgments` idea. Fixing the dashboard regen script would mix a `scripts/` code change into a `docs/`-only PR (different `paths-ignore` behavior in CI; different review lens). Per the inline-fix vs idea-file rubric in `CLAUDE.md`: "Fix requires a separate subsystem AND >250 LOC AND no immediate path to inline → Idea file." The dashboard regen script is a separate subsystem from the planning docs; mixing breaks reviewability.

The fix is bounded enough to ship in a follow-up PR with no further design work. ~60–90 minutes of work.

## Relationship to other work

- **Surfaced by [PR #200](https://github.com/SoundMindsAI/relyloop/pull/200)** — Gemini Code Assist flagged 4 instances when `feat_ubi_judgments` got added to the bloated lists. The bug pre-exists PR #200; this idea is the deferred-fix capture.
- **Adjacent to [`infra_dashboard_regen_pre_commit_conflict`](../infra_dashboard_regen_pre_commit_conflict/)** (status: TBD — also a dashboard-regen issue, but about pre-commit hook conflicts rather than "Depends on" parsing). May be worth bundling into a single dashboard-regen-quality PR if both are tackled together.
- **Does NOT block any planned feature.** The dashboard is internal planning surface; the bloated column doesn't break navigation or block decisions, it just makes "Depends on" non-actionable.
