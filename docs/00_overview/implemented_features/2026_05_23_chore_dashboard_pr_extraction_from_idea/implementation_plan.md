# Implementation Plan — `_extract_pr_number` reads `idea.md` for legacy idea-only features

**Date:** 2026-05-23
**Status:** Complete (PR #221 squash-merged as `8a6452d5` on 2026-05-23)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) (Conventional Commits, 80% coverage gate, no main commits).

---

## 0) Planning principles

- **Spec traceability first** — every story maps to one or more FR IDs from `feature_spec.md`; every AC has at least one test.
- **Single phase, single PR** — the chore is ~40 LOC across one script + one new test file.
- **No new test infrastructure** — `backend/tests/unit/scripts/` already exists with `_dashboard_*` test files; the new file follows the established pattern.
- **Line-anchoring is the load-bearing safeguard** — per spec FR-5 + AC-14, the strict patterns' `^…` anchors prevent false positives from dependency cites; the implementation must preserve this property and the tests must lock it.
- **No backfill of legacy folders** — per spec §3 Out of scope, this chore ships extraction logic only. The `**PR:**` frontmatter convention is documented; existing legacy ideas are NOT edited.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Notes |
|---|---|---|
| FR-1 (signature change: `_extract_pr_number(pipe, plan, spec, idea="")`) | Epic 1 / Story 1.1 | Default arg preserves backward-compat. |
| FR-2 (three line-anchored strict patterns A/B/C at priority 3.5) | Epic 1 / Story 1.1 | Each pattern's `\b` boundary lives immediately after the digit capture per spec cycle-2 fix. |
| FR-3 (bounded `**PR:**` frontmatter at priority 3.6) | Epic 1 / Story 1.1 | Bounded metadata-block algorithm (contiguous metadata-key lines + 30-line cap). |
| FR-4 (`_load_implemented` + `_load_planned` read `idea.md` and thread it) | Epic 1 / Story 1.2 | Both call sites updated symmetrically. |
| FR-5 (line-anchoring is the safeguard; no stripping for idea) | Epic 1 / Story 1.1 + 1.2 | No additional code path — the line-anchor in FR-2/3 patterns IS the safeguard. AC-4 + AC-13 + AC-14 + AC-17 are the regression locks. |

No deferred phases — the spec defines a single phase (spec §3 "Phase boundaries: single phase, single PR").

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** One epic, two stories.

### Story-level detail requirements

Both stories are script-and-test changes — no API surface, no migrations, no UI, no Pydantic schemas. Stories include New/Modified files + Tasks + DoD; Endpoints/Schemas sections are omitted per the template rule for "purely refactor or test-only" stories.

### Conventions (applies to every story)

- All Python additions are typed (`mypy --strict` clean). New function signatures include explicit return annotations.
- Regex patterns are defined as module-level constants (`_IDEA_STATUS_SHIPPED_RE`, `_IDEA_STATUS_IMPLEMENTED_RE`, `_IDEA_SHIPPED_DATELINE_RE`, `_IDEA_PR_FRONTMATTER_RE`) so the test file can import them for direct verification AND the production code path reuses them. Modules constants are `re.compile`'d once at import time.
- Helper functions are named with leading underscore (private). Existing module conventions: `_read`, `_strip_dependency_table_rows`, `_split_prefix`, `_extract_pr_number`, etc.
- New helper `_extract_metadata_block(idea: str) -> str` implements the bounded-metadata-block algorithm from spec FR-3.

### AI Agent Execution Protocol (applies to every story)

Per template Step 0–9, narrowed for the chore's scope (no backend services, no frontend, no migrations):

0. Read [`architecture.md`](../../../../architecture.md) §"Where the code lives" and [`state.md`](../../../../state.md) (confirm Alembic head, recent dashboard-related chores).
1. Read story scope, FRs, ACs from the spec.
2. **Script-only:** modify `scripts/build_mvp1_dashboard.py`. No backend services, no models, no migrations, no routers, no schemas.
3. Run `make test-unit` (must remain green — chore must not regress unrelated tests, AND the new test file must pass).
4. Skip frontend (no UI scope).
5. Skip E2E (no UI scope).
6. Update `architecture.md` per FR-3's "documented in architecture.md" requirement — Story 1.2's DoD covers this.
7. Skip migration round-trip (no schema change).
8. PR description must include the empirical-verification structural-comparison transcript (per spec §14 step 3) — forward gain (5–8 new PR# resolutions) + no regression (zero PR# rewrites).
9. At finalization (separate PR after merge): update `state.md` recent-changes section + move folder to `implemented_features/2026_05_23_chore_dashboard_pr_extraction_from_idea/`.

---

## Epic 1 — `_extract_pr_number` reads `idea.md`

### Story 1.1 — Strict-pattern + frontmatter extraction in `_extract_pr_number`

**Outcome:** `_extract_pr_number(pipe, plan, spec, idea="")` accepts a fourth `idea: str` argument with a default of `""`. The function inserts priorities 3.5 (three line-anchored strict patterns) and 3.6 (bounded `**PR:**` frontmatter) into the cascade between current priority 3 (fuzzy `merged`-context) and current priority 4 (last-resort `#N`). All function-level ACs (AC-1 through AC-11 + AC-13 through AC-17) pass against the new logic when invoked directly with idea content. **AC-12 is owned by Story 1.2** — it requires the `_load_implemented` call-site update that threads idea content into the function from a real on-disk folder.

**FR coverage:** FR-1, FR-2, FR-3, FR-5. AC coverage: AC-1 through AC-11 (cascade behavior + Pattern A/B/C extraction + frontmatter fallback + false-positive rejection + backward-compat) + AC-13, AC-14, AC-15, AC-16, AC-17 (false-positive and edge-case locks). **AC-12 is owned by Story 1.2** (end-to-end loader test).

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) | (1) Add 4 module-level `re.compile`'d pattern constants. (2) Add `_extract_metadata_block(idea: str) -> str` helper at ~L497 (just above `_extract_pr_number`). (3) Change `_extract_pr_number` signature to `(pipe: str, plan: str, spec: str, idea: str = "") -> int | None`. (4) Insert priority 3.5 (strict patterns A→B→C) and 3.6 (`**PR:**` frontmatter) between the existing fuzzy `merged`-context match (priority 3, ends ~L538) and the last-resort `re.findall` (priority 4, starts ~L539). Update the function's docstring to describe the new cascade. |

**Endpoints**

N/A — script file only.

**Key interfaces**

```python
# scripts/build_mvp1_dashboard.py — additions at ~L490 (above _extract_pr_number)

# Spec FR-2 Pattern A — own-PR shipped status with optional markdown link.
# Each \b is immediately after a \d+ capture (digit↔non-digit transition);
# placing \b after `]` or `)` would fail because both are non-word characters.
_IDEA_STATUS_SHIPPED_RE = re.compile(
    r"^\*\*Status:\*\*\s+\*\*Shipped\*\*\s+as\s+PR\s*"
    r"(?:\[#(\d+)\b\]\([^)]*\)|\[#(\d+)\b\]|#(\d+)\b)",
    re.MULTILINE,
)

# Spec FR-2 Pattern B — own-PR implemented status.
_IDEA_STATUS_IMPLEMENTED_RE = re.compile(
    r"^\*\*Status:\*\*\s+\*\*Implemented\s*[—\-]\s*PR\s*#(\d+)\b",
    re.MULTILINE,
)

# Spec FR-2 Pattern C — own-PR inline shipped dateline at line start.
# Leading ^ is load-bearing: prevents matching dependency cites such as
# `Depends on chore_X (**shipped 2026-05-21 as PR #N**)`.
_IDEA_SHIPPED_DATELINE_RE = re.compile(
    r"^\*\*shipped\s+\d{4}-\d{2}-\d{2}\s+as\s+PR\s*#(\d+)\b",
    re.MULTILINE,
)

# Spec FR-3 — `**PR:**` frontmatter pattern, applied only to the bounded
# metadata block (see _extract_metadata_block).
_IDEA_PR_FRONTMATTER_RE = re.compile(r"^\*\*PR:\*\*\s+#(\d+)\b", re.MULTILINE)

# Spec FR-3 — metadata-key pattern matching `**Date:**`, `**Status:**`, etc.
# Used by _extract_metadata_block to identify contiguous metadata lines.
_METADATA_KEY_RE = re.compile(r"^\*\*[A-Z][a-zA-Z ]+:\*\*")


def _extract_metadata_block(idea: str) -> str:
    """Return the bounded metadata block at the top of an idea body.

    Per spec FR-3: the block is the contiguous prefix of `idea` that
    contains the title line (allowed ONLY as the first non-blank line),
    blank lines, and metadata-key lines (e.g., ``**Date:**``,
    ``**Status:**``, ``**Priority:**``, ``**PR:**``). Scanning stops at
    either (a) a ``## `` heading line, OR (b) a non-blank line that is
    neither the initial title nor a metadata-key match. A 30-line
    ceiling caps headingless edge cases.

    The ``title_seen`` flag ensures only the FIRST ``# `` line counts as
    the title — a later ``# `` line in the same idea would be a non-
    metadata body heading and stops the block (otherwise a malformed
    headingless idea with a later H1 could let a body ``**PR:**`` line
    slip into the search scope; GPT-5.5 plan-cycle-1 finding B1).

    This is the search scope for the `**PR:**` frontmatter convention
    (spec priority 3.6) — it prevents body-section `**PR:**` references
    (e.g., inside ``## Related``) from being misread as this feature's
    own PR.
    """
    lines = idea.splitlines()
    cap = min(len(lines), 30)
    title_seen = False
    for idx in range(cap):
        line = lines[idx]
        if line.startswith("## "):
            return "\n".join(lines[:idx])
        stripped = line.strip()
        if not stripped:
            continue
        # The title line is allowed ONLY as the first non-blank line.
        if stripped.startswith("# ") and not title_seen:
            title_seen = True
            continue
        # Anything else that's not a metadata key ends the block.
        if not _METADATA_KEY_RE.match(stripped):
            return "\n".join(lines[:idx])
    return "\n".join(lines[:cap])
```

Then in the updated `_extract_pr_number` body, between current priorities 3 and 4:

```python
# 3.5. Strict idea-body patterns (own-PR assertions).
# Per spec FR-2: each pattern is line-anchored to prevent dependency-cite
# false positives. Order matters: A → B → C, first match wins.
for pattern in (
    _IDEA_STATUS_SHIPPED_RE,
    _IDEA_STATUS_IMPLEMENTED_RE,
    _IDEA_SHIPPED_DATELINE_RE,
):
    m = pattern.search(idea)
    if m:
        # Pattern A has 3 alternation groups; only one is non-empty per match.
        for group in m.groups():
            if group:
                return int(group)

# 3.6. `**PR:**` frontmatter fallback, scoped to the bounded metadata block.
# Per spec FR-3: prevents body-section **PR:** narrative references from matching.
m = _IDEA_PR_FRONTMATTER_RE.search(_extract_metadata_block(idea))
if m:
    return int(m.group(1))
```

**Pydantic schemas**

N/A.

**Tasks**

1. Read [`scripts/build_mvp1_dashboard.py:495-545`](../../../../scripts/build_mvp1_dashboard.py#L495) to confirm the current `_extract_pr_number` body and the exact insertion point for priority 3.5/3.6 (between the fuzzy-merged matches at ~L530-540 and the last-resort `findall` at ~L540).
2. Add the 5 module-level regex constants (`_IDEA_STATUS_SHIPPED_RE`, `_IDEA_STATUS_IMPLEMENTED_RE`, `_IDEA_SHIPPED_DATELINE_RE`, `_IDEA_PR_FRONTMATTER_RE`, `_METADATA_KEY_RE`) immediately above `_extract_pr_number` at ~L495. Order constants A → B → C → PR → metadata_key for readability.
3. Add the `_extract_metadata_block(idea: str) -> str` helper at ~L497 (after the constants, before `_extract_pr_number`).
4. Change `_extract_pr_number`'s signature from `(pipe: str, plan: str, spec: str) -> int | None` to `(pipe: str, plan: str, spec: str, idea: str = "") -> int | None`. Default-arg preserves AC-11 backward-compat.
5. Update the function's docstring to document the new cascade (priorities 1, 2, 3, 3.5, 3.6, 4) and reference spec §"Decision log" 2026-05-23 priority-slotting decision.
6. Insert the priority 3.5 / 3.6 logic between the existing priority 3 (fuzzy `merged`-context, ends with the second `re.search(...merged...)` block) and priority 4 (last-resort `re.findall`). Use the snippet from the **Key interfaces** section verbatim.
7. Run `make backend-fmt` (ruff format) — verify the new constants and helper format consistently.
8. Run `make backend-lint` (ruff check) — green.
9. Run `make backend-typecheck` (mypy --strict) — green; the new helper is typed `(str) -> str` and the signature change keeps the explicit return annotation.
10. Run `make test-unit` — full unit suite must pass against the new code (and against the new test file in Story 1.2 — but Story 1.2's call-site updates come second; Story 1.1's tests work against the function directly with idea content passed in).

**Definition of Done (DoD)**

- [ ] 5 module-level regex constants exist at top-of-file (above `_extract_pr_number`) and are `re.compile`'d once at import time. **Verified by `grep -c "^_IDEA_.*_RE = re.compile\|^_METADATA_KEY_RE = re.compile" scripts/build_mvp1_dashboard.py` returning `5`.**
- [ ] `_extract_metadata_block(idea: str) -> str` exists and is typed.
- [ ] `_extract_pr_number`'s signature is `(pipe: str, plan: str, spec: str, idea: str = "") -> int | None` — verified by inspecting the function definition.
- [ ] The function's docstring lists the priorities `1 → 2 → 3 → 3.5 → 3.6 → 4` with one-line descriptions for the new entries.
- [ ] Priority 3.5 iterates through the three patterns in order A → B → C.
- [ ] Priority 3.5 handles Pattern A's three-group alternation (coalesces the non-empty group).
- [ ] Priority 3.6 uses `_extract_metadata_block(idea)` to scope the search, not the raw idea text.
- [ ] `make backend-fmt` / `make backend-lint` / `make backend-typecheck` green locally.
- [ ] `make test-unit` green locally (the existing unit suite must not regress; new tests are written in Story 1.2's same-day commit).
- [ ] No changes to priorities 1, 2, 3, or 4 in `_extract_pr_number` — diff against `HEAD~1 scripts/build_mvp1_dashboard.py` shows only ADDED lines for the constants, helper, and new priority blocks, plus the function signature line.

### Story 1.2 — `_load_implemented` + `_load_planned` thread `idea` through; tests + docs

**Outcome:** Both feature-loader sites read `idea.md` and pass its content as the 4th argument to `_extract_pr_number`. A new test file `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` ships ≥17 unit tests covering every AC. `architecture.md`'s `## Where the code lives` section gains a brief subsection documenting the `**PR:**` frontmatter convention.

**FR coverage:** FR-4 + tests for FR-1/2/3/5. AC coverage: AC-12 (end-to-end `_load_implemented` with idea-only folder) + locks the test cases for AC-1 through AC-17.

**New files**

| File | Purpose |
|---|---|
| [`backend/tests/unit/scripts/test_dashboard_pr_extraction.py`](../../../../backend/tests/unit/scripts/test_dashboard_pr_extraction.py) (new) | Unit tests for `_extract_pr_number`'s idea-aware behavior + the `_extract_metadata_block` helper. Covers all 17 ACs from the spec plus one mutual-exclusion case (Pattern A and Pattern B cannot both match the same line because their `**Status:** **Shipped**` vs `**Status:** **Implemented`** prefixes are mutually exclusive). |

**Modified files**

| File | Change |
|---|---|
| [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) | (1) In `_load_implemented` (~L661–690), add `idea = _read(folder_path / "idea.md")` after the existing `pipe = _read(...)` line and change the `_extract_pr_number(pipe, plan, spec)` call (~L673) to `_extract_pr_number(pipe, plan, spec, idea)`. (2) Apply the same pattern to the `_load_planned` call site (~L646 area). Symmetry between the two loaders is the goal. |
| [`architecture.md`](../../../../architecture.md) | Add ~6-line subsection at the end of §"Where the code lives" (after the `scripts/` line) documenting (a) `scripts/build_mvp1_dashboard.py` as the regen entrypoint, (b) the `**PR:**` frontmatter convention for legacy idea-only features that don't fit the natural Status patterns. Single short paragraph; no new top-level heading. |

**Endpoints**

N/A.

**Key interfaces**

```python
# scripts/build_mvp1_dashboard.py — _load_implemented update (~L661-690)

def _load_implemented(folder_path: Path) -> Feature | None:
    folder = folder_path.name
    # ... (existing prefix/short parsing unchanged) ...

    spec = _read(folder_path / "feature_spec.md")
    plan = _read(folder_path / "implementation_plan.md")
    pipe = _read(folder_path / "pipeline_status.md")
    idea = _read(folder_path / "idea.md")  # NEW

    one_liner = _extract_one_liner(spec, source_dir=folder_path)
    pr = _extract_pr_number(pipe, plan, spec, idea)  # CHANGED: added idea
    # ... rest of function unchanged ...


# scripts/build_mvp1_dashboard.py — _load_planned update (~L630-660)

def _load_planned(folder_path: Path) -> Feature | None:
    # ... (existing prefix/short parsing unchanged) ...

    idea = _read(folder_path / "idea.md")
    spec = _read(folder_path / "feature_spec.md")
    plan = _read(folder_path / "implementation_plan.md")
    pipe = _read(folder_path / "pipeline_status.md")

    one_liner = _extract_one_liner(idea or spec, source_dir=folder_path)
    pr = _extract_pr_number(pipe, plan, spec, idea)  # CHANGED: added idea (was 3-arg)
    # ... rest of function unchanged ...
```

**Pydantic schemas**

N/A.

**Tasks**

1. Re-read [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) `_load_implemented` (~L661-690) and `_load_planned` (~L625-660) to confirm the exact line numbers and surrounding code (line numbers may have shifted slightly after Story 1.1's additions; the function-name anchors are stable).
2. Add `idea = _read(folder_path / "idea.md")` to `_load_implemented` immediately after the existing `pipe = _read(...)` line.
3. Update the `_extract_pr_number(pipe, plan, spec)` call in `_load_implemented` to `_extract_pr_number(pipe, plan, spec, idea)`.
4. Apply the same two updates to `_load_planned` (read idea + pass it). Note: `_load_planned` likely already reads `idea = _read(...)` because it uses idea content for the one-liner; if so, just update the `_extract_pr_number` call.
5. Create `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` with the following test class structure:
   ```python
   """Tests for `_extract_pr_number`'s idea-aware extraction (chore_dashboard_pr_extraction_from_idea)."""

   from __future__ import annotations
   from pathlib import Path
   import tempfile
   import pytest

   from scripts.build_mvp1_dashboard import (
       _extract_pr_number,
       _extract_metadata_block,
       _load_implemented,
   )


   class TestStrictPatternExtraction:
       def test_ac1_status_shipped_unlinked_extracts(self) -> None: ...
       def test_ac1_status_shipped_linked_extracts(self) -> None: ...  # AC-1 + AC-16
       def test_ac2_status_implemented_extracts(self) -> None: ...
       def test_ac3_shipped_dateline_extracts(self) -> None: ...

   class TestFalsePositiveRejection:
       def test_ac4_dependency_only_pr_returns_none(self) -> None: ...
       def test_ac14_inline_bold_in_dependency_cite_does_not_match(self) -> None: ...
       def test_ac15_pattern_a_rejects_partial_bracket_token(self) -> None: ...
       def test_ac15_pattern_a_rejects_trailing_alphanum_token(self) -> None: ...
       def test_ac13_pr_in_body_section_does_not_match(self) -> None: ...
       def test_ac17_pr_at_line_50_does_not_match_headingless(self) -> None: ...

   class TestFrontmatterFallback:
       def test_ac5_pr_in_metadata_block_extracts(self) -> None: ...
       def test_ac6_strict_pattern_beats_frontmatter(self) -> None: ...

   class TestPriorityCascade:
       def test_ac7_pipeline_status_implement_section_beats_idea(self) -> None: ...
       def test_ac8_plan_status_header_beats_idea(self) -> None: ...
       def test_ac9_fuzzy_merged_in_spec_beats_idea(self) -> None: ...
       def test_ac10_last_resort_fires_when_idea_empty(self) -> None: ...

   class TestBackwardCompat:
       def test_ac11_three_arg_call_works(self) -> None: ...

   class TestEndToEnd:
       def test_ac12_load_implemented_extracts_from_idea_only_folder(self, tmp_path: Path) -> None: ...

   class TestMutualExclusion:
       def test_pattern_a_and_b_share_no_lines(self) -> None: ...
   ```
6. Write each test body, using the AC-N "Given/When/Then" from the spec as the test contract. Each test must include the literal idea-body text the spec cites as its precedent example (e.g., AC-1's body is `**Status:** **Shipped** as PR [#124](https://github.com/SoundMindsAI/relyloop/pull/124) (squash-merged 2026-05-15, commit `9d22f62`).` — verified against the actual `feat_contextual_help_mvp2/idea.md`).
7. The AC-12 test uses `pytest.fixture` or `tempfile.mkdtemp` to construct a real on-disk folder with a date-prefixed slug (e.g., `2026_05_20_chore_test_stub`) containing only `idea.md`. The `_load_implemented` call returns a `Feature` whose `pr_number` field is asserted.
8. Update `architecture.md` per the FR-3 requirement. Add a ~6-line subsection at the end of §"Where the code lives" (immediately after the `scripts/` mention at ~L141). Content:
   ```markdown
   ### Dashboard regen
   
   `scripts/build_mvp1_dashboard.py` regenerates `docs/00_overview/MVP1_DASHBOARD.md` + `mvp1_dashboard.html` (and the cross-release `DASHBOARD.md` + `dashboard.html`) from the planned-features and implemented-features folder tree. Triggered automatically by the `mvp1-dashboard-regen` pre-commit hook when a feature folder changes. **`**PR:**` frontmatter convention:** legacy idea-only implemented features that don't fit the natural `**Status:** **Shipped** as PR #N` / `**Status:** **Implemented — PR #N**` / line-start `**shipped YYYY-MM-DD as PR #N**` patterns may opt into PR# extraction by adding a `**PR:** #N` line to their idea.md metadata block (alongside `**Date:**`, `**Status:**`, etc.). Search is bounded to the metadata block per `chore_dashboard_pr_extraction_from_idea`'s spec — body-section references are ignored.
   ```
9. Run `make backend-fmt` / `make backend-lint` / `make backend-typecheck` / `make test-unit` — all green.
10. Run `make dashboard` to regenerate `MVP1_DASHBOARD.md` and capture the empirical-verification output per spec §14 step 3 (structural script): list the 5–8 newly-resolved PR rows + assert zero pre-existing PR rewrites. Document in PR body.

**Definition of Done (DoD)**

- [ ] `_load_implemented` reads `idea.md` and passes `idea` as 4th arg to `_extract_pr_number`. **Verified by `grep -c "_extract_pr_number(pipe, plan, spec, idea)" scripts/build_mvp1_dashboard.py` returning `2` (both call sites).**
- [ ] `_load_planned` reads `idea.md` and passes `idea` as 4th arg to `_extract_pr_number`.
- [ ] `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` exists and contains **≥18 test cases** (17 ACs + 1 mutual-exclusion). **Verified by `.venv/bin/pytest --collect-only -q backend/tests/unit/scripts/test_dashboard_pr_extraction.py | grep -c "::test_"` returning `≥ 18`.** (The `-q` flag is required — without it pytest emits a collection tree instead of node IDs that `grep` can count reliably.)
- [ ] All AC-1 through AC-17 tests pass via `.venv/bin/pytest backend/tests/unit/scripts/test_dashboard_pr_extraction.py -v`.
- [ ] Full `make test-unit` passes — no regression in existing tests (`test_dashboard_expand_transitive_deps.py`, `test_dashboard_priority_sort.py`, etc.).
- [ ] `architecture.md`'s §"Where the code lives" gains the `### Dashboard regen` subsection documenting the `**PR:**` frontmatter convention.
- [ ] `make dashboard` regen produces the expected forward gain (5–8 new PR rows) AND no PR# regressions. Transcript pasted in PR body per spec §14 step 3.
- [ ] No backfill of any existing legacy idea folder — `git status` after the chore shows changes only to `scripts/`, `backend/tests/`, `architecture.md`, the planned-features chore folder, and the regenerated dashboard files.

---

## UI Guidance (required for frontend-facing work)

**N/A — this chore has no frontend scope.** No user-facing components are added, moved, or deleted. The Legacy Behavior Parity table is omitted accordingly: no user-facing component >100 LOC is being deleted or migrated in this plan.

---

## 3) Testing workstream (required)

### 3.1 Unit tests

- Location: `backend/tests/unit/scripts/`
- Scope: `_extract_pr_number`'s idea-aware extraction + `_extract_metadata_block` + `_load_implemented` integration on a real on-disk folder.
- Tasks:
  - [ ] Create [`backend/tests/unit/scripts/test_dashboard_pr_extraction.py`](../../../../backend/tests/unit/scripts/test_dashboard_pr_extraction.py) with the 8 test classes listed in Story 1.2 task 5, covering ≥17 test cases.
  - [ ] Each test asserts against the literal idea-body text the spec cites as its precedent example.
  - [ ] AC-12's test uses `tmp_path` fixture to construct a real on-disk folder.
- DoD:
  - [ ] All 17 ACs (AC-1 through AC-17) have at least one test case.
  - [ ] All tests pass via `make test-unit`.
  - [ ] Coverage of `_extract_pr_number` (lines added by Story 1.1) is ≥90% by `pytest-cov` measurement (the function is small enough that 100% should be achievable; settling for ≥90% to allow for the priority-4 fallback being covered by existing tests).

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: N/A — the script is hermetic (no DB, no network). The unit-test layer's `tmp_path`-based test for AC-12 effectively exercises the filesystem-reading code path.
- Tasks: none.
- DoD: existing integration suite remains green (`make test-integration`).

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: N/A — no API surface.
- Tasks: none.
- DoD: existing contract suite remains green (`make test-contract`).

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Scope: N/A — no UI surface.
- Tasks: none.
- DoD: existing E2E suite remains green (CI gates it; not run as part of this PR locally).

### 3.5 Existing test impact audit (required for refactors and UI changes)

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py` | calls to `_extract_pr_number` | 0 (file tests `_merge_order_key` + `_expand_transitive_deps`) | **No change.** New signature backward-compat ensures no regression. |
| `backend/tests/unit/scripts/test_dashboard_priority_sort.py` | calls to `_extract_pr_number` | 0 | **No change.** |
| `backend/tests/unit/scripts/test_dashboard_release_classifier.py` | calls to `_extract_pr_number` | 0 | **No change.** |
| `backend/tests/unit/scripts/test_dashboard_path_rewrite_and_idempotency.py` | calls to `_extract_pr_number` | 0 | **No change.** |
| `backend/tests/unit/scripts/test_dashboard_truncation.py` | calls to `_extract_pr_number` | 0 | **No change.** |
| All other backend tests | `_extract_pr_number` references | 0 (verified: `grep -rn "_extract_pr_number" backend/`) | None. |

### 3.5 Migration verification (if schema changes)

N/A — this chore makes no schema changes.

### 3.6 CI gates

- [ ] `make backend-fmt` (ruff format) — green
- [ ] `make backend-lint` (ruff check) — green
- [ ] `make backend-typecheck` (mypy --strict) — green
- [ ] `make test-unit` — green (new tests pass + no regression in existing tests)
- [ ] `make test-contract` — green (no new contract tests; verifies unrelated regressions)
- [ ] `make test-integration` — green (no new integration tests; verifies unrelated regressions when CI Postgres available)
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` — green (no UI changes; verifies unrelated regressions)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files (required for every implementation plan)

**`state.md`** — update at finalization:
- [ ] Add a one-line entry under "Recent changes" pointing at the chore PR.
- [ ] No active-branch change (the finalization PR cleans up the branch).
- [ ] Alembic head does NOT move — this chore makes no schema changes.

**`architecture.md`** — Story 1.2 task 8: add ~6-line `### Dashboard regen` subsection at end of §"Where the code lives" documenting the `**PR:**` frontmatter convention. **This is the spec FR-3 documentation requirement.**

**`CLAUDE.md`** — no updates required. No new conventions for end-developers (the `**PR:**` frontmatter is a back-of-house regen convention, not an end-developer rule).

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] No updates required beyond the `architecture.md` `### Dashboard regen` subsection.

### 4.2 Product docs (`docs/02_product`)

- [ ] No updates required for the planned-features folder beyond finalization. At finalization, the folder moves to `docs/00_overview/implemented_features/2026_05_23_chore_dashboard_pr_extraction_from_idea/`.

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] No updates required.

### 4.4 Security docs (`docs/04_security`)

- [ ] No updates required.

### 4.5 Quality docs (`docs/05_quality`)

- [ ] No updates required.

**Documentation DoD**

- [ ] `architecture.md` `### Dashboard regen` subsection added (Story 1.2).
- [ ] `state.md` updated at finalization (separate PR).
- [ ] `CLAUDE.md` unchanged.

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals

- **Resolve the data gap** where idea-only legacy implemented features render as `Complete` instead of `[PR #N](url) merged YYYY-MM-DD` in the regenerated dashboard.
- **Fix the `_merge_order_key` end-of-day fallback** for those features so they participate correctly in the `DEPS_ALL_BACKEND` transitive-dependency expansion introduced by [`bug_dashboard_depends_on_column_bloat`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/) PR #208.

### 5.2 Planned refactor tasks

- [ ] Story 1.1: extend `_extract_pr_number` with strict-pattern + frontmatter logic.
- [ ] Story 1.2: thread `idea.md` content through `_load_implemented` + `_load_planned`; add test file; document `**PR:**` convention.
- [ ] No frontend changes, no dead-code removal.

### 5.3 Refactor guardrails

- [ ] Backward-compat proven by AC-11 + the existing test files' continued green status.
- [ ] No false positives proven by AC-4 + AC-13 + AC-14 + AC-17 (the foundational anti-regression test set).
- [ ] `make backend-fmt` / `make backend-lint` / `make backend-typecheck` remain green.
- [ ] No expansion of product scope — the chore is bounded to extraction logic.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `bug_dashboard_depends_on_column_bloat` PR #208 (introduced `_merge_order_key` + time-ordered transitive-dep filter) | Story 1.1 + Story 1.2 — the dependency surface this chore polishes | **Shipped 2026-05-23** ([implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/)) | N/A — already merged. |
| `make dashboard` works locally for empirical verification | Story 1.2 task 10 | Implemented (verified in prior dashboard chores) | If `make dashboard` fails, fall back to manually running `uv run python scripts/build_mvp1_dashboard.py` per the Makefile target's actual invocation. |
| At least 5 idea-only legacy features with parseable strict patterns | Story 1.2 empirical verification | Implemented (preflight survey confirmed `feat_contextual_help_mvp2`, `chore_create_study_modal_e2e_stability`, `chore_data_table_columnvisibility_tanstack`, `chore_precommit_node_path_resolution`, and possibly others carry the strict patterns) | If the empirical verification finds 0 newly-resolved features, the chore's runtime correctness is fine but the operator value is zero — investigate which features the survey miscounted. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pattern A's three-group alternation coalescing logic is implemented wrong (e.g., always returns the first non-None group, missing the digit-↔-non-digit boundary placement) | Low (the spec cycle-2 fix is explicit; key-interface snippet locks the implementation) | Medium (would silently fail AC-1 + AC-16 against linked PR forms) | Story 1.1 task 6 copies the snippet from spec FR-2 verbatim; AC-1 and AC-16 tests are the canaries. If either fails, the snippet is wrong. |
| The bounded metadata-block algorithm has an off-by-one error or misses a real metadata-key shape (e.g., `**Owners:**` which exists in feature_spec headers but not idea headers) | Low (idea bodies use a stable set of metadata keys per `idea-template.md`; algorithm tested against actual precedents) | Low (would only cause a body-section `**PR:**` to match in headingless ideas, which is the AC-17 case being locked anyway) | The `_METADATA_KEY_RE` is intentionally generous (`^\*\*[A-Z][a-zA-Z ]+:\*\*`) to handle any title-case key. AC-17 locks the cap-based stop for headingless edge cases. |
| Empirical verification reveals an existing PR-linked row's PR# changed | Low (priority cascade puts idea-body below pipe/plan/spec; for currently-PR-linked rows, one of those wins) | High (would indicate a spec bug — the cascade ordering is wrong) | Story 1.2 task 10's structural-comparison script catches this. If any row's PR# changes, halt and investigate before merge. |
| The new `idea` argument's default `""` interacts unexpectedly with `_extract_metadata_block("")` | Low | Low | `_extract_metadata_block("")` returns `""` (the loop doesn't iterate, `"\n".join(lines[:cap])` returns `""` because `cap == 0`). The downstream `_IDEA_PR_FRONTMATTER_RE.search("")` returns `None`. Default behavior is correct fall-through. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| `idea.md` file missing in an implemented_features folder | New folder shape, or `_read` failure | `_read` returns `""` (existing helper behavior); `_extract_pr_number` falls through priority 3.5/3.6 (no match against empty string) to priority 4. **No exception raised.** | N/A — graceful degradation by design. |
| Idea body contains BOTH a strict pattern and a `**PR:**` frontmatter with conflicting PRs | Author error or backfill mistake | Strict pattern wins (priority 3.5 beats 3.6). Locked by AC-6. | Author corrects the idea body. |
| `_extract_metadata_block` returns the entire idea body (no `## ` heading AND fewer than 30 lines AND all lines are metadata) | Genuinely short idea | The frontmatter search runs against the full content; for shorts that are all metadata, this is the intended behavior. | N/A — by design. |
| Pattern A's regex matches but ALL three capture groups are empty (impossible per Python regex semantics but defensive check) | Cannot happen | Defensive `for group in m.groups(): if group:` skips empties; if all empty, no return → fall-through to next pattern. | N/A — defensive. |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — extend `_extract_pr_number` (constants + helper + priority 3.5/3.6 insertion). The new code path is unreachable from production until Story 1.2 threads `idea` content into the call sites, but the function is fully callable from tests with `idea=...` keyword.
2. **Story 1.2** — update `_load_implemented` + `_load_planned`; add test file; document the `**PR:**` convention in `architecture.md`. Empirical verification (`make dashboard`) runs as the final step of Story 1.2.

