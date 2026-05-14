# Dashboard regen pre-commit hook conflicts with stash-on-unstaged-files

**Date:** 2026-05-14
**Status:** Idea — captured during feat_judgments_periodic_resume_sweep impl-execute tangential sweep
**Origin:** `/impl-execute` Step 7 (commit) — `mvp1-dashboard-regen` pre-commit hook chronically blocked commit attempts during the feat_judgments_periodic_resume_sweep `/pipeline --auto` run, requiring multiple stash-pop-restage-recommit cycles.

## Problem

The pre-commit pipeline does:

1. Stash unstaged + untracked working-tree changes (via pre-commit's `--keep-index` mechanism).
2. Run hooks against the staged content + remaining working tree.
3. `mvp1-dashboard-regen` reads `ls docs/02_product/planned_features/` and rewrites `MVP1_DASHBOARD.md` + `mvp1_dashboard.html`.
4. Hook modifies files → pre-commit aborts the commit "files were modified by this hook."
5. Pre-commit unstashes — but if the dashboard regen's modifications conflict with the unstashed working-tree edits, the pop fails ("Rolling back fixes...") and the working tree ends up in a partially-applied state.

**Observed failure shape during `feat_judgments_periodic_resume_sweep` pipeline run (2026-05-14):**

```
[WARNING] Unstaged files detected.
[INFO] Stashing unstaged files to /Users/ericstarr/.cache/pre-commit/patch1778724393-61087.
...
Regenerate MVP1 dashboard if feature folders changed.......................Failed
- hook id: mvp1-dashboard-regen
- files were modified by this hook
...
[WARNING] Stashed changes conflicted with hook auto-fixes... Rolling back fixes...
[INFO] Restored changes from /Users/ericstarr/.cache/pre-commit/patch1778724393-61087.
```

After this, the index shows the dashboard modifications staged AND the user's unstaged work intermixed in ways that don't reflect any single commit's intent. The workaround used in the feat_judgments run was `git stash push --keep-index --include-untracked` to fully isolate the user's pending work before retrying the commit.

The dashboard hook is also overly aggressive: it regenerates on every commit, even when no planned-features folder actually changed. The cost is ~2 seconds per commit; the bigger problem is the stash-pop conflict surface.

## Proposed capabilities

Three independent improvements that compound:

### 1. Tighten the hook trigger to actual scope changes

The hook config currently has no `files:` regex — it runs on every commit. Add a filter:

```yaml
- id: mvp1-dashboard-regen
  files: ^docs/(02_product/planned_features|00_overview/implemented_features)/
```

Skip if no planned/implemented feature folder changed. Most commits (backend code, runbook tweaks, test additions) wouldn't trigger the hook.

### 2. Make the regen idempotent

Currently the regen unconditionally rewrites both `MVP1_DASHBOARD.md` and `mvp1_dashboard.html`. If the rewrite is content-equivalent (just timestamp changes, no semantic delta), pre-commit still sees "files modified" and aborts. Fix: hash the semantic content (excluding any timestamps) and only write if the hash changed.

### 3. Document the stash-conflict workaround

When unstaged work conflicts with hook output, the operator-facing path is:

```bash
git stash push --keep-index --include-untracked -m "pre-pre-commit-work"
git commit ...   # now clean
git stash pop    # may still conflict; manual merge required
```

Add this to `docs/03_runbooks/local-dev.md` or the pre-commit config comments.

### 4. Rewrite relative paths during one-liner extraction (added 2026-05-14)

Gemini Code Assist flagged this on PR #106: `scripts/build_mvp1_dashboard.py` extracts the first few hundred chars of each idea.md's "Problem" section and embeds them verbatim into `docs/00_overview/MVP1_DASHBOARD.md` and `mvp1_dashboard.html`. The idea.md lives at depth 4 (`docs/02_product/planned_features/<folder>/idea.md`) and uses `../../../../backend/...` to reach the repo root. The dashboard files live at depth 2 (`docs/00_overview/MVP1_DASHBOARD.md`), so the same string resolves to **outside** the repo. Result: every dashboard one-liner that references a `backend/...` path via relative link is broken.

Three fix options:

* **A — rewrite paths during extraction.** Detect markdown relative-link patterns in the extracted text and recompute the path against the dashboard's directory depth. Most robust.
* **B — use repo-rooted absolute paths in idea.md.** Switch idea.md authoring convention from `[file.py](../../../../backend/file.py)` to `[file.py](/backend/file.py)`. Markdown renderers (GitHub, VSCode) interpret leading-`/` as repo-rooted. Simpler script, but requires teaching authors a new convention.
* **C — strip links from the one-liner before embedding.** Regex out `[text](path)` → keep just `text`. Loses the click-through but the dashboard's "Feature" column already links to idea.md, so the one-liner doesn't strictly need its own links.

**Recommendation: B.** Convention is easy to teach (and `/idea-preflight` can enforce it), the script change is one line (no extraction-side path rewriting needed), and the resulting idea.md files render correctly on GitHub at their canonical path too.

Affected today: dashboard rows for any idea.md with backend/frontend link references in its Problem section. Visible immediately on `bug_query_inline_crud_since_filter_uuidv7_ms_collision` per Gemini's PR #106 inline comments at `MVP1_DASHBOARD.md:91` and `mvp1_dashboard.html:479`.

## Scope signals

- **Backend:** none (script in `scripts/build_mvp1_dashboard.py`).
- **Frontend:** none.
- **Migration:** none.
- **Config:** `.pre-commit-config.yaml` `files:` regex addition; `scripts/build_mvp1_dashboard.py` idempotency logic; runbook addendum.
- **Audit events:** N/A.

## Why deferred

The fix touches pre-commit hook config + the dashboard-regen script — a different subsystem from the worker-runtime feature this session was implementing. Bundling would have crossed a clean scope boundary.

## Relationship to other work

- Sibling chore: `infra_make_targets_split_backend_only` (captured during the same impl-execute session — same source of friction).
- No interference with planned MVP2 work.
