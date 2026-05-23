# Dashboard release classifier doesn't recognize half-step releases (MVP1.5, etc.) — those features bleed into MVP1_DASHBOARD.md

> **Folder-name note:** This bug was initially filed as `bug_dashboard_classifier_missing_mvp1_5`. Implementing the fix immediately revealed the name itself triggered the new half-step regex (`r"_mvp(\d+(?:_\d+)?)$"`) — classifying the bug folder as an MVP1.5 feature and putting it in `MVP1_5_DASHBOARD.md`. Renamed to `bug_dashboard_classifier_half_step_releases` so the descriptive form doesn't collide with the release-tag suffix convention. **General rule for future folders:** if a feature is *about* MVP1.5 (rather than scoped to it), avoid using the literal `mvp1_5` substring in the folder's descriptive tail — use `half_step` or similar.

**Date:** 2026-05-23
**Status:** Idea — surfaced when `/pipeline status` ranked `feat_ubi_judgments` (MVP1.5 anchor) as #1 in the MVP1 backlog
**Priority:** P1 — distorts every `/pipeline status` output and the MVP1 dashboard until fixed. Operators can't trust the priority order.
**Origin:** During a 2026-05-23 `/pipeline status` invocation, the operator noticed `feat_ubi_judgments` ranked first in the MVP1 prioritized backlog. The idea body explicitly says it's the MVP1.5 / v0.1.5 "Real Signals" anchor feature — it shouldn't appear in MVP1's queue at all.
**Depends on:** None.

## Problem

The MVP1.5 release tier was introduced 2026-05-23 via PR #200 (canonical release matrix + spec §27 + tech-stack.md). But the dashboard regen script's release classifier at [`scripts/build_mvp1_dashboard.py:134-158`](../../../../scripts/build_mvp1_dashboard.py#L134-L158) was never updated to recognize it. Three concrete gaps:

1. **`_RELEASE_SUFFIX_RE`** at [`build_mvp1_dashboard.py:127`](../../../../scripts/build_mvp1_dashboard.py#L127) — pattern `r"_mvp(\d+)$"` matches only integer release tags (`_mvp2`, `_mvp3`). A folder named `_mvp1_5` (the natural suffix convention for half-steps since folder names can't have dots) doesn't match.
2. **`_RELEASE_STATUS_RE`** at [`build_mvp1_dashboard.py:130`](../../../../scripts/build_mvp1_dashboard.py#L130) — pattern `r"Held\s+for\s+MVP\s*(\d+)"` matches only integer release tags AND only the "Held for" prose framing. `feat_ubi_judgments`'s status line says `Idea — anchor feature for MVP1.5 / v0.1.5 "Real Signals"` — both the `1.5` decimal and the `anchor … for` framing miss.
3. **`ROADMAP_RELEASES`** at [`build_mvp1_dashboard.py:57-64`](../../../../scripts/build_mvp1_dashboard.py#L57-L64) — the tuple list has no `mvp1.5` entry between `mvp1` and `mvp2`, so even if the classifier returned `"mvp1.5"`, the roadmap roll-up at the top level wouldn't have a row for it. (The per-release dashboard files would still get emitted by [`main()`](../../../../scripts/build_mvp1_dashboard.py#L2096) via the `discovered = sorted({f.release for f in features} | {DEFAULT_RELEASE})` logic, but the roadmap navigation would be stale.)

Result: `feat_ubi_judgments` falls through to `DEFAULT_RELEASE = "mvp1"` and gets rendered in `MVP1_DASHBOARD.md`. The sort within that dashboard correctly puts P1 ahead of P2 (it's working as designed given the input), so the MVP1.5 anchor appears as the top item in the MVP1 priority queue. Same fate awaits any future MVP1.5 idea — `feat_ubi_judgments` is just the canary.

## Why this matters

`/pipeline status` mirrors `MVP1_DASHBOARD.md`'s Idea table (per the PR #210 sort-unify fix). When the dashboard's release classification is wrong, every operator using `/pipeline status` gets a wrong-priority answer. The operator currently has to mentally subtract MVP1.5 items from the top of the list — defeating the purpose of having an authoritative "what's next" tool.

## Proposed fix

Single tier — extend the classifier; no schema, no UI, no operator action required.

### Recognize half-step release tags

- **Folder-suffix form:** `_mvp1_5` (the natural underscore-instead-of-dot convention; consistent with other underscore-separated tokens in folder names per [`feature_templates/README.md`](../feature_templates/README.md)). Extend `_RELEASE_SUFFIX_RE` from `r"_mvp(\d+)$"` to `r"_mvp(\d+(?:_\d+)?)$"`. Normalize the captured `"1_5"` → `"1.5"` before building the release string.
- **Status-line form:** `anchor feature for MVP1.5`, `MVP1.5 anchor`, `Held for MVP1.5`. Extend `_RELEASE_STATUS_RE` to match both prefix framings AND the decimal form. Proposed pattern: `r"(?:Held\s+for|anchor\s+(?:feature\s+)?for)\s+MVP\s*(\d+(?:\.\d+)?)"`.

### Add MVP1.5 to the roadmap roll-up

- Insert `("mvp1.5", "MVP1.5 / v0.1.5", "Real Signals")` into `ROADMAP_RELEASES` between `mvp1` and `mvp2`. The sort `sorted({f.release for f in features} | {DEFAULT_RELEASE})` in `main()` will place `"mvp1.5"` between `"mvp1"` and `"mvp2"` (string sort works because `mvp1.5 < mvp1z`; verified).

### File naming for the new dashboard

- `_dashboard_paths(release)` currently does `release.upper()` to derive `MVPN_DASHBOARD.md`. For `"mvp1.5"` that produces `"MVP1.5_DASHBOARD.md"` — dots in filenames are legal on macOS/Linux but read awkwardly. Normalize dots → underscores for filenames: `release.replace(".", "_")` → `mvp1_5_dashboard.html` + `MVP1_5_DASHBOARD.md`. Internal release identifier stays `"mvp1.5"` (used in roadmap labels + sort key); filename-safe form is derived where written to disk.

### Display-name suffix stripping

- `Feature.display_name` at [`build_mvp1_dashboard.py:118-124`](../../../../scripts/build_mvp1_dashboard.py#L118-L124) strips a trailing `_mvpN` from the visible label so the release tag doesn't double-print on dashboard cards. Extend the regex to also strip `_mvp\d+_\d+` (half-step).

## Scope signals

- **Backend:** 0 LOC (no API change).
- **Scripts:** ~30 LOC in `scripts/build_mvp1_dashboard.py` — three regex extensions + one tuple-list insertion + one path-normalization tweak + one display-name regex update.
- **Frontend:** 0 LOC.
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A.
- **Tests:** new unit test file at `backend/tests/unit/scripts/test_dashboard_release_classifier.py` (~5-8 cases): half-step suffix matches, half-step status-line matches, status-line "anchor for" framing matches, status-line "Held for" framing still matches (regression), integer suffix still matches (regression), `_dashboard_paths("mvp1.5")` produces underscore-form filenames, `Feature.display_name` strips the half-step suffix.

## Verification (end-to-end)

After the fix, re-run `python scripts/build_mvp1_dashboard.py`:

- A new file `docs/00_overview/MVP1_5_DASHBOARD.md` exists with `feat_ubi_judgments` as its only Idea-table entry.
- `MVP1_DASHBOARD.md`'s Idea table drops from 14 → 13 entries; the new top row is `#1 P2 feat_auto_followup_studies` (or whatever the new highest-priority MVP1.0-scoped item is).
- The script's stdout line `mvp1.5: 1 features` appears in the regen output.
- `/pipeline status` (re-rendered) shows the same 13 entries; `feat_ubi_judgments` no longer appears in the MVP1 backlog.

## Out of scope

- Backfilling `_mvp1_5` folder-suffix renames on existing MVP1.5 ideas. Only `feat_ubi_judgments` exists today; its status line ("anchor feature for MVP1.5") gives the classifier the signal it needs. Folder renames can wait until there are 2+ MVP1.5 ideas and the operator wants to enforce the suffix convention.
- Generalizing to `mvp2.5`, `mvp3.5`, etc. The regex changes make this work automatically once a status line says "Held for MVP2.5"; no further code needed.

## Relationship to other work

- **Surfaced by [PR #210](https://github.com/SoundMindsAI/relyloop/pull/210)** (the sort-unify chore) — once the sort algorithm was made authoritative, the misclassification became visible at the top of the dashboard. PR #210 didn't introduce the bug; it made the bug operator-felt.
- **Adjacent to [`chore_dashboard_pr_extraction_from_idea`](../chore_dashboard_pr_extraction_from_idea/idea.md)** — same `build_mvp1_dashboard.py` file, different layer of the regen pipeline. No bundling needed; ship independently.