Story 1.1 must complete before Story 1.2's tests can run end-to-end (AC-12 imports `_load_implemented` which uses the extended `_extract_pr_number`). Story 1.1's own non-AC-12 tests can run independently; Story 1.2's tests need both stories.

### Parallelization opportunities

None — the two stories are sequential by data dependency.

## 8) Rollout and cutover plan

- **Rollout stages:** N/A — build-script change with no runtime user impact.
- **Feature flags / staged rollout:** N/A.
- **Migration/cutover steps:** N/A — no schema changes.
- **Reconciliation/repair strategy:** N/A — no external systems.

## 9) Execution tracker (copy/paste section)

### Current sprint

- [ ] Story 1.1 — Extend `_extract_pr_number` with strict-pattern + frontmatter logic + `_extract_metadata_block` helper
- [ ] Story 1.2 — Thread `idea` through `_load_implemented` + `_load_planned`; write `test_dashboard_pr_extraction.py`; add `architecture.md` subsection
- [ ] Empirical verification: `make dashboard` shows 5–8 newly-resolved PR rows + zero PR# regressions
- [ ] CI green (lint + typecheck + unit + integration + contract + Docker build + frontend)
- [ ] Gemini Code Assist review adjudicated
- [ ] Final GPT-5.5 cross-model review on the merged diff

