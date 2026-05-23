# Dashboard "Depends on" column bloat — shipped features list future ideas as dependencies

**Date:** 2026-05-22
**Status:** Idea — surfaced by Gemini Code Assist review on PR #200 (2026-05-22). Pre-existing bug; this PR only made one more entry visible.
**Priority:** P2 — dashboard is internal planning surface; the bloat doesn't break navigation, it just makes the "Depends on" column meaningless. No daily cost; not unblocking anything.
**Origin:** Gemini Code Assist findings on [PR #200](https://github.com/SoundMindsAI/relyloop/pull/200) flagged 4 instances of completed features (`feat_chat_agent`, `chore_tutorial_polish`) listing `feat_ubi_judgments` as a dependency. Verified by `git show main:docs/00_overview/MVP1_DASHBOARD.md | sed -n '35p'` — pre-PR-200, `feat_chat_agent` already had **45** backtick'd feature names in its "Depends on" column, including dozens of features that shipped *after* it. PR #200 only added one more (`feat_ubi_judgments`) to the existing list; the underlying bug is in the dashboard-regen script's parser, not in the planning artifacts.
**Depends on:** None.

## Problem

[`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) (2,084 lines) generates the "Depends on" column for each row in [`MVP1_DASHBOARD.md`](../../../00_overview/MVP1_DASHBOARD.md) and `mvp1_dashboard.html`. Two shipped features render impossibly-large dependency lists:

- **`feat_chat_agent`** shipped 2026-05-12 (PR #60). Its "Depends on" column lists 46 entries, including `feat_pr_metric_confidence` (shipped 2026-05-21), `feat_study_clone_from_previous` (idea only), `feat_ubi_judgments` (idea only, dated 2026-05-22). A merged feature can't depend on features that didn't exist yet.
- **`chore_tutorial_polish`** shipped 2026-05-12 (PR #64). Same shape — 42 backtick'd entries, most shipped weeks later or still unscoped.

The **actual root cause** (confirmed by reading the code, not by inference from symptoms — the prior diagnosis in this idea was wrong):

1. The parser at [`build_mvp1_dashboard.py:435-456`](../../../../scripts/build_mvp1_dashboard.py) is **already correctly scoped** to the `- Depends on:` line via `re.search(r"^-\s+Depends on:\s*(.+)$", ..., re.MULTILINE)`. It does not scan the whole document; it correctly extracts only the canonical bullet line.
2. The bloat lives in the **sentinel-expansion logic** at [`build_mvp1_dashboard.py:707-714`](../../../../scripts/build_mvp1_dashboard.py). The parser recognizes the prose markers `"all prior backend features"` / `"all prior mvp1 features"` (defined as `_TRANSITIVE_DEP_PHRASES` at line 413) and adds the `DEPS_ALL_BACKEND` sentinel. The expansion block then replaces that sentinel with **every `infra_*` and `feat_*` folder in the current snapshot**, with no time-ordering filter:

```python
backend_folders = sorted(f.folder for f in features if f.prefix in ("infra", "feat"))
for f in features:
    if DEPS_ALL_BACKEND not in f.depends_on:
        continue
    explicit = [d for d in f.depends_on if d != DEPS_ALL_BACKEND]
    merged = sorted(set(explicit) | set(backend_folders) - {f.folder})
    f.depends_on = merged
```

So a feature like `feat_chat_agent` that genuinely meant "everything merged before me on 2026-05-12" inherits today's full backend roster — including 30+ features that shipped *after* it and a handful of planned ideas that don't exist on disk as code yet. Only **two** features use the transitive phrase (verified by `grep -rlE "^- Depends on:.*(ALL prior|all backend|all MVP)" docs/`), so the fix surface is narrow.

The fix is to time-order the sentinel expansion — for shipped features, restrict the expansion to backend folders that merged on or before this feature's merge date. For planned features that still use the transitive phrase (none today, but the planned `feat_ubi_judgments` etc. don't use it), the current-snapshot expansion remains correct (a planned feature genuinely depends on everything in the queue).

## Proposed capabilities

Single tier — time-order the sentinel expansion; no schema, no UI, no parser change.

### Sentinel-expansion correction

**Scope:** [`scripts/build_mvp1_dashboard.py:703-714`](../../../../scripts/build_mvp1_dashboard.py) — the block that resolves `DEPS_ALL_BACKEND` against `backend_folders`.

**Fix design (recommended default — lock during /bug-fix or /spec-gen):**

1. **Derive a merge-order key** for every feature in the loaded set. Shipped features have a `pr_number` (already parsed by `_extract_pr_number` at line 476+) and/or a folder prefix `YYYY_MM_DD_` from their `implemented_features/` path. Planned features have neither — they're "post-everything-shipped" in dependency terms.
2. **Filter the expansion per-feature:**
   - For a **shipped feature** `f` using the transitive marker, expand `DEPS_ALL_BACKEND` to only those backend folders whose merge order is strictly less than `f`'s merge order. Use the folder date prefix (`YYYY_MM_DD_`) for shipped peers and treat planned features as having infinite merge order (i.e., never included).
   - For a **planned feature** using the transitive marker (none today; defensive only), keep the current behavior — expand to every backend folder in the snapshot, since a planned feature genuinely depends on everything queued.
3. **Tiebreaker** when two shipped features share the same date prefix (e.g., both 2026-05-12): use PR number ascending; if PR numbers are equal or absent, fall back to lexicographic folder name. This is a rare case but worth pinning.

**Expected post-fix outcomes:**

- `feat_chat_agent` ([`implemented_features/2026_05_12_feat_chat_agent/`](../../../00_overview/implemented_features/2026_05_12_feat_chat_agent/)) "Depends on" column drops from 46 entries to the count of `infra_*`/`feat_*` folders that shipped on or before 2026-05-12: `infra_foundation` (2026-05-09), `infra_adapter_elastic` (2026-05-10), `infra_optuna_eval` (2026-05-10), `feat_study_lifecycle` (2026-05-10), `feat_llm_judgments` (2026-05-11), `feat_digest_proposal` (2026-05-11), `feat_github_pr_worker` (2026-05-12), `feat_github_webhook` (2026-05-12), `feat_studies_ui` (2026-05-12), `feat_proposals_ui` (2026-05-12). That's roughly 10 entries — coherent and time-consistent.
- `chore_tutorial_polish` (also 2026-05-12, PR #64) drops from 42 entries to the same set (it's the release-readiness chore; "ALL prior MVP1 features" really does mean "everything up to PR #64").
- All other shipped features that DON'T use the transitive phrase are unchanged (their `- Depends on:` lines list explicit folders; no sentinel involved).

**Regression test plan:**

Add a unit test alongside the existing test fixtures for the regen script. Two cases:

1. Lock the fix: a `feat_chat_agent`-shaped fixture (folder prefixed `2026_05_12_*`, spec body says `- Depends on: ALL prior backend features`) gets expanded against a feature set that includes one before (`2026_05_09_*`), one same-day (`2026_05_12_*` with lower PR#), and one after (`2026_05_21_*`). Expected: only the before + same-day-lower-PR neighbors appear, not the after.
2. Lock the unchanged-behavior path: a planned-feature fixture using the transitive phrase gets expanded against the full snapshot (current behavior preserved).

Test file location: `scripts/tests/test_dashboard_depends_on_expansion.py` if a scripts test dir exists; otherwise `backend/tests/unit/scripts/test_dashboard_depends_on_expansion.py`. Verify the location during /bug-fix.

### Verify the bloated rows shrink

After the fix, re-run `python scripts/build_mvp1_dashboard.py`. Confirm:

- `feat_chat_agent` row backtick'd-entry count drops from 46 to ~10.
- `chore_tutorial_polish` row drops from 42 to ~10.
- Every other shipped feature's row is byte-identical to its pre-fix state (no collateral churn).
- Spot-check both shrunk rows against the time-ordered subset by hand.

### Out of scope

- Changing the parser (already correctly scoped — see Problem section).
- Adding a "Depended on by" (reverse-dependency) column. The current dashboard has no such surface; reverse lookups can come later if useful.
- UI / HTML styling changes. The bug is purely in the data layer.

## Scope signals

- **Backend:** 0 LOC (no API change).
- **Scripts:** ~20–40 LOC in `scripts/build_mvp1_dashboard.py` — adding a per-feature merge-order filter to the `DEPS_ALL_BACKEND` expansion block at lines 703-714. Plus ~80 LOC test coverage.
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
- **Adjacent to [`infra_dashboard_regen_pre_commit_conflict`](../../../00_overview/implemented_features/2026_05_14_infra_dashboard_regen_pre_commit_conflict/)** (shipped 2026-05-14 — pre-commit hook conflicts on idempotent regen + relative-link rewriting). Touches the same script but at a different layer (pre-commit hook contract), so no bundling needed; cited only for context.
- **Does NOT block any planned feature.** The dashboard is internal planning surface; the bloated column doesn't break navigation or block decisions, it just makes "Depends on" non-actionable.
