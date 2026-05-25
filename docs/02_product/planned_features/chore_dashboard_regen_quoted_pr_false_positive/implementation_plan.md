# Implementation Plan — chore_dashboard_regen_quoted_pr_false_positive

**Date:** 2026-05-25
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) — two-PR finalization pattern, never `--no-verify`; [`impl-execute SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md) — Step 7 finalization

---

## 0) Planning principles

- Spec traceability first: every story maps to ≥1 FR.
- Atomic per-FR commits — each story is independently reviewable and revertible.
- Two-PR rollout per [`feature_spec.md` §3 "Phase boundaries"](feature_spec.md): PR A ships Epic 1 (FRs 1–4 — helper + wire-in + 7 tests + docstring); PR B ships Epic 2 (FR-5, post-merge finalization).
- Never bypass pre-commit hooks (CLAUDE.md absolute rule 7).
- No regression on the existing 24+ test methods in `test_dashboard_pr_extraction.py`.

## 1) Scope traceability (FR → epics)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 | Epic 1 / Story 1.1 | Add `_strip_backtick_quoted_segments` helper (3 fence flavors: multi-line, single-line, empty) |
| FR-2 | Epic 1 / Story 1.2 | Wire helper into `_extract_pr_number` priority-3 at line 628 |
| FR-3 | Epic 1 / Story 1.3 | Add `TestBacktickStripPriority3` class with 7 test methods (AC-6..AC-12) |
| FR-4 | Epic 1 / Story 1.4 | Insert one-sentence docstring note about backtick strip |
| FR-5 | Epic 2 / Story 2.1 | Post-merge `git mv` folder + `state.md` update |

All 5 FRs from [`feature_spec.md` §7](feature_spec.md) are covered. No deferred phases (spec §3 explicitly notes "Single phase, single PR" content + standard 2-PR finalization shape, not a deferred-capability boundary). No `phase2_idea.md` needed.

## 2) Delivery structure

**Epic → Story → Tasks → DoD** pattern, scoped to the two PRs:

- **Epic 1 (PR A — Content + Tests):** Stories 1.1–1.4. Modifies `scripts/build_mvp1_dashboard.py` (new helper + wire-in + docstring sentence) and `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` (new test class with 7 methods). Ships against `feature/chore-dashboard-regen-quoted-pr-false-positive`.
- **Epic 2 (PR B — Finalization):** Story 2.1. Folder move + state.md recent-changes entry. Ships against `docs/finalize-chore-dashboard-regen-quoted-pr-false-positive` (branch created off post-A `main`).

### Conventions

- All edits use the project's standard pre-commit hook stack (ruff format/check, mypy, prettier, eslint, gitleaks secret scan, dashboard regen, conventional-commit validator). Never `--no-verify`.
- Conventional Commits prefix: `fix(dashboard):` for FR-1/2 (helper + wire-in correct a bug); `test(dashboard):` for FR-3 (new tests); `docs(dashboard):` for FR-4 (docstring note); `docs:` for FR-5 (finalization, matching recent main pattern `2a24fae4 docs: finalize ... after PR #N`).
- Every commit body includes the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

### AI Agent Execution Protocol (applies to every story)

0. **Load context first** (already done — this plan was generated with full context).
1. **Read scope** — verify the story's FR, target file, target line range, and DoD.
2. **Re-Read the target file/section** to confirm line ranges haven't shifted since spec authoring. `git log -1 -- <path>` should show no commits since the spec commit (`04e5e8f0`).
3. **Apply the edit** via `Edit` or `Write`.
4. **Verify** with the test/grep assertions in the DoD.
5. **Commit** atomically (one story = one commit).
6. **Run the targeted unit test suite after each story that adds tests** (Story 1.3): `.venv/bin/pytest backend/tests/unit/scripts/test_dashboard_pr_extraction.py -v` must show 7 new tests passing + the existing 24+ still green.
7. **Pre-push gate** (per [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 4): `make fmt && make lint && make typecheck && .venv/bin/ruff format --check backend/` before push.

Story completion is invalid if any step is skipped.

---

## Epic 1 — Content + Tests (FRs 1–4)

### Story 1.1 — Add `_strip_backtick_quoted_segments` helper
**Outcome:** [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) gains a new module-level function `_strip_backtick_quoted_segments(text: str) -> str` placed immediately after `_strip_dependency_table_rows` (currently ending at line ~498). The function removes all 3 fence flavors (multi-line fenced blocks, single-line triple-backtick fences, empty fences) AND all inline backtick spans (including empty inline spans per AC-11). [`feature_spec.md` FR-1 / AC-10 / AC-11 / AC-12](feature_spec.md).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `scripts/build_mvp1_dashboard.py` | Add `_strip_backtick_quoted_segments` function (~10–15 LOC) immediately after `_strip_dependency_table_rows`. |

**Key interfaces**

```python
def _strip_backtick_quoted_segments(text: str) -> str:
    """Remove backtick-fenced segments before fuzzy PR# matching.

    Strips three fence flavors: multi-line triple-backtick blocks (```...```
    spanning newlines), single-line triple-backtick fences (```...``` on one
    line), and inline backtick spans (`...`). Empty fences/spans are removed
    (substituted with empty string).

    Composes with _strip_dependency_table_rows in _extract_pr_number's
    priority-3 path.
    """
```

**Tasks**

1. Re-Read lines 488–500 of `scripts/build_mvp1_dashboard.py` to locate the end of `_strip_dependency_table_rows` and find the insertion point (immediately after the function's `return` statement, before the next module-level definition).
2. Implement using a two-pass regex approach for safety:
   - Pass A: `text = re.sub(r"`{3,}.*?`{3,}", "", text, flags=re.DOTALL)` — handles multi-line + single-line + empty triple-backtick fences in one regex. `` `{3,} `` matches 3 OR MORE backticks (per spec FR-1: "three or more backticks at the start and another three or more backticks at the end" — accommodates markdown's 4+ backtick convention for embedding 3-backtick blocks). `.*?` is non-greedy; `re.DOTALL` allows `.` to match newlines.
   - Pass B: `text = re.sub(r"`[^`\n]*`", "", text)` — handles inline backtick spans, including empty `` `` `` (note the `*` — zero or more chars, per AC-11 + spec D-7).
   - Return the result.
3. Verify the function is exported via the module's existing convention (the existing `_strip_dependency_table_rows` is module-level and accessed via `scripts.build_mvp1_dashboard._strip_dependency_table_rows` in tests — no `__all__` export needed; underscored module-level functions are importable).
4. Save the file; the pre-commit hook will lint and format.

**Definition of Done**

- Function exists at the planned location: `grep -n '^def _strip_backtick_quoted_segments' scripts/build_mvp1_dashboard.py` returns one line, and it appears immediately after `_strip_dependency_table_rows`'s end.
- Importable: `python3 -c "from scripts.build_mvp1_dashboard import _strip_backtick_quoted_segments; print(_strip_backtick_quoted_segments('test'))"` returns `'test'`.
- Multi-line strip works: `python3 -c "from scripts.build_mvp1_dashboard import _strip_backtick_quoted_segments as f; print(repr(f('a\n\`\`\`\nbody\n\`\`\`\nb')))"` returns `"'a\n\nb'"` (or similar with the fence + body fully removed).
- Single-line strip works: `python3 -c "from scripts.build_mvp1_dashboard import _strip_backtick_quoted_segments as f; print(f('a \`\`\`PR #1 merged\`\`\` b'))"` does not contain `PR #1`.
- Inline strip works (incl. empty): `python3 -c "from scripts.build_mvp1_dashboard import _strip_backtick_quoted_segments as f; print(f('before \`\` middle \`x\` after'))"` does not contain `x` AND does not raise.
- Pre-commit hooks pass (no `--no-verify`).

---

### Story 1.2 — Wire helper into `_extract_pr_number` priority-3
**Outcome:** Line 628 of `_extract_pr_number` is modified so that `_strip_backtick_quoted_segments` runs BEFORE `_strip_dependency_table_rows` on the joined `pipe + "\n" + plan + "\n" + spec` input. Net effect: backtick-quoted PR# tokens never reach the priority-3 fuzzy regexes at lines 629/632. [`feature_spec.md` FR-2 / AC-6 / AC-7 / AC-8 / AC-9](feature_spec.md).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `scripts/build_mvp1_dashboard.py` | Modify line 628 (the existing `combined = _strip_dependency_table_rows(pipe + "\n" + plan + "\n" + spec)` assignment) to wrap the inner expression with `_strip_backtick_quoted_segments(...)`. |

**Tasks**

1. Re-Read lines 624–635 of `scripts/build_mvp1_dashboard.py` to confirm the current line 628 still reads `combined = _strip_dependency_table_rows(pipe + "\n" + plan + "\n" + spec)`. If drifted, escalate.
2. Edit with `old_string = "    combined = _strip_dependency_table_rows(pipe + \"\\n\" + plan + \"\\n\" + spec)"` and `new_string`:
   ```python
       combined = _strip_dependency_table_rows(
           _strip_backtick_quoted_segments(pipe + "\n" + plan + "\n" + spec)
       )
   ```
   Note: 4-space indentation, three-line factoring is acceptable per spec FR-2 ("equivalent factorings are acceptable").
3. Verify priority-3 still fires correctly on un-backticked own-PR prose by running the existing test:
   `.venv/bin/pytest backend/tests/unit/scripts/test_dashboard_pr_extraction.py::TestPriorityCascade::test_ac9_fuzzy_merged_in_spec_beats_idea -v` — must pass (regression guard).
4. Pre-commit hooks pass.

**Definition of Done**

- The modified line(s) in `_extract_pr_number` invoke `_strip_backtick_quoted_segments` BEFORE `_strip_dependency_table_rows`: `grep -A1 'combined = _strip_dependency_table_rows' scripts/build_mvp1_dashboard.py | head -5` shows the new nested call shape.
- Existing `TestPriorityCascade::test_ac9_fuzzy_merged_in_spec_beats_idea` test still passes (regression guard — proves un-backticked own-PR prose still matches priority-3 correctly).
- All other priorities (1, 2, 3.5, 3.6, 4) unchanged — `git diff` shows changes ONLY at line 628 (and the surrounding lines if multi-line factoring chosen).
- Pre-commit hooks pass.

---

### Story 1.3 — Add `TestBacktickStripPriority3` class with 7 test methods
**Outcome:** [`backend/tests/unit/scripts/test_dashboard_pr_extraction.py`](../../../../backend/tests/unit/scripts/test_dashboard_pr_extraction.py) gains a new test class `TestBacktickStripPriority3` placed after the existing `TestBackwardCompat` class, with exactly 7 test methods named per AC-6 through AC-12. [`feature_spec.md` FR-3 / AC-6..AC-12](feature_spec.md).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` | Append new `TestBacktickStripPriority3` class at end of file with 7 test methods. Update the import block at the top to add `_strip_backtick_quoted_segments` to the existing `from scripts.build_mvp1_dashboard import (...)` block. |

**Tasks**

1. Re-Read the existing import block at the top of `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` to confirm the import shape (current block imports `_extract_pr_number` and the regex constants from the same module).
2. Add `_strip_backtick_quoted_segments` to the import block (alphabetical or end-of-list — match existing style).
3. Re-Read the end of the file (last ~30 lines) to locate the `TestBackwardCompat` class's last test method, which is the insertion point for the new class.
4. Append the new class:

```python
class TestBacktickStripPriority3:
    """Locks the false-positive rejection added by chore_dashboard_regen_quoted_pr_false_positive.

    Spec FR-3 / ACs 6-12. The priority-3 fuzzy regexes at scripts/build_mvp1_dashboard.py:629
    and :632 must not match backtick-quoted PR-merge phrases, while still matching legitimate
    un-backticked own-PR prose (regression guard via AC-9).
    """

    def test_ac6_inline_backtick_quoted_merged_pr_returns_none(self) -> None:
        # `**Depends on:** [infra_foundation] -- merged via PR #4 (2026-05-09)` (inline backtick)
        spec = (
            "Some prose.\n\n"
            "Example: `**Depends on:** [infra_foundation] -- merged via PR #4 (2026-05-09)`\n\n"
            "More prose."
        )
        assert _extract_pr_number("", "", spec, "") is None

    def test_ac7_multiline_triple_backtick_block_with_merged_pr_returns_none(self) -> None:
        spec = "Header.\n\n```python\n# Example: see PR #99 (merged 2026-05-15)\n```\n\nFooter."
        assert _extract_pr_number("", "", spec, "") is None

    def test_ac8_inline_backtick_with_pr_first_then_merged_returns_none(self) -> None:
        # First-regex ordering: PR #N ... merged
        spec = "Note: `PR #42 was merged on 2026-05-01` for context."
        assert _extract_pr_number("", "", spec, "") is None

    def test_ac9_unbacktickend_prose_own_pr_still_matches(self) -> None:
        # Regression guard: un-backticked own-PR prose still matches priority-3 fuzzy.
        spec = "## Status\n\nThis feature merged 2026-05-15 as PR #200 (squash)."
        assert _extract_pr_number("", "", spec, "") == 200

    def test_ac10_backtick_strip_runs_before_dependency_table_strip(self) -> None:
        # Verify the helpers compose correctly: backtick strip removes its scope without
        # touching dependency-table-row content (which the sibling helper handles).
        text = "| foo | Implemented (PR #1) |\n\n`Example: merged via PR #99`\n\nMore."
        result = _strip_backtick_quoted_segments(text)
        assert "PR #99" not in result
        assert "| foo | Implemented (PR #1) |" in result

    def test_ac11_empty_backtick_segment_does_not_crash(self) -> None:
        # Empty inline span `` and empty triple-backtick fence ```\n``` must be removed
        # without raising IndexError/TypeError/regex error.
        text = "before `` after\n```\n```\nfinal"
        result = _strip_backtick_quoted_segments(text)
        assert isinstance(result, str)
        # The empty segments must be removed (substituted with empty string).
        assert "``" not in result
        assert "```" not in result

    def test_ac12_single_line_triple_backtick_fence_returns_none(self) -> None:
        # Single-line ```...``` (no embedded newline). A regex that only matches
        # multi-line ```\n...\n``` would miss this and produce a false positive.
        spec = "Inline example: ```PR #77 merged 2026-05-03``` for context."
        assert _extract_pr_number("", "", spec, "") is None
```

5. Save the file; pre-commit hooks run.
6. Run the targeted test: `.venv/bin/pytest backend/tests/unit/scripts/test_dashboard_pr_extraction.py::TestBacktickStripPriority3 -v` — all 7 tests must pass.
7. Run the full file: `.venv/bin/pytest backend/tests/unit/scripts/test_dashboard_pr_extraction.py -v` — all 24+ existing + 7 new tests pass (= 31+ passing).

**Definition of Done**

- New class exists: `grep -n '^class TestBacktickStripPriority3' backend/tests/unit/scripts/test_dashboard_pr_extraction.py` returns one line.
- All 7 method names present: `grep -c '    def test_ac\(6\|7\|8\|9\|10\|11\|12\)_' backend/tests/unit/scripts/test_dashboard_pr_extraction.py` returns 7.
- `.venv/bin/pytest backend/tests/unit/scripts/test_dashboard_pr_extraction.py -v` — all tests pass; the new TestBacktickStripPriority3 class shows 7 passing.
- Import block at top of file includes `_strip_backtick_quoted_segments`.
- Pre-commit hooks pass.

---

### Story 1.4 — Insert docstring note about backtick strip
**Outcome:** The `_extract_pr_number` docstring at lines 582–608 of `scripts/build_mvp1_dashboard.py` gets one new sentence noting that priority 3 strips backtick-fenced segments before fuzzy matching, AND citing the new helper function name. [`feature_spec.md` FR-4](feature_spec.md).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `scripts/build_mvp1_dashboard.py` | Insert one sentence in the docstring's priority-3 description (currently lines 589–592). |

**Tasks**

1. Re-Read lines 580–610 of `scripts/build_mvp1_dashboard.py`. Find the priority-3 description block — currently ends with `"Dependency-table rows are stripped first so PR numbers cited as 'Implemented (PR #N)' in a Dependencies row don't leak through."` at ~line 591–592.
2. Append one sentence to that block, e.g.:
   ```
       Backtick-fenced segments (multi-line triple-backtick blocks, single-line
       triple-backtick fences, and inline backtick spans) are stripped via
       _strip_backtick_quoted_segments BEFORE _strip_dependency_table_rows so
       quoted PR-merge phrases in spec narrative don't leak through either.
   ```
3. Save; pre-commit hooks run.

**Definition of Done**

- Docstring contains the new sentence: `grep -A2 'don'"'"'t leak through' scripts/build_mvp1_dashboard.py | head -5` shows both the old "Dependency-table rows ... don't leak through" sentence AND the new "Backtick-fenced segments ... don't leak through" sentence.
- Docstring still passes: `python3 -c "import scripts.build_mvp1_dashboard as m; print(m._extract_pr_number.__doc__[:200])"` returns the docstring including the new content.
- No code changes outside the docstring: `git diff scripts/build_mvp1_dashboard.py` shows only the new docstring sentence (no logic changes).
- Pre-commit hooks pass.

---

### Epic 1 phase gate

Before opening PR A:

1. Run `make test-unit` from repo root (via `/Users/ericstarr/relyloop`'s venv — same approach `chore_e2e_seed_acme_idea_obsolete` PR #250 used since the sibling worktree may not have its own venv). Expected: **all tests pass + the new TestBacktickStripPriority3 class shows 7 passing**.
2. Run `make lint && make typecheck && ./.venv/bin/ruff format --check backend/`. Expected: clean.
3. `git log --oneline origin/main..HEAD` — expected: **7 commits** (preflight + spec + plan + 4 story commits = 7 total at Epic 1 phase gate). Stories 1.1, 1.2, 1.3, 1.4 are each their own commit.
4. Run [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 6's pre-push gate cumulative-diff GPT-5.5 phase-gate review against the cumulative Epic 1 diff. Expected: 0 High-severity findings (small script change with clear test coverage).
5. Push the branch (`git push -u origin feature/chore-dashboard-regen-quoted-pr-false-positive`) and open PR A via `gh pr create`.

---

## Epic 2 — Finalization PR (FR-5)

### Story 2.1 — Move chore folder to implemented_features (post-merge)
**Outcome:** After PR A merges to `main`, the chore folder is renamed under `implemented_features/` per [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 7 finalization. `state.md` gets a recent-changes entry naming PR A's number. [`feature_spec.md` FR-5](feature_spec.md).

**Trigger:** PR A has been merged to `main`. The local main branch has been synced (`git fetch origin main`).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `docs/02_product/planned_features/chore_dashboard_regen_quoted_pr_false_positive/*` | Move (via `git mv`) the entire folder to `docs/00_overview/implemented_features/2026_05_25_chore_dashboard_regen_quoted_pr_false_positive/`. |
| `state.md` | Append a recent-changes entry naming PR A's number. PR B's number is NOT included (it doesn't exist at commit time). |
| `docs/02_product/planned_features/chore_dashboard_regen_quoted_pr_false_positive/implementation_plan.md` | Update Status: `Ready for Execution` → `Complete (PR #<A>, merged 2026-05-25)`. Mark execution tracker rows `[x]` with commit SHAs. (Edit happens at OLD path then `git mv` per the CLAUDE.md "edit first, then git mv" anti-pattern — per the PR #252 finalization commit pattern, edit AFTER `git mv` at the NEW path is what works.) |
| `docs/02_product/planned_features/chore_dashboard_regen_quoted_pr_false_positive/pipeline_status.md` | Update Implementation section: `Not started` → `Complete`. Add `## Done` section. (Same `git mv` ordering caveat.) |

**Tasks**

1. From a fresh worktree off origin/main (`git worktree add /private/tmp/relyloop-finalize-dashboard-regen-regex -b docs/finalize-chore-dashboard-regen-quoted-pr-false-positive origin/main`), `cd` in.
2. `git mv docs/02_product/planned_features/chore_dashboard_regen_quoted_pr_false_positive docs/00_overview/implemented_features/2026_05_25_chore_dashboard_regen_quoted_pr_false_positive`.
3. Update `implementation_plan.md` AT THE NEW PATH (per CLAUDE.md "Do not edit a file and then git mv it" — order: `git mv` first, then edit at new path):
   - Header `**Status:**` → `Complete (PR #<A> merged 2026-05-25; PR B finalization in flight)`.
   - Execution tracker (§7): all 4 content stories + Epic 1 phase gate + PR A marked `[x]` with commit SHAs.
4. Update `pipeline_status.md` AT THE NEW PATH:
   - `## Implementation` section: `Not started` → `Complete` with PR A link, CI summary, cross-model review summary, Gemini adjudication note.
   - Add `## Done` section.
5. Update `state.md`: append recent-changes entry referencing PR A's number (using the Python in-place-edit pattern from PR #252 — `state.md` is too large for the Read tool).
6. `git add -A && git status -s` — expected: at least 4 files renamed (`idea.md`, `feature_spec.md`, `implementation_plan.md`, `pipeline_status.md`) + 1 file modified (`state.md`). Plus auto-regenerated dashboard files from pre-commit hook.
7. Commit: `docs: finalize chore_dashboard_regen_quoted_pr_false_positive after PR #<A>` (matching canonical pattern on recent main e.g., `2a24fae4 docs: finalize chore_e2e_seed_acme_idea_obsolete after PR #250 (#252)`).
8. Push and open PR B: `gh pr create --title "docs: finalize chore_dashboard_regen_quoted_pr_false_positive after PR #<A>" --body <standard finalization body>`.

**Definition of Done**

- `docs/00_overview/implemented_features/2026_05_25_chore_dashboard_regen_quoted_pr_false_positive/` exists on the finalize branch with all 4 files moved.
- `docs/02_product/planned_features/chore_dashboard_regen_quoted_pr_false_positive/` does NOT exist on the finalize branch.
- `state.md` recent-changes entry references PR A's number.
- PR B is open, CI green (it will be `secrets-defense` only since PR B is docs-only — `pr` workflow is paths-ignored for `docs/**`), and merge to main completes the chore.

---

## 3) Test workstream

| Test layer | Story | File | Status |
|---|---|---|---|
| Unit (backend) — new | 1.3 | `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` (TestBacktickStripPriority3, 7 methods) | Story 1.3 deliverable |
| Unit (backend) — regression guard | 1.2, 1.3 | Same file, existing 24+ tests | Per AC-9 expectation: all existing tests must still pass. Story 1.2 verifies `TestPriorityCascade::test_ac9_fuzzy_merged_in_spec_beats_idea` specifically. |
| Integration / Contract / E2E | — | — | N/A — script change, no DB/HTTP/UI surface |
| Doc-verification | — | — | N/A — code change, not doc-only |

No new test files (additive to the existing `test_dashboard_pr_extraction.py`). No orphaned tests. Coverage gate (80% Python per CLAUDE.md) is satisfied — `scripts/build_mvp1_dashboard.py` already has substantial test coverage; the new helper + wire-in are exercised by 7 new methods.

## 4) Documentation update workstream

| Doc | Scope | Story |
|---|---|---|
| `scripts/build_mvp1_dashboard.py` docstring (lines 582–608) | One sentence about backtick strip | 1.4 |
| `docs/02_product/planned_features/chore_dashboard_regen_quoted_pr_false_positive/implementation_plan.md` | Status flip + execution tracker | 2.1 (at NEW path post-mv) |
| `docs/02_product/planned_features/chore_dashboard_regen_quoted_pr_false_positive/pipeline_status.md` | Implementation section + Done section | 2.1 (at NEW path post-mv) |
| `state.md` | Recent-changes entry | 2.1 |
| Folder move | `planned_features/` → `implemented_features/` | 2.1 |

**Not chore-authored content (downstream-of-pre-commit):** The `mvp1-dashboard-regen` pre-commit hook automatically refreshes `docs/00_overview/MVP1_DASHBOARD.md` + `mvp1_dashboard.html` + `DASHBOARD.md` + `dashboard.html` on every commit touching feature folders. These auto-regenerated files appear in PR A's diff but are NOT chore-authored deliverables — per [`feature_spec.md` §3 Out of scope](feature_spec.md). No story calls `make dashboard` manually.

`architecture.md` and `CLAUDE.md` not updated — this chore introduces no new conventions, rules, services, layers, env vars, or build commands.

## 5) Plan consistency review

| Check | Method | Result |
|---|---|---|
| Every spec FR has a story | Spec §17: FR-1..FR-5. Plan §1: Stories 1.1, 1.2, 1.3, 1.4, 2.1 mapping to the same FRs. | ✓ Match |
| Every spec endpoint has a story | Spec §8: 0 endpoints | ✓ N/A |
| Every spec error code is tested | Spec §8.5: 0 error codes | ✓ N/A |
| Every modified file actually exists | `scripts/build_mvp1_dashboard.py` ✓; `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` ✓; `state.md` ✓ (all verified by ls/grep) | ✓ |
| Every story's DoD has a verification gate | All 5 stories have explicit grep / pytest / functional / state assertions in their DoD | ✓ |
| Test file count and assignment | 1 test file (existing, additive); assigned to Story 1.3 | ✓ |
| Phase gate arithmetic | Epic 1 gate references **7 commits** at end of Epic 1 (preflight + spec + plan + 4 story commits = 7); Epic 2 = 4 files renamed + 1 modified + auto-regen | Recounted: ✓ |
| Open questions resolved | Spec §19: 0 open questions; 7 decisions logged (D-1..D-7) | ✓ |
| Frontend UI Guidance | N/A — no story has frontend scope | ✓ skip |
| Audit-event coverage | N/A — pre-MVP2; spec §6 marks audit_log as N/A | ✓ skip |
| Enumerated value contracts | N/A — no `<select>` / filter / badge / sort surface | ✓ skip |
| Deferred phase tracking | Spec §3 explicitly notes "single phase, single PR" content + standard 2-PR finalization — not a deferred-capability boundary | ✓ no `phase2_idea.md` needed |

## 6) Sequencing and risk

- **Story ordering within Epic 1:** 1.1 → 1.2 → 1.3 → 1.4. The order matters because Story 1.2 imports the helper Story 1.1 created, and Story 1.3's tests import both. Story 1.4 is independent and could run anywhere in Epic 1.
- **Cross-story file overlap:** Stories 1.1, 1.2, 1.4 all edit `scripts/build_mvp1_dashboard.py` at disjoint locations (post-line-498 insertion, line-628 modification, lines 589–592 docstring edit). Sequential `Edit` calls with re-Read between each story is sufficient — no merge conflicts. Story 1.3 edits a different file (`test_dashboard_pr_extraction.py`).
- **PR-A → PR-B dependency:** Epic 2 cannot start until PR A merges to main (Epic 2's branch must be off post-A `main`).
- **Risk: parallel edits to target files.** Mitigated by Task 1/2 in each story re-Reading the target. If a parallel PR (e.g., another contributor) has touched the same line range, the `Edit` errors out and the chore escalates. `git log -1 -- scripts/build_mvp1_dashboard.py` should return commit `e100ced7` (2026-05-23) — that's the last commit touching the script before this chore.
- **Risk: pre-commit dashboard regen after each commit.** Expected behavior — the hook regenerates whenever feature folders change. Re-stage pattern (per the `chore_e2e_seed_acme_idea_obsolete` precedent established in PR #250) handles it.
- **Risk: mid-flight base drift from main.** If the user's `infra_study_preflight_real_engine_integration` work or another concurrent PR merges into main while Epic 1 is in flight, this chore's PR may need to be rebased onto current main (as PR #250 did). The rebase pattern is established: `git rebase -X ours origin/main` favors incoming main on auto-regenerated dashboards; manual conflict resolution on `scripts/build_mvp1_dashboard.py` would be needed only if the concurrent PR also touched lines 488–650 (low likelihood given the chore is the only in-flight work on this script).
- **Risk: smoke CI failure (pre-existing).** The `smoke (operator-path tutorial flow)` check has failed on every main push for the past 24 hours (captured in `bug_smoke_dashboard_demo_state_locator_missing`). This chore is not expected to affect smoke. Per PR #250 precedent, adjudicate as "pre-existing, not regressed by this chore" and proceed with merge.

## 7) Execution tracker

| Story | Status | Commit SHA |
|---|---|---|
| 1.1 — Add `_strip_backtick_quoted_segments` helper | [ ] | — |
| 1.2 — Wire helper into `_extract_pr_number` priority-3 | [ ] | — |
| 1.3 — Add `TestBacktickStripPriority3` class (7 methods) | [ ] | — |
| 1.4 — Insert docstring note about backtick strip | [ ] | — |
| Epic 1 phase gate | [ ] | — |
| **PR A** | [ ] | — |
| 2.1 — git mv + state.md update | [ ] | — |
| **PR B** | [ ] | — |

## 8) Open questions

None. All decisions locked in [`feature_spec.md` §19](feature_spec.md) D-1 through D-7.