### Blocked items

None.

### Done this sprint

- (populated during execution)

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files modified match story scope (`Modified files` tables — Story 1.1: `scripts/build_mvp1_dashboard.py` only; Story 1.2: `scripts/build_mvp1_dashboard.py` + `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` + `architecture.md`).
- [ ] No endpoint contract changes (chore is script-only).
- [ ] Key interfaces (Story 1.1's `_extract_metadata_block`, the 5 regex constants, the extended `_extract_pr_number`) implemented with the exact signatures documented in **Key interfaces**.
- [ ] Required tests pass at every layer where applicable:
  - [ ] `make test-unit` — green (Story 1.2's new test file + no regression in existing suite)
  - [ ] `make test-integration` — green (no new integration tests; suite must not regress; skipped locally when Postgres unreachable, gated by CI)
  - [ ] `make test-contract` — green (no new contract tests; suite must not regress)
  - [ ] `cd ui && pnpm test` — green (no UI changes; suite must not regress)
- [ ] No migration round-trip evidence required (no schema change).
- [ ] Empirical verification (`make dashboard` structural comparison) documented in the PR body with the forward-gain count + the zero-regression assertion.
- [ ] `architecture.md` `### Dashboard regen` subsection landed (Story 1.2 DoD).

## 11) Plan consistency review (required before execution)

Performed inline during plan generation. Findings:

1. **Spec ↔ plan FR coverage:** All 5 FRs (FR-1, FR-2, FR-3, FR-4, FR-5) covered by Story 1.1 + Story 1.2. ✅
2. **Spec ↔ plan AC coverage:** All 17 ACs mapped to a specific test case in Story 1.2's task 5 test inventory. ✅
3. **Spec ↔ plan endpoint count:** Both are zero. Trivially consistent. ✅
4. **Spec ↔ plan error code coverage:** Both are zero. Trivially consistent. ✅
5. **Test file count:** 1 new test file (`test_dashboard_pr_extraction.py`); matches §3 testing workstream inventory. Story 1.2 owns it. ✅
6. **Open questions resolved:** Spec §19 reports zero open questions. ✅
7. **Plan ↔ codebase verification:**
   - `scripts/build_mvp1_dashboard.py` exists ✅
   - `_extract_pr_number` exists at L499 (line drift since idea was drafted is documented in idea preflight) ✅
   - `_load_implemented` exists at L661 ✅
   - `_load_planned` exists in the same script (verified via `grep -n "def _load_planned" scripts/build_mvp1_dashboard.py`) ✅
   - `backend/tests/unit/scripts/` exists with 5 existing test files; the new `test_dashboard_pr_extraction.py` follows the same `test_dashboard_*` naming convention ✅
   - `architecture.md` §"Where the code lives" exists at L87+; the `scripts/` mention at L141 is the anchor for the new subsection ✅
   - All 5 cited precedent idea files for strict patterns exist in `implemented_features/` (verified during preflight) ✅
8. **Infrastructure path verification:**
   - No migrations, no router registration, no service layer. N/A. ✅
   - Test directory: `backend/tests/unit/scripts/` (verified by `ls`). ✅
9. **Enumerated value contract audit:** N/A — no filters, no dropdowns, no sort controls, no badges, no API enums. ✅
10. **Admin control / ceiling enforcement audit:** N/A — MVP1 has no admin/tenant model. ✅
11. **Audit-event coverage audit:** N/A — MVP1 has no `audit_log` table; chore touches no business state regardless. ✅
12. **Persistence scope:** N/A — no client-side storage.
13. **Legacy behavior parity:** N/A — no user-facing component >100 LOC is being deleted or migrated.

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates. (FR-1 → Story 1.1; FR-2 → Story 1.1; FR-3 → Story 1.1; FR-4 → Story 1.2; FR-5 → Story 1.1 + 1.2.)
- [x] Every story includes New files, Modified files, Tasks, and DoD. (Endpoints / Schemas omitted per template rule — both stories are test-only / refactor.)
- [x] Test layers explicitly scoped (Unit: new file with ≥18 cases; Integration/Contract/E2E: N/A by scope).
- [x] Documentation updates across docs/01-05 are planned (architecture.md `### Dashboard regen` subsection in Story 1.2; `state.md` at finalization).
- [x] Lean refactor scope and guardrails explicit.
- [x] Phase/epic gates measurable (Story 1.2 DoD includes the empirical-verification structural comparison).
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review (§11) performed with no unresolved findings.
