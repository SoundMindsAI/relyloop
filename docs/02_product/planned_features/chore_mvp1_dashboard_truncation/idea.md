# chore_mvp1_dashboard_truncation

**Type:** chore (regeneration-script bug — pre-existing, low impact)
**Date:** 2026-05-13
**Origin:** Gemini Code Assist findings F3 + F4 on PR #73 (dogfood-bug-chat-long-conv).

## Problem

The `mvp1-dashboard-regen` pre-commit hook
([`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py))
generates two artifacts —
[`docs/00_overview/MVP1_DASHBOARD.md`](../../../00_overview/MVP1_DASHBOARD.md)
and `mvp1_dashboard.html` — that summarize every `idea.md` /
`feature_spec.md` under `docs/02_product/planned_features/` and
`docs/00_overview/implemented_features/`. For idea-only entries it
calls `_extract_idea_problem` to pull the first paragraph under
`## Problem`. That helper caps the result at 240 chars via raw
character truncation:

```python
# scripts/build_mvp1_dashboard.py:127-139
def _extract_idea_problem(text: str) -> str:
    ...
    if len(para) > 240:
        para = para[:237] + "..."
    return para
```

This is character-blind. It happily cuts in the middle of:
- Markdown links (`[label]` without `(url)`, or `[label](url` without close)
- Inline code spans (` `` ` open without close)
- HTML attributes inside the generated `.html`

Visible breakage in [`MVP1_DASHBOARD.md` line 79](../../../00_overview/MVP1_DASHBOARD.md)
after PR #73 lands: the `bug_chat_long_conversation_truncation` entry's
one-liner ends mid-link with `...messages ([age` — the markdown link is
unclosed, the description trails off, and GitHub renders the rest of
the table cell awkwardly.

## Why it didn't surface earlier

The truncation has been pre-existing on `main` since the hook landed
(visible in committed `MVP1_DASHBOARD.md` for at least
`chore_test_both_engines`, `chore_trial_summary_single_query`,
`bug_digest_param_importance_seam`, `bug_dockerfile_missing_prompts`,
`bug_env_file_corrupted_during_session` — multiple rows truncated
mid-sentence on main). Most cuts land in plain prose where the broken
output is "ugly but readable." The
`bug_chat_long_conversation_truncation` row after the `/idea-preflight`
patch became the first one that cut mid-markdown-link, making the
issue visually obvious.

## Proposed fix

Replace the character-blind 237-char cut with a markdown-aware truncator:

1. **Truncate at sentence/word boundary, not character.** After the
   length check, walk backward from the cut point to the nearest
   `. `, `! `, or `? ` (sentence end) — fall back to nearest space
   if no sentence boundary exists within ~50 chars of the cut.
2. **Strip any unclosed markdown.** After cutting, count `[` vs `]`
   and `(` vs `)`; if unbalanced, walk back to the last balanced
   position. Same for inline-code backticks (odd count → walk back).
3. **Append `…` (single-char ellipsis) instead of `...`** so the
   cap+ellipsis fits in the 240 budget more often.
4. **For the HTML output**, also escape the truncated content with
   `html.escape()` if it isn't already — a truncated tag is worse
   than a broken link.

Anticipated diff: ~30 lines in
[`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py)
(new helper `_safe_truncate_markdown` + 2 call-sites:
`_extract_idea_problem` + `_extract_one_liner`'s sentence-split logic).
Plus 4–6 unit tests in `backend/tests/unit/scripts/test_dashboard_truncation.py`
covering: short input untouched, mid-link cut, mid-code-span cut,
mid-word cut, sentence-boundary preference, HTML-escape on the HTML
path.

## Scope signals

- Single-file script change + small new test file.
- No runtime impact on the application — only affects the auto-generated
  dashboard artifacts.
- Pre-commit hook re-runs on the next commit that touches a planned
  feature; the dashboards regenerate automatically with the new logic.

## Why deferred

Low-impact cosmetic issue on an internal artifact. Doesn't block
operators or developers. Fits naturally into a `/bug-fix` or
direct-ad-hoc PR whenever someone wants 30 minutes of clean-up work.

## Related work

- Discovered via Gemini Code Assist review on PR #73 — both findings
  pointed at the symptom; the root cause is the regen script.
- Not blocking PR #73's merge: the truncation behavior is pre-existing
  on `main`; PR #73 just shifted where the cut lands for one row.
