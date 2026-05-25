# Feature Specification — chore_dashboard_regen_quoted_pr_false_positive

**Date:** 2026-05-25
**Status:** Approved
**Owners:** Eric Starr (eng); soundminds.ai (product)
**Related docs:**
- [`idea.md`](idea.md)
- Target file: [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) (current `_extract_pr_number` at line 581; existing strip helper `_strip_dependency_table_rows` at line 488)
- Existing test surface: [`backend/tests/unit/scripts/test_dashboard_pr_extraction.py`](../../../../backend/tests/unit/scripts/test_dashboard_pr_extraction.py) (`chore_dashboard_pr_extraction_from_idea` PR #221 — adds the strict-idea-body patterns 3.5/3.6 that this chore composes with)
- Sibling shipped work: [`bug_dashboard_depends_on_column_bloat`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/) (PR #208) + [`chore_dashboard_pr_extraction_from_idea`](../../../00_overview/implemented_features/2026_05_23_chore_dashboard_pr_extraction_from_idea/) (PR #221)
- **Depends on:** none (single-PR, single-file behavioral fix in dev infrastructure)

---

## 1) Purpose

- **Problem:** [`_extract_pr_number`](../../../../scripts/build_mvp1_dashboard.py#L581)'s priority-3 fuzzy regexes at lines 629/632 of `scripts/build_mvp1_dashboard.py` (`PR[^a-zA-Z\n]{0,5}#(\d+)[^.\n]{0,80}merged` and `merged[^.\n]{0,80}PR[^a-zA-Z\n]{0,5}#(\d+)`) match narrative-quoted PR-merge phrases inside backtick-fenced inline code AND triple-backtick code blocks within spec/plan/idea body content. When a planned-feature spec quotes another feature's PR-merge phrase for didactic clarity (e.g., `` `**Depends on:** [infra_foundation] — merged via PR #4 (2026-05-09)` ``), the fuzzy match returns `4` as THIS feature's PR number. The rendered `MVP1_DASHBOARD.md` Plan/Spec/Idea row shows the wrong PR# until the feature actually merges and `_load_implemented` takes over with the authoritative pipeline-status data.
- **Outcome:** Priority-3 fuzzy match no longer matches PR-merge phrases that live inside backtick-fenced segments. The existing strip helper [`_strip_dependency_table_rows`](../../../../scripts/build_mvp1_dashboard.py#L488) gets a sibling `_strip_backtick_quoted_segments(text)` that runs BEFORE the dependency-table strip in the priority-3 path at line 628. Backtick-quoted PR-merge phrases (the most common false-positive shape, per the idea's "Concrete impact" section) stop triggering wrong-PR# extractions. Existing own-PR fuzzy matches (priority-3's intended use case — narrative `## Status` body assertions that legitimately describe the feature's own ship event) continue to work because they live in prose, not backticks.
- **Non-goal:** Option B (tightening the fuzzy regex itself) or Option C (opt-in `merged-context-fuzzy-match: true` marker) per [`idea.md`](idea.md) §"Proposed capabilities" Recommendation. Both are deferred: Option C carries backfill cost; Option B risks breaking legitimate fuzzy-match extractions. If Option A leaves residual false positives in the wild after this lands, a follow-up `chore_dashboard_regen_pr_extraction_opt_in_marker` can pick up Option C.

## 2) Current state audit

### Existing implementations

- [`scripts/build_mvp1_dashboard.py:581-657`](../../../../scripts/build_mvp1_dashboard.py#L581) — `_extract_pr_number(pipe, plan, spec, idea="") -> int | None`. Six-priority cascade: (1) pipeline_status `## Implement` section, (2) plan `**Status:**` header, (3) fuzzy merged-context across `pipe + "\n" + plan + "\n" + spec` (the regression target), (3.5) strict line-anchored idea-body patterns (Pattern A/B/C — added by `chore_dashboard_pr_extraction_from_idea` PR #221), (3.6) `**PR:**` frontmatter in the metadata block, (4) last-resort `#N` fallback. Priority 3 runs at lines 628–634: it calls `_strip_dependency_table_rows(pipe + "\n" + plan + "\n" + spec)`, then runs the two fuzzy regexes against the stripped string.
- [`scripts/build_mvp1_dashboard.py:488-498`](../../../../scripts/build_mvp1_dashboard.py#L488) — `_strip_dependency_table_rows(text: str) -> str`. Existing strip helper. Removes markdown-table rows containing `Implemented` / `Depends on` / `Depended` keywords so dependency-cite PR# numbers don't leak into the fuzzy match. Doesn't touch narrative paragraphs, bullet lists, or backtick-fenced inline examples — which is the gap this chore fills.
- [`backend/tests/unit/scripts/test_dashboard_pr_extraction.py`](../../../../backend/tests/unit/scripts/test_dashboard_pr_extraction.py) — 312-line test file (14.7K). Five test classes cover the strict-pattern paths (TestStrictPatternExtraction, TestFalsePositiveRejection, TestFrontmatterFallback, TestPriorityCascade, TestBackwardCompat). **No test class exercises priority-3's backtick-stripped behavior** — that's the gap this chore fills with new tests.
- [`scripts/build_mvp1_dashboard.py:_load_planned`](../../../../scripts/build_mvp1_dashboard.py#L698) — caller. Reads each planned feature's `pipe`/`plan`/`spec`/`idea` strings from disk, passes them to `_extract_pr_number`. The returned PR# is what populates the Plan/Spec/Idea-table `Status` column when no `_load_implemented` row exists for the feature yet.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| N/A | dev-infra script; no URL refs change | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` | Existing tests against `_extract_pr_number` | 24+ test methods | None — additive only. New test class added (TestBacktickStripPriority3 or sibling file). |
| `backend/tests/unit/scripts/test_dashboard_priority_sort.py` | Tests the `_md_sort_key` / `_priority_order` algorithms (locks tie-breaker order) | N | None — orthogonal subsystem. |

### Existing behaviors affected by scope change

- **Fuzzy-match priority-3 on backtick-quoted PR-merge phrases:** Current: matches and returns the quoted PR number (false positive). New: stripped before regex runs; returns `None` for that input. Decision needed: **no** — pure correctness fix; the previous behavior was a bug.
- **Fuzzy-match priority-3 on non-backticked own-PR assertions (e.g., `## Status\n\nThis feature merged 2026-05-15 as PR #200`):** Current: matches and returns 200 (intended behavior). New: unchanged. The backtick strip removes ONLY backtick-fenced segments; un-backticked prose is preserved. Decision needed: **no** — preserves intended behavior.
- **Priority cascade (1 → 2 → 3 → 3.5 → 3.6 → 4):** Current order preserved. The backtick strip runs only inside priority 3; priorities 1, 2, 3.5, 3.6, and 4 are untouched. Decision needed: **no** — minimal-blast-radius change.

---

## 3) Scope

### In scope

- A. **Add `_strip_backtick_quoted_segments(text: str) -> str`** in `scripts/build_mvp1_dashboard.py`, placed adjacent to the existing `_strip_dependency_table_rows` helper at line 488. The function removes (a) triple-backtick code blocks (` ```...``` `) including any leading language identifier and embedded newlines, AND (b) inline backtick spans (`` `...` ``) — both flavors are common false-positive shapes per [`idea.md`](idea.md) §"Concrete impact". Replacement is the empty string (the priority-3 regex only cares about whether the `PR #N`/`merged` tokens are present; positional information is irrelevant once segments are scrubbed).
- B. **Wire the new helper into priority 3** at line 628 of `_extract_pr_number`, between the existing `pipe + "\n" + plan + "\n" + spec` join and the existing `_strip_dependency_table_rows` call. Order: backtick-strip first (removes the densest false-positive source), then dependency-table-row strip. Net behavior: backtick-quoted PR# never reaches the fuzzy regex.
- C. **Add new test class `TestBacktickStripPriority3`** in `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` covering 7 specific scenarios (per §12 ACs). The tests assert priority-3 returns `None` for backtick-quoted false-positive inputs (inline, multi-line fenced, single-line fenced) AND still returns the correct PR# for legitimate un-backticked own-PR prose. Total new test methods: 7 (one per AC, AC-6 through AC-12).

### Out of scope

- Option B (tightening the fuzzy regex). Per [`idea.md`](idea.md) Recommendation, deferred unless Option A proves insufficient.
- Option C (opt-in `merged-context-fuzzy-match: true` marker). Per [`idea.md`](idea.md) Recommendation, deferred. If implemented later, would need a separate spec/PR cycle.
- Modifying priorities 1, 2, 3.5, 3.6, or 4 in any way. The bug is scoped to priority 3.
- Refactoring `_strip_dependency_table_rows` or its callers. The chore composes with it, doesn't change it.
- Touching `_load_planned`, `_load_implemented`, or any downstream rendering code.
- Backfilling any historical dashboard renders. The chore's effect manifests on the next `make dashboard` regen (which runs on every commit touching feature folders via pre-commit hook); no manual backfill needed.
- Refactoring the priority cascade docstring at lines 582-608 beyond a brief one-line addition noting the backtick strip.

### API convention check

N/A — dev-infrastructure script change; no API endpoints added or modified.

### Phase boundaries (if multi-phase)

Single phase, single PR. The chore is one helper + one wire-in + 7 test methods. The standard two-PR finalization pattern still applies (PR A = content, PR B = `git mv` to `implemented_features/`) per [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 7, matching the canonical shape on recent main (e.g., [`PR #251 docs: finalize infra_agent_sibling_worktree_isolation after PR #249`](https://github.com/SoundMindsAI/relyloop/pull/251)). Not a deferred-capability phase boundary.

---

## 4) Product principles and constraints

- **Minimal blast radius.** The fix touches one helper insertion (new function) and one line wire-in (line 628). It does not change any other priority in the cascade, does not refactor any caller, does not touch any downstream rendering.
- **Composition over modification.** Add a new helper rather than fold backtick-stripping into `_strip_dependency_table_rows`. Keeps each helper's responsibility narrow and testable in isolation.
- **Preserve legitimate fuzzy-match extractions.** Un-backticked prose like `## Status\n\nThis feature merged 2026-05-15 as PR #200` must continue to match priority 3. The strip is positively-scoped to backtick segments only.
- **Conventional Commits** (CLAUDE.md absolute rule 7). Commit subject prefix is `fix(dashboard):` since this corrects a bug in `_extract_pr_number`'s behavior. Story commits use `fix(dashboard):`; finalization commit uses `docs:` per the recent main pattern.
- **No `--no-verify`.** The pre-commit hook (`mvp1-dashboard-regen`) WILL fire on this branch because the planned-features folder is touched (this chore's own scaffolding); the regenerated dashboard files are downstream-of-pre-commit per the same convention `chore_e2e_seed_acme_idea_obsolete` established (PR #250 D-3).

### Anti-patterns

- **Do not** modify `_strip_dependency_table_rows` to also strip backticks. Composing two narrow helpers is more testable than one wide helper, and the dependency-table-row helper has a different keyword-based scope (`Implemented` / `Depends on` / `Depended`) that shouldn't entangle with markdown formatting.
- **Do not** apply the backtick strip outside priority 3. Priorities 3.5 and 3.6 use line-anchored regex / metadata-block-bounded matches that already reject backtick-quoted false positives; stripping there would be a no-op overhead. Priorities 1 and 2 read structured sections (`## Implement` body and `**Status:**` line); stripping there could remove information the regex needs.
- **Do not** use a regex that captures and re-inserts the backtick content. Plain removal is sufficient — the priority-3 fuzzy regex doesn't care about position or surrounding context, only token presence.
- **Do not** add a CLI flag, config knob, or env var to disable the strip. The fix is a pure behavioral correction; gating it is unnecessary.

## 5) Assumptions and dependencies

- **No in-flight PR is editing `scripts/build_mvp1_dashboard.py`.** Status: verified (2026-05-25). The most recent commit touching the script is `e100ced7 docs: finalize chore_dashboard_pr_extraction_from_idea post-PR-221 merge` (2026-05-23). Risk if violated: rebase conflicts on `_extract_pr_number` or `_strip_dependency_table_rows`. Mitigation: re-check `git log -1 -- scripts/build_mvp1_dashboard.py` immediately before push.
- **No in-flight PR is editing `backend/tests/unit/scripts/test_dashboard_pr_extraction.py`.** Status: verified (2026-05-25). Risk if violated: test-class merge conflict. Mitigation: same as above.
- **The `_extract_pr_number` priority cascade docstring at lines 582-608 remains the source of truth for the priority order.** Status: verified by Read of lines 575-654 (Pass 1). The chore adds a one-line note about the backtick strip but does not restructure the cascade.

## 6) Actors and roles

- **Primary actor:** Internal contributor (any human or agent who runs `make dashboard`, opens a PR, or pushes a commit that triggers the `mvp1-dashboard-regen` pre-commit hook).
- **Role model:** N/A — single-tenant install, no auth surface. RelyLoop is single-tenant + no auth through MVP3 per [`docs/01_architecture/data-model.md`](../../../../docs/01_architecture/data-model.md).
- **Permission boundaries:** N/A. The dashboard regen script runs locally; output files (`MVP1_DASHBOARD.md`, `mvp1_dashboard.html`, `DASHBOARD.md`, `dashboard.html`) are committed alongside whatever feature change triggered the regen.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2; this chore is MVP1-era dev-infra and touches no state-mutating code paths.

---

## 7) Functional requirements

### FR-1: Add `_strip_backtick_quoted_segments` helper

- Requirement:
  - The system **MUST** add a new function `_strip_backtick_quoted_segments(text: str) -> str` to `scripts/build_mvp1_dashboard.py`, placed immediately after `_strip_dependency_table_rows` (the function ending at approximately line 498).
  - The function **MUST** remove all triple-backtick code blocks. A triple-backtick block is delimited by three or more backticks at the start and another three or more backticks at the end. Three flavors **MUST** all be handled: (a) **multi-line fenced blocks** — ` ``` ` (optionally followed by a language identifier like `python`) on one line, body on intervening lines, closing ` ``` ` on its own line; (b) **single-line triple-backtick fences** — ` ```PR #N merged 2026-05-01``` ` all on one line; (c) **empty fences** — ` ``` ` immediately followed by ` ``` ` with no body. A robust two-pass approach (one greedy regex for the multi-line flavor with `re.DOTALL`, then a non-greedy single-line pass) is acceptable, OR a single regex like `r"```.*?```"` with `re.DOTALL` that handles all three flavors. AC-12 locks the single-line case.
  - The function **MUST** remove all inline backtick spans (a single `` ` ``-character followed by any content not containing a newline or another single backtick, terminated by another single `` ` ``). Suggested regex: `r"`[^`\n]*`"` (note the `*` — must match empty inline spans `` `` `` per AC-11, not just one-or-more content).
  - The function **MUST** apply triple-backtick removal BEFORE inline-backtick removal so the inner ` ``` ` characters don't accidentally match the inline-backtick regex.
  - Replacement for both flavors **MUST** be the empty string (not a single space, not a placeholder) — the priority-3 fuzzy regex only cares about token presence.
  - The function **MUST** be a pure function (no I/O, no global state mutation) — same shape as `_strip_dependency_table_rows`.
- Notes: Helper lives next to its sibling for discoverability. Both helpers compose in the priority-3 path; either could in principle be reused by future priority-N additions, but the chore does NOT speculatively wire them into other priorities (Anti-pattern §4 bullet 2).

### FR-2: Wire the new helper into priority-3 of `_extract_pr_number`

- Requirement:
  - The system **MUST** modify `_extract_pr_number` at line 628 of `scripts/build_mvp1_dashboard.py` (the existing assignment `combined = _strip_dependency_table_rows(pipe + "\n" + plan + "\n" + spec)`) to first run `_strip_backtick_quoted_segments` on the joined text, THEN run `_strip_dependency_table_rows`. The new line shape (representative — equivalent factorings are acceptable):
    ```python
    combined = _strip_dependency_table_rows(
        _strip_backtick_quoted_segments(pipe + "\n" + plan + "\n" + spec)
    )
    ```
  - The system **MUST NOT** change any other line of `_extract_pr_number` other than this one assignment AND a one-line addition to the docstring (e.g., adding `Backtick-fenced and inline-backtick segments are stripped first so` to the priority-3 description in the docstring at lines 589–592).
  - The system **MUST NOT** modify priorities 1, 2, 3.5, 3.6, or 4 in any way.
- Notes: The order matters — backtick-strip first reduces the input that `_strip_dependency_table_rows` then operates on. The dependency-table-row strip is keyword-based on markdown table rows, so it's unaffected by whether content is backtick-fenced. But applying backtick-strip first is the safer order in case a future markdown table row contains backtick-quoted content that should still be considered for dependency-row classification.

### FR-3: Add `TestBacktickStripPriority3` test class with 7 test methods

- Requirement:
  - The system **MUST** add a new test class `TestBacktickStripPriority3` to `backend/tests/unit/scripts/test_dashboard_pr_extraction.py`, placed after the existing `TestBackwardCompat` class.
  - The class **MUST** contain exactly the following 7 test methods, named per §12 AC IDs (one per AC):
    - `test_ac6_inline_backtick_quoted_merged_pr_returns_none`
    - `test_ac7_multiline_triple_backtick_block_with_merged_pr_returns_none`
    - `test_ac8_inline_backtick_with_pr_first_then_merged_returns_none`
    - `test_ac9_unbacktickend_prose_own_pr_still_matches`
    - `test_ac10_backtick_strip_runs_before_dependency_table_strip`
    - `test_ac11_empty_backtick_segment_does_not_crash`
    - `test_ac12_single_line_triple_backtick_fence_returns_none`
  - Each test **MUST** be a method of the class taking only `self` (matches existing style — no `pytest.fixture` parameters needed).
  - The tests **MUST** import `_extract_pr_number` and (where AC-10 requires it) `_strip_backtick_quoted_segments` from `scripts.build_mvp1_dashboard` — matching the existing import block at the top of the test file.
- Notes: The 7 tests cover (a) inline-backtick false-positive rejection in both regex orderings (AC-6, AC-8), (b) multi-line triple-backtick block false-positive rejection (AC-7), (c) preservation of legitimate un-backticked own-PR matches (AC-9), (d) helper-composition order verification (AC-10), (e) edge case for empty backtick segments (AC-11), (f) single-line triple-backtick fence rejection (AC-12).

### FR-4: Update the priority cascade docstring

- Requirement:
  - The system **MUST** insert at most one sentence in the `_extract_pr_number` docstring (currently lines 582-608) noting that priority 3 strips backtick-fenced segments before fuzzy matching, AND citing the new helper function name. Representative wording: `Backtick-fenced (triple + inline) segments are stripped first via _strip_backtick_quoted_segments so quoted PR-merge phrases in spec narrative don't leak through.` Placement: at the end of the priority-3 description (currently lines 589-592), as a continuation of the existing dependency-table-rows sentence.
  - The system **MUST NOT** restructure the docstring's priority cascade enumeration or any other description.
- Notes: Documenting the strip in the docstring is the source-of-truth pattern the existing dependency-table-rows note follows (line 590: "Dependency-table rows are stripped first…").

## 8) API and data contract baseline

N/A — dev-infrastructure script change; no API surface, no data contract.

### 7.1–7.5

All subsections N/A. No endpoints, no error envelopes, no enumerated values, no error codes.

## 9) Data model and state transitions

N/A — dev-infrastructure script change; no schema changes, no new entities, no state transitions.

## 10) Security, privacy, and compliance

- **Threats:** None — script change in dev infra; no PII, no credentials, no network calls, no user input parsing.
- **Controls:** N/A.
- **Secrets/key handling:** N/A.
- **Auditability:** Standard `git log` for the chore PR is sufficient.
- **Data retention/deletion/export impact:** N/A.

## 11) UX flows and edge cases

N/A — no UI changes. Dev-infra script behavioral fix.

## 12) Given/When/Then acceptance criteria

### AC-6: Inline-backtick-quoted merged-PR phrase (`merged ... PR #N` order) returns None

- Given a `spec` string containing an inline-backtick segment with a quoted merged-PR phrase, e.g., `` `**Depends on:** [infra_foundation] — merged via PR #4 (2026-05-09)` ``, AND no other PR#-bearing content in `pipe`/`plan`/`idea`.
- When `_extract_pr_number(pipe="", plan="", spec=<above>, idea="")` is called.
- Then the return value **MUST** be `None` (the priority-3 fuzzy regex does not match the stripped input; no other priority fires).
  - Example values:
    - Input: `spec = "Some prose.\n\nExample: ` + chr(96) + `**Depends on:** [infra_foundation] — merged via PR #4 (2026-05-09)` + chr(96) + `\n\nMore prose."`
    - Expected: `_extract_pr_number("", "", spec, "") == None`

### AC-7: Multi-line triple-backtick code block with merged-PR phrase returns None

- Given a `spec` string containing a multi-line triple-backtick code block whose body contains a merged-PR phrase.
- When `_extract_pr_number(pipe="", plan="", spec=<above>, idea="")` is called.
- Then the return value **MUST** be `None`.
  - Example values:
    - Input: ``spec = "Header.\n\n```python\n# Example: see PR #99 (merged 2026-05-15)\n```\n\nFooter."``
    - Expected: `_extract_pr_number("", "", spec, "") == None`

### AC-8: Inline-backtick-quoted `PR #N ... merged` (other regex order) returns None

- Given a `spec` string containing an inline-backtick segment with a quoted `PR #N ... merged` phrase (the FIRST priority-3 regex order, complementing AC-6 which tests the second).
- When `_extract_pr_number("", "", spec, "")` is called.
- Then the return value **MUST** be `None`.
  - Example values:
    - Input: `spec = "Note: ` + chr(96) + `PR #42 was merged on 2026-05-01` + chr(96) + ` for context."`
    - Expected: `_extract_pr_number("", "", spec, "") == None`

### AC-9: Un-backticked own-PR prose still matches priority-3

- Given a `spec` string containing a legitimate own-PR assertion in prose (NOT inside any backtick segment), e.g., `## Status\n\nThis feature merged 2026-05-15 as PR #200 (squash).`
- When `_extract_pr_number("", "", spec, "")` is called.
- Then the return value **MUST** be `200` (the priority-3 fuzzy regex still matches un-backticked prose).
  - Example values:
    - Input: `spec = "## Status\n\nThis feature merged 2026-05-15 as PR #200 (squash)."`
    - Expected: `_extract_pr_number("", "", spec, "") == 200`

### AC-10: `_strip_backtick_quoted_segments` runs before `_strip_dependency_table_rows`

- Given a multi-line input containing BOTH a backtick-fenced PR# AND a dependency-table-row PR#.
- When `_strip_backtick_quoted_segments` is called directly on the input.
- Then the returned string **MUST NOT** contain the backtick-fenced content, AND **MUST** still contain the dependency-table-row content unchanged (proving the new helper does not encroach on the dependency-row helper's scope).
  - Example values:
    - Input: ``text = "| foo | Implemented (PR #1) |\n\n`Example: merged via PR #99`\n\nMore."``
    - Expected substring present: `"| foo | Implemented (PR #1) |"`
    - Expected substring absent: `"PR #99"`

### AC-11: Empty backtick segment does not crash

- Given an input containing an empty inline-backtick segment (`` `` ``) and/or an empty triple-backtick block (` ``` ` followed immediately by ` ``` `).
- When `_strip_backtick_quoted_segments` is called on the input.
- Then the function **MUST** return a string (no `IndexError`, `TypeError`, or regex `error`), with the empty segments removed (substituted with empty string).
  - Example values:
    - Input: ``text = "before `` after\n```\n```\nfinal"``
    - Expected: the call returns a string; runtime does not raise.

### AC-12: Single-line triple-backtick fence with merged-PR phrase returns None

- Given a `spec` string containing a SINGLE-line triple-backtick fence (no embedded newline between the opening and closing fences) whose body contains a merged-PR phrase. This is a distinct shape from AC-7's multi-line case — handlers that only match `` ``` ... \n ... \n ``` `` will silently miss this.
- When `_extract_pr_number("", "", spec, "")` is called.
- Then the return value **MUST** be `None`.
  - Example values:
    - Input: ``spec = "Inline example: ```PR #77 merged 2026-05-03``` for context."``
    - Expected: `_extract_pr_number("", "", spec, "") == None`

## 13) Non-functional requirements

- **Performance:** Negligible. The strip operates on planned-feature spec/plan/idea text (typically <100KB per feature; total across all features <5MB). Regex execution is microseconds per feature. Total dashboard regen runtime impact: <100ms across the full corpus.
- **Reliability:** N/A.
- **Operability:** The fix manifests on the next `make dashboard` regen, which fires automatically via the `mvp1-dashboard-regen` pre-commit hook on every commit that touches a planned-features folder. No operator action required.
- **Accessibility/usability:** N/A.

## 14) Test strategy requirements (spec-level)

- **Unit tests:** 7 new test methods in `TestBacktickStripPriority3` class within `backend/tests/unit/scripts/test_dashboard_pr_extraction.py`, mapping 1-to-1 to ACs 6–12.
- **Integration tests:** None — script change, no DB/HTTP boundary.
- **Contract tests:** None — no API surface.
- **E2E tests:** None — dev infra.
- **Regression guard:** The 24+ existing test methods in `test_dashboard_pr_extraction.py` MUST all continue to pass (the existing `TestPriorityCascade` AC-9 test method, which exercises the fuzzy match's correct extraction from un-backticked prose, is the canary that the chore's change doesn't break legitimate matches).

Per CLAUDE.md "test completeness rule": the script change touches the Python dev-infra layer only. Unit tests are the sole appropriate layer; the new 7 tests + 24 regression-guard tests deliver complete coverage.

## 15) Documentation update requirements

- `docs/01_architecture/`: no updates required.
- `docs/02_product/`: this chore's folder ships under `docs/02_product/planned_features/` for PR A, then moves to `docs/00_overview/implemented_features/2026_05_25_chore_dashboard_regen_quoted_pr_false_positive/` (or whatever date the finalization PR lands on) for PR B.
- `docs/03_runbooks/`: no updates required.
- `docs/04_security/`: no updates required.
- `docs/05_quality/`: no updates required — the existing test layer convention is followed (unit tests in `backend/tests/unit/scripts/`).
- `state.md`: not updated by this chore's content commits. `state.md` updates are handled by the standard post-merge finalization step in [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 7 (PR B), matching the convention established by [`chore_e2e_seed_acme_idea_obsolete` PR #252](https://github.com/SoundMindsAI/relyloop/pull/252).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** N/A — script change ships across two PRs (PR A = content + tests; PR B = finalization folder move).
- **Migration/backfill expectations:** N/A — no schema changes, no historical-dashboard backfill needed.
- **Operational readiness gates:** standard CI gate (`.github/workflows/pr.yml` — backend lint + format + mypy + pytest with 80% coverage gate; frontend lint + typecheck + tests + build; docker buildx). The chore touches `scripts/build_mvp1_dashboard.py` (under repo root, NOT under `docs/**` or `*.md`) so the full `pr` workflow WILL fire (unlike doc-only chores that hit only `secrets-defense`).
- **Release gate (PR A):** green CI on all jobs; Gemini Code Assist review adjudicated per CLAUDE.md "Cross-model review policy"; merge to main triggers PR B preparation.
- **Release gate (PR B):** green CI (will be `secrets-defense` only since PR B is docs-only); merge to main completes the chore.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-10, AC-11, AC-12 | Story 1.1 — Add `_strip_backtick_quoted_segments` helper (handles all 3 fence flavors: multi-line, single-line, empty) | `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` (TestBacktickStripPriority3 — AC-10, AC-11, AC-12 tests) | `scripts/build_mvp1_dashboard.py` (new helper) |
| FR-2 | AC-6, AC-7, AC-8, AC-9 | Story 1.2 — Wire helper into priority-3 of `_extract_pr_number` | Same test file (AC-6, AC-7, AC-8, AC-9 tests) | `scripts/build_mvp1_dashboard.py` (line 628 modification) |
| FR-3 | AC-6 through AC-12 | Story 1.3 — Add 7-method `TestBacktickStripPriority3` class | `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` (the new class itself is the deliverable) | none |
| FR-4 | (none direct; docstring is descriptive) | Story 1.4 — Insert one-sentence docstring note about backtick strip | none (docstring change; no test) | `scripts/build_mvp1_dashboard.py` (docstring lines 589-592) |
| FR-5 (post-merge) | — | Epic 2 / Story 2.1 — Post-merge `git mv` folder to `implemented_features/` + `state.md` update | n/a (post-merge) | `state.md` |

## 18) Definition of feature done

This feature is complete when:

- [ ] AC-6 through AC-12 all pass via the new `TestBacktickStripPriority3` class.
- [ ] All 24+ existing tests in `test_dashboard_pr_extraction.py` still pass (regression guard).
- [ ] `make lint && make typecheck && make test-unit` all green.
- [ ] PR A CI is green on all jobs (backend full suite + frontend + docker buildx).
- [ ] Gemini Code Assist review adjudicated per the four-quadrant rubric.
- [ ] PR A merged to `main`.
- [ ] PR B (finalization folder move) opened, CI green, merged to `main`.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all decisions locked at idea-stage Recommendation (Option A) and re-confirmed during /idea-preflight (2026-05-25).

### Decision log

- **D-1 (2026-05-25):** Option A (backtick-scope strip) is the chosen implementation. Rationale: per [`idea.md`](idea.md) Recommendation, Option A is the lowest-friction fix that captures the most common false-positive shape. Options B (regex tightening) and C (opt-in marker) deferred — B risks breaking legitimate own-PR fuzzy matches; C requires backfilling a marker on legacy features. If A leaves residual false positives in the wild, a follow-up `chore_dashboard_regen_pr_extraction_opt_in_marker` can pick up Option C.
- **D-2 (2026-05-25):** Strip order is backtick-first, then dependency-table-row. Rationale: backtick stripping removes the densest false-positive source AND reduces the input that the dependency-table-row strip then processes. Other order works (helpers are commutative on the false-positive shapes named in the idea) but this order minimizes the dependency-table helper's input.
- **D-3 (2026-05-25):** No CLI flag, config knob, or env var to disable the strip. Rationale: pure correctness fix; no legitimate use case for the broken behavior. Avoids adding configuration surface for a bug.
- **D-4 (2026-05-25):** `_strip_backtick_quoted_segments` is a separate helper, NOT folded into `_strip_dependency_table_rows`. Rationale: composition over modification — each helper's responsibility stays narrow and testable in isolation. Dependency-table-row strip is keyword-based on table-row text; backtick strip is markdown-syntax-based on inline/fenced segments. Different scopes.
- **D-5 (2026-05-25):** No manual `make dashboard` invocation in any story. Rationale: same pattern as `chore_e2e_seed_acme_idea_obsolete` D-3 (PR #250) — the dashboard regen is pre-commit-hook-driven; manual `make dashboard` would create unrelated churn. Auto-regenerated dashboards in PR A land as downstream-of-pre-commit.
- **D-6 (2026-05-25):** Two-PR rollout (PR A = content + tests; PR B = finalization folder move) matches the canonical RelyLoop pattern (e.g., recent main `2a24fae4 docs: finalize chore_e2e_seed_acme_idea_obsolete after PR #250 (#252)`). Not a deferred-capability phase boundary — single phase.
- **D-7 (2026-05-25):** AC-12 added to lock the single-line triple-backtick fence shape (` ```PR #N merged YYYY-MM-DD``` ` all on one line, no embedded newlines). Rationale: GPT-5.5 cross-model review cycle 1 (Pass B Low finding) caught that AC-7 only exercised the multi-line shape; a regex like `r"```[^\n]*\n.*?\n```"` would pass AC-7 + AC-11 but silently fail the single-line case. FR-1 was clarified to enumerate all three fence flavors (multi-line, single-line, empty); test count rose 6 → 7.
