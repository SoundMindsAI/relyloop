# Feature Specification — `_extract_pr_number` reads `idea.md` for legacy idea-only features

**Date:** 2026-05-23
**Status:** Implemented (PR #221 squash-merged as `8a6452d5` on 2026-05-23)
**Owners:** Eric Starr (engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) (the regen script)
- [`backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py`](../../../../backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py) (existing tests for the surrounding `_merge_order_key` / `_expand_transitive_deps` work)
- [`bug_dashboard_depends_on_column_bloat`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/) (PR #208, shipped 2026-05-23 — created the regression surface this chore polishes)

---

## 1) Purpose

- **Problem:** [`_extract_pr_number`](../../../../scripts/build_mvp1_dashboard.py#L499) is called from [`_load_implemented`](../../../../scripts/build_mvp1_dashboard.py#L661) with `_read(folder/"pipeline_status.md") + _read(folder/"implementation_plan.md") + _read(folder/"feature_spec.md")`. For ~50 early MVP1 features that shipped before the `/pipeline` ceremony solidified, only `idea.md` exists in their `implemented_features/<date>_<slug>/` folder — so all three reads return empty strings and the function returns `None`. Downstream: (a) those features render as `Complete` instead of `[PR #N](url) merged YYYY-MM-DD` in the dashboard's shipped table; (b) they sort to end-of-day in [`_merge_order_key`](../../../../scripts/build_mvp1_dashboard.py#L716) (`(merged_date, 999_999, folder)`), placing them AFTER same-day peers with concrete PR numbers and excluding them from the time-ordered `DEPS_ALL_BACKEND` expansion that [`bug_dashboard_depends_on_column_bloat`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/) (PR #208) introduced.
- **Outcome:** Extend `_extract_pr_number` to accept the idea body as a fourth argument, and have `_load_implemented` read `idea.md` and pass it through. The extraction logic uses **strict idea-body patterns** that assert "this is THIS feature's PR" (e.g., `**Status:** **Shipped** as PR #N`, `**Status:** **Implemented — PR #N**`, `**shipped … as PR #N**`) rather than the existing function's `merged`-context fuzzy match — which would extract dependency or sibling PRs from typical legacy ideas. A new optional `**PR:**` frontmatter convention provides a fallback for genuinely silent legacy ideas, applied opportunistically by future work that touches their folders. **No backfill of existing legacy features in this chore** — extraction logic only.
- **Non-goal:** Backfilling the ~50 idea-only legacy folders. That's separate scope captured as a future-work observation, not packaged here.

## 2) Current state audit

### Existing implementations

- [`scripts/build_mvp1_dashboard.py:499-540`](../../../../scripts/build_mvp1_dashboard.py#L499) — `_extract_pr_number(pipe: str, plan: str, spec: str) -> int | None`. Four-priority cascade:
  1. `pipeline_status.md`'s `## Implement` section (most authoritative — wins).
  2. Plan's `**Status:** … PR #N` header.
  3. `merged`-context fuzzy match across `pipe + "\n" + plan + "\n" + spec`, AFTER `_strip_dependency_table_rows` strips Dependencies-table content so cites like `| feat_study_lifecycle Phase 1 | All stories | Implemented (PR #18, #25) |` don't leak.
  4. First `#N` reference outside any dependency-table row, as a last-resort fallback.
- [`scripts/build_mvp1_dashboard.py:661-690`](../../../../scripts/build_mvp1_dashboard.py#L661) — `_load_implemented(folder_path)`. Reads `feature_spec.md`, `implementation_plan.md`, `pipeline_status.md`. **Does NOT read `idea.md`.** Calls `_extract_pr_number(pipe, plan, spec)` at line 673.
- [`scripts/build_mvp1_dashboard.py:716-734`](../../../../scripts/build_mvp1_dashboard.py#L716) — `_merge_order_key(f: Feature) -> tuple[str, int, str]`. Sort tuple is `(merged_date_or_9999_99_99, pr_number_or_999_999, folder)`. The `999_999` fallback for missing PR# is what places idea-only legacy features at the end of their day in time-ordered scans.
- [`scripts/build_mvp1_dashboard.py:646`](../../../../scripts/build_mvp1_dashboard.py#L646) — `_extract_pr_number(pipe, plan, spec)` is also called from `_load_planned` for in-flight features. **In-flight features always have at least an idea.md and typically a feature_spec.md**, so the in-flight call path doesn't strictly need the new idea-aware logic — but for surface consistency the same signature update flows through both call sites.
- [`backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py`](../../../../backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py) — 197 lines, two test classes (`TestExpandTransitiveDeps` + `TestMergeOrderKey`). Provides `_feat()` helper for constructing Feature objects. New PR-extraction tests can either live alongside (in a new `TestExtractPrNumberFromIdea` class) or in a sibling file (`test_dashboard_pr_extraction.py`).
- Survey of `implemented_features/<date>_<slug>/idea.md` (run during preflight, 2026-05-23): ~50 idea-only folders. ~5–8 carry usable own-PR mentions in strict patterns (`**Status:** **Shipped** as PR #N` etc.); ~10 mention OTHER features' PRs (dependencies, parent features); ~35 have no PR mention at all.

### Navigation and link impact

N/A — no UI, no URL changes, no docs link rewrites in `docs/`. The dashboard output itself changes (more rows show `PR #N` instead of `Complete`) but that's the feature's goal, not a side-effect.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py` | `_extract_pr_number(` calls | 0 (the file doesn't test extraction directly) | No regression risk — but new tests for PR# extraction will be added here or in a sibling file. |
| `backend/tests/unit/scripts/test_dashboard_priority_sort.py` | `_extract_pr_number(` calls | 0 | No regression risk. |
| All other backend tests | `_extract_pr_number` references | 0 (`grep -rn "_extract_pr_number" backend/`) | None. |

### Existing behaviors affected by scope change

- **Behavior:** `_extract_pr_number(pipe, plan, spec)` accepts exactly 3 string arguments. **Current:** Returns `None` for idea-only folders. **New:** Accepts a 4th `idea: str = ""` argument with a default to preserve backward-compat call sites; tries idea-body strict patterns at new priority slot 3.5 (between fuzzy-merge and last-resort). Decision needed: **No** — the signature evolution is locked in §19 decision log (default arg keeps in-flight call paths working without simultaneous updates; both call sites in `build_mvp1_dashboard.py` are updated in the same PR).
- **Behavior:** Idea-only folders currently get `pr_number=None`, which makes `_merge_order_key` return `(date, 999_999, folder)`. **New:** Folders whose idea body carries one of the strict patterns get a real `pr_number`, so the tuple becomes `(date, <pr#>, folder)` and they sort correctly within the day. Decision needed: **No** — this is the whole point of the feature.

---

## 3) Scope

### In scope

- Extend `_extract_pr_number` signature: `def _extract_pr_number(pipe: str, plan: str, spec: str, idea: str = "") -> int | None`. The new `idea` parameter defaults to `""` so the function's callability and current behavior are preserved for any consumer that doesn't pass it.
- Add a new priority **3.5** to the cascade (between current 3 and current 4): strict-pattern extraction against `idea`. Three patterns — **see FR-2 for the exact regex contracts including line-anchoring and `\b` boundary placement**. Precedents in the existing corpus:
  - `**Status:** **Shipped** as PR #N` / `... PR [#N](url)` — Pattern A. (`feat_contextual_help_mvp2` precedent.)
  - `**Status:** **Implemented — PR #N**` — Pattern B. (`chore_create_study_modal_e2e_stability` precedent.)
  - `**shipped YYYY-MM-DD as PR #N**` at line start — Pattern C. (`chore_precommit_node_path_resolution` precedent.)
- Add a new priority **3.6** (immediately after 3.5): `**PR:**` frontmatter convention. **See FR-3 for the exact contract** including the bounded metadata-block scope. This is the explicit escape hatch for legacy ideas that don't fit the natural patterns. **No backfill of existing folders in this chore** — convention is documented in `architecture.md`'s dashboard-regen section so future opportunistic edits know to use it.
- Update `_load_implemented` and `_load_planned` to also read `idea.md` and pass it through.
- Tests in `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` (new file, kept narrow rather than appended to the `test_dashboard_expand_transitive_deps.py` tests which target different unit-of-behavior). At least 5 cases covering: (1) `**Status:** **Shipped** as PR #N` → extracted; (2) `**Status:** **Implemented — PR #N**` → extracted; (3) `**shipped … as PR #N**` → extracted; (4) idea mentioning ONLY a dependency's PR → returns `None` (no false positive); (5) `**PR:** #N` frontmatter → extracted; (6) own-PR + dependency-PR both present → own-PR wins; (7) pipeline_status.md `## Implement` PR# wins over idea-body strict pattern (priority cascade lock).

### Out of scope

- **Backfilling the ~50 idea-only legacy folders** with `**PR:**` frontmatter. Captured for future opportunistic work; not bundled here. Rationale: each backfill row is a PR-history lookup + an idea.md edit, which compounds review surface beyond what this chore's logic-only value justifies.
- **Changing `_extract_pr_number`'s priority 1–3 logic.** Those paths already work and are covered by existing extraction in the dashboard regen.
- **Updating the dashboard's "Status" column rendering.** The column already renders `[PR #N](url) merged YYYY-MM-DD` when `pr_number is not None` and `Complete` otherwise. Once extraction works for legacy idea-only folders, the rendering automatically improves with no further code change.
- **Changing `_merge_order_key`.** The tuple shape stays; only the inputs improve.
- **Extracting PR# from external sources** (GitHub API, commit messages, etc.). The chore is markdown-only; runtime API calls would add a dependency on `GITHUB_TOKEN`/network reachability that the regen script has historically avoided.
- **Adding new dashboard table columns.** The fix surfaces in existing columns.

### API convention check

N/A — this chore touches only a build script + tests. No API endpoints, no router files, no error envelopes.

### Phase boundaries

Single phase, single PR. No phase boundaries.

## 4) Product principles and constraints

- **Idempotent regen:** `make dashboard` (`scripts/build_mvp1_dashboard.py`) must remain idempotent — running it twice in a row produces no diff. Adding the new extraction path doesn't change idempotency because it doesn't introduce state.
- **No false positives:** The strict patterns must NOT match dependency or sibling PR cites in legacy idea bodies (e.g., `merged via PR #4 (2026-05-09)` for `infra_foundation` as a dependency). This is the central correctness criterion; tests in §14 lock it.
- **Backward compat:** `_extract_pr_number(pipe, plan, spec)` calls without the new `idea` argument continue to work via the default `""` value. The in-flight `_load_planned` path that doesn't yet pass idea content is unaffected at runtime.
- **CLAUDE.md "no main commit" + Conventional Commits + 80% coverage gate** — all preserved (this chore touches Python scripts + tests, both well-covered already).

### Anti-patterns

- **Do not** reuse the existing fuzzy `merged`-context regex (current priority 3) against `idea` content. The preflight survey showed that ~10 idea-only legacy files would produce false-positive PR# extractions (dependency, sibling, or parent-feature PRs presented in `merged`-context phrasing). Using strict patterns prevents this entire class of error.
- **Do not** add network or GitHub-API lookups. The regen script is hermetic per dashboard-regen conventions (it reads `docs/` and writes `docs/00_overview/*.{md,html}` — no external state).
- **Do not** add `**PR:**` frontmatter to existing legacy idea files as part of this chore. That's a separately-scoped backfill; bundling it inflates the diff with cross-folder edits that obscure the logic change being reviewed.
- **Do not** insert idea-body extraction at priority 1 or 2. Pipeline_status.md and plan `**Status:**` headers are canonical for shipped features and must beat idea-body patterns. Inserting at priority 3.5/3.6 (between fuzzy-merge and last-resort) keeps the cascade's authority order intact.
- **Do not** combine the strict-pattern lookups with the existing fuzzy regex via fall-through. They are distinct regimes — strict patterns operate on idea-body, fuzzy regex operates on `pipe + plan + spec` (which the new code doesn't touch).

## 5) Assumptions and dependencies

- **Assumption:** Future opportunistic backfills of `**PR:**` frontmatter on legacy idea folders are acceptable — i.e., when someone edits a legacy idea for any reason, adding the frontmatter line is a low-friction expected pattern. Documented in `architecture.md`'s dashboard-regen section as part of this chore.
- **Dependency:** [`bug_dashboard_depends_on_column_bloat`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/) shipped 2026-05-23 as PR #208. Created the regression-visibility surface. Hard dependency; merged before this chore starts.
- **Dependency:** The dashboard regen tests at `backend/tests/unit/scripts/` use direct imports from `scripts.build_mvp1_dashboard`. No new test infrastructure needed.

## 6) Actors and roles

- Primary actor: developer or AI agent running `make dashboard` (or the `mvp1-dashboard-regen` pre-commit hook).
- Role model: N/A — single-tenant install, no auth surface.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2; this chore is a build-script refactor with no business state.

---

## 7) Functional requirements

### FR-1: Extended `_extract_pr_number` signature

- **Requirement:**
  - The system **MUST** change the signature of `_extract_pr_number` to `def _extract_pr_number(pipe: str, plan: str, spec: str, idea: str = "") -> int | None`.
  - The `idea` parameter **MUST** default to `""` so existing callers that don't pass it continue to work unchanged (backward compat).
  - The function **MUST** remain pure (no I/O, no side effects, no global state mutation). It accepts strings and returns `int | None`, exactly as today.

### FR-2: Strict-pattern extraction (priority 3.5)

- **Requirement:**
  - The system **MUST** insert a new extraction path between current priority 3 (fuzzy `merged`-context match) and current priority 4 (last-resort first `#N`).
  - The new path **MUST** try three strict regex patterns against the `idea` argument, in order. All patterns are line-anchored (`^` with `re.MULTILINE`) so that dependency cites embedded inside table rows or narrative prose cannot accidentally match. Verified against the actual precedent ideas at column 0 of their respective Status / shipped lines.
    - **Pattern A:** `r"^\*\*Status:\*\*\s+\*\*Shipped\*\*\s+as\s+PR\s*(?:\[#(\d+)\b\]\([^)]*\)|\[#(\d+)\b\]|#(\d+)\b)"` with `re.MULTILINE`. The non-capturing alternation requires either a fully-bracketed markdown link `[#N](url)`, a bare bracketed `[#N]`, or an unbracketed `#N` — each with `\b` placed **immediately after the digit capture** so the boundary check fires on a digit↔non-digit transition (not after the closing bracket / paren, where `\b` would fail because `)` and `]` are non-word characters and would not produce a boundary against following non-word chars like spaces or end-of-string). Exactly one of the three capture groups will be non-empty per match; the implementation MUST coalesce the non-empty group to extract the integer. The boundary placement prevents partial-token matches like `PR [#124abc` or `PR [#124` (missing closing bracket).
    - **Pattern B:** `r"^\*\*Status:\*\*\s+\*\*Implemented\s*[—\-]\s*PR\s*#(\d+)\b"` with `re.MULTILINE`. The trailing `\b` prevents partial-token matches like `PR #161abc`.
    - **Pattern C:** `r"^\*\*shipped\s+\d{4}-\d{2}-\d{2}\s+as\s+PR\s*#(\d+)\b"` with `re.MULTILINE`. **The leading `^` is load-bearing** — without it, the pattern would match dependency cites such as `Depends on chore_X (**shipped 2026-05-21 as PR #171**)` or table-row cells `| dependency | **shipped 2026-05-21 as PR #171** |`. The actual precedent at [`docs/00_overview/implemented_features/2026_05_21_chore_precommit_node_path_resolution/idea.md:127`](../../../00_overview/implemented_features/2026_05_21_chore_precommit_node_path_resolution/idea.md) appears at column 0, supporting the line-anchor.
  - The first pattern to match **MUST** win and return its captured `int(PR#)`.
  - If no pattern matches, the function **MUST** fall through to FR-3 (frontmatter fallback), then current priority 4 (last-resort).

### FR-3: `**PR:**` frontmatter fallback (priority 3.6) — bounded metadata block

- **Requirement:**
  - The system **MUST** try one additional regex against the bounded metadata block of `idea` after the three strict patterns and before priority 4.
  - **Metadata block definition (precise):** the substring of `idea` extracted by the following algorithm:
    1. Start at the beginning of `idea`.
    2. Scan forward through lines. Include the title line (`# ...`), blank lines, and lines matching the idea-template's metadata-key pattern `^\*\*[A-Z][a-zA-Z ]+:\*\*` (e.g., `**Date:**`, `**Status:**`, `**Priority:**`, `**Origin:**`, `**Depends on:**`, and the new `**PR:**` field this chore introduces).
    3. Stop at the first line that is either (a) a `^## ` heading, OR (b) a non-blank line that does NOT match the metadata-key pattern. The metadata block is everything BEFORE that stop line.
    4. **Maximum window:** if no stop line is found within the first 30 lines, cap the metadata block at line 30 as a safety bound. This handles malformed or headingless ideas without accidentally treating an entire long narrative document as metadata. (Verified: the longest idea-template-conformant frontmatter in the current corpus is 7 lines; 30 is a comfortable ceiling.)
  - The pattern within the bounded metadata block is `r"^\*\*PR:\*\*\s+#(\d+)\b"` with `re.MULTILINE`. The trailing `\b` prevents partial-token matches.
  - **Frontmatter-only intent:** A `**PR:**` reference in a body section (e.g., inside `## Related` or `## Why deferred`) **MUST NOT** match because the body section is outside the bounded metadata block. The 30-line cap protects headingless edge cases where step 3's stop condition might fail to trigger. AC-13 and AC-17 lock this behavior.
  - This provides an explicit escape hatch for legacy ideas that don't fit FR-2's natural patterns. The convention is documented in `architecture.md` so future opportunistic backfills know where to place it (under the existing `**Date:** / **Status:** / **Priority:** / **Origin:** / **Depends on:**` metadata cluster).
  - **No existing legacy folder is backfilled** with this frontmatter in scope of this chore — see §3 Out of scope.

### FR-4: `_load_implemented` reads `idea.md` and threads it through

- **Requirement:**
  - The system **MUST** update `_load_implemented` at `scripts/build_mvp1_dashboard.py:661-690` to read `idea = _read(folder_path / "idea.md")` (using the existing `_read` helper, which returns `""` for missing files) and pass it as the 4th argument to `_extract_pr_number`.
  - The system **MUST** apply the same update at the `_load_planned` call site (line 646 area), where the planned-feature loader reads idea content as the primary artifact. Symmetry is the goal — both call sites pass idea-body content through the new parameter.

### FR-5: Line-anchoring is what prevents false-positive matches in idea extraction

- **Requirement:**
  - All FR-2 and FR-3 patterns **MUST** be line-anchored (`^…` with `re.MULTILINE`). The line-anchor is what prevents false-positive matches from dependency cites (e.g., narrative `Depends on chore_X (**shipped 2026-05-21 as PR #171**)`), from table-row cells (whose lines start with `|`, never `**`), and from headings (which start with `#`, not `**`).
  - The existing `_strip_dependency_table_rows` call in current priority 3 (fuzzy match) **MUST** remain unchanged — it operates on `pipe + plan + spec` only, not on `idea`. The new idea-aware code path **MUST NOT** add a stripping step against the idea text because (a) the line-anchoring requirement above already prevents the failure modes stripping would address, and (b) adding the stripping step would surface a maintenance-tax footgun: any future regex change that loses the line-anchor would silently introduce false positives unless someone remembered to add stripping. Anchoring + no stripping is the simpler, more verifiable contract.
  - Equivalently: FR-2 / FR-3 patterns are designed so the `^…` anchor is the single load-bearing safeguard against false positives. AC-4 + AC-13 + AC-14 lock the safeguard via negative tests.

---

## 8) API and data contract baseline

N/A across all subsections — this chore touches no API surface, no error codes, no enumerated value contracts.

## 9) Data model and state transitions

N/A — no schema changes, no new tables, no migrations, no state machines touched.

## 10) Security, privacy, and compliance

- Threats: none. The regex operates on local filesystem content already trusted by the regen script. No new attack surface.
- Controls: no new I/O, no subprocess, no network. The function remains pure.
- Secrets/key handling: N/A.
- Auditability: N/A.
- Data retention/deletion/export impact: N/A.

## 11) UX flows and edge cases

N/A — no UI changes.

## 12) Given/When/Then acceptance criteria

### AC-1: `**Status:** **Shipped** as PR #N` pattern extracts correctly

- **Given** an idea body whose first non-blank line after the title is `**Status:** **Shipped** as PR [#124](https://github.com/SoundMindsAI/relyloop/pull/124)` (precedent: `feat_contextual_help_mvp2`; the literal `(squash-merged 2026-05-15…)` trailer is omitted from this AC body because it trips the dashboard regen's pre-existing priority-3 fuzzy `PR #N…merged` regex — see tangential observation `chore_dashboard_regen_quoted_pr_false_positive` for the underlying issue. The strict Pattern A regex anchors at the `**Status:**` line, so the trailing prose doesn't affect AC-1's pass/fail.)
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `124`.

### AC-2: `**Status:** **Implemented — PR #N**` pattern extracts correctly

- **Given** an idea body whose first non-blank line after the title is `**Status:** **Implemented — PR #161 (squash `0879df2`)**` (precedent: `chore_create_study_modal_e2e_stability`; trailing `merged YYYY-MM-DD` prose intentionally omitted — see AC-1 note)
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `161`.

### AC-3: `**shipped YYYY-MM-DD as PR #N**` pattern extracts correctly

- **Given** an idea body containing `**shipped 2026-05-21 as PR #171** (squash `861e354`)`
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `171`.

### AC-4: Dependency-only PR mention does NOT produce a false positive

- **Given** an idea body containing only `**Depends on:** [`infra_foundation`](../2026_05_09_infra_foundation/) — merged via PR #4 (2026-05-09).` (matching `infra_frontend_stack_refresh`'s actual idea content) and no own-PR strict pattern
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `None`. PR #4 is the dependency's PR, not this feature's.

### AC-5: `**PR:**` frontmatter fallback extracts correctly

- **Given** an idea body starting with:
  ```
  # Feature title
  
  **Date:** 2026-05-23
  **PR:** #42
  ```
  and no strict-pattern match
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `42`.

### AC-6: Strict pattern wins over `**PR:**` frontmatter

- **Given** an idea body containing BOTH `**Status:** **Shipped** as PR #100` AND `**PR:** #999`
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `100` (priority 3.5 strict pattern beats priority 3.6 frontmatter).

### AC-7: Pipeline_status.md `## Implement` PR# wins over idea-body strict pattern

- **Given** `pipe` contains a `## Implement` section. Its body lists a PR number (e.g., `200`) and a squash/merge trailer. AND `idea` contains the strict `**Status:** **Shipped**` line for a different PR number (e.g., `100`)
- **When** `_extract_pr_number(pipe=<pipe>, plan="", spec="", idea=<idea>)` is called
- **Then** it returns `200` (priority 1 beats priority 3.5; the canonical artifact wins over historical idea).

### AC-8: Plan `**Status:**` PR# wins over idea-body strict pattern

- **Given** `plan` contains `**Status:** Complete (PR #300, squash …)` AND `idea` contains `**Status:** **Shipped** as PR #100`
- **When** `_extract_pr_number(pipe="", plan=<plan>, spec="", idea=<idea>)` is called
- **Then** it returns `300` (priority 2 beats priority 3.5).

### AC-9: Fuzzy `merged`-context still wins over idea-body strict pattern when present in spec/plan/pipe

- **Given** `spec` contains a narrative-form merge sentence in a `merged on YYYY-MM-DD via PR #N` shape (e.g., N=150). AND `idea` contains the strict `**Status:** **Shipped**` line for a different PR number (e.g., 100)
- **When** `_extract_pr_number(pipe="", plan="", spec=<spec>, idea=<idea>)` is called
- **Then** it returns `150` (priority 3 beats priority 3.5).

### AC-10: Last-resort fallback (priority 4) only fires when neither idea nor pipe/plan/spec matches

- **Given** `spec` contains `PR #500` in narrative form (not adjacent to merge-context keywords) AND `idea` has no own-PR pattern
- **When** `_extract_pr_number(pipe="", plan="", spec=<spec>, idea=<idea>)` is called
- **Then** it returns `500` (priority 4 last-resort).

### AC-11: Backward compat — existing call without `idea` argument works

- **Given** legacy or external code calling `_extract_pr_number(pipe="...", plan="...", spec="...")` without the new keyword
- **When** invoked
- **Then** it returns the same value it would have returned before this chore (default `idea=""` means no new extraction paths activate).

### AC-12: `_load_implemented` end-to-end on a legacy idea-only folder

- **Given** an `implemented_features/<date>_<slug>/` folder containing only `idea.md` with body `**Status:** **Implemented — PR #161**`
- **When** `_load_implemented(folder_path)` is called
- **Then** the returned `Feature` has `pr_number == 161` (instead of the previous `None`).

### AC-13: `**PR:**` in a body section does NOT match (frontmatter-only)

- **Given** an idea body where `**PR:** #999` appears inside a body section (e.g., after a `## Related` heading) and no other own-PR pattern is present
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `None` (or falls through to the priority-4 last-resort if a `#N` exists elsewhere; the key assertion is that the body-section `**PR:**` does NOT produce a match at priority 3.6).

### AC-14: Dependency cite containing exact bold shipped phrase does NOT match (line-anchor lock)

- **Given** an idea body containing `Depends on chore_X (**shipped 2026-05-21 as PR #171**) — see prior work.` in narrative form (not at line-start)
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `None` (the line-anchor in Pattern C prevents the match because the substring does NOT start at column 0; this is the central correctness criterion the chore must protect).

### AC-15: Pattern A rejects partial-token matches

- **Given** an idea body containing `**Status:** **Shipped** as PR [#124abc...` (a malformed token without a clear word boundary) OR `**Status:** **Shipped** as PR [#124` (a partial bracket without closing) on a line by itself
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `None`. The Pattern A alternation requires either a fully-bracketed link `[#N](url)`, a bare bracket pair `[#N]`, or `#N\b` — partial forms do not match.

### AC-16: Pattern A handles both linked and unlinked status forms

- **Given** an idea body containing `**Status:** **Shipped** as PR [#124](https://github.com/SoundMindsAI/relyloop/pull/124)`
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `124`. The fully-bracketed alternation captures correctly.

### AC-17: Headingless idea with body-section `**PR:**` does NOT match (30-line cap)

- **Given** an idea body with no `## ` heading at all, where the metadata cluster ends at line 8 (followed by blank lines and free-form narrative), and `**PR:** #99` appears on line 50 within that narrative
- **When** `_extract_pr_number(pipe="", plan="", spec="", idea=<that body>)` is called
- **Then** it returns `None`. The metadata block stops at line 8 (first non-metadata non-blank line after the cluster), OR at the 30-line cap, whichever fires first; the line-50 `**PR:**` is outside the bounded scope. This complements AC-13 (which uses a `## ` heading as the stop) by locking the cap-based stop for headingless ideas.

## 13) Non-functional requirements

- **Performance:** negligible — the new regex passes run only when none of priorities 1–3 match, AND only on idea-body content (typically <10 KB per file). Total regen runtime impact is well under measurement noise.
- **Reliability:** unchanged. The function remains pure; failure modes are confined to regex returning `None` (current behavior for missing patterns).
- **Operability:** no new metrics, logs, or alerts. The dashboard regen's existing console output (`mvp1: N features … wrote …`) is unchanged.
- **Accessibility/usability:** N/A.

## 14) Test strategy requirements (spec-level)

- **Unit tests:** new file `backend/tests/unit/scripts/test_dashboard_pr_extraction.py`. **All 17 ACs MUST have at least one test case.** Minimum case inventory:
  - AC-1 / AC-2 / AC-3: positive extraction for each strict pattern (3 cases)
  - AC-4: dependency-only `merged via PR #N` returns `None` (no false positive — the foundational anti-regression)
  - AC-5: `**PR:**` frontmatter at the top of the metadata block extracts correctly
  - AC-6: strict pattern (3.5) wins over `**PR:**` (3.6) when both present
  - AC-7: pipeline_status.md `## Implement` PR# (priority 1) wins over idea-body strict pattern
  - AC-8: plan `**Status:**` PR# (priority 2) wins over idea-body strict pattern
  - AC-9: fuzzy `merged`-context in spec (priority 3) wins over idea-body strict pattern
  - AC-10: last-resort fallback (priority 4) only fires when neither idea nor pipe/plan/spec matches
  - AC-11: backward-compat 3-arg call works (regression lock)
  - AC-12: `_load_implemented` end-to-end with tmp folder containing only `idea.md`
  - **AC-13** (Medium-severity false-positive): `**PR:**` in a body section does NOT match — frontmatter-only intent
  - **AC-14** (High-severity false-positive): dependency cite containing exact bold shipped phrase does NOT match (line-anchor lock — the central correctness criterion)
  - AC-15: Pattern A rejects partial-token forms (malformed `[#N`, `#Nabc`)
  - AC-16: Pattern A handles fully-bracketed markdown link form `[#N](url)`
  - **AC-17** (Medium-severity false-positive): headingless idea with body-section `**PR:**` at line 50 — bounded metadata-block + 30-line cap prevents the match
  - One additional case verifying Pattern A and Pattern B can NOT both match the same line (mutual exclusion is implicit in their distinct `**Status:** **Shipped**` vs `**Status:** **Implemented`** prefixes; documenting prevents future ambiguity)
- **Integration tests:** N/A — the regen script doesn't touch the database or any external service.
- **Contract tests:** N/A.
- **E2E tests:** N/A.
- **Verification gates the implementer must hit:**
  - `make backend-fmt` (ruff format) — green
  - `make backend-lint` (ruff check) — green
  - `make backend-typecheck` (mypy --strict) — green; `_extract_pr_number`'s signature change must remain `mypy --strict` clean
  - `make test-unit` — green; new tests pass + no regression in existing tests
  - **Empirical verification:** Run `make dashboard` and compare the regenerated `MVP1_DASHBOARD.md` shipped table against `HEAD~1` with two structural assertions (NOT a textual diff grep — `git diff` emits old/new on separate `-`/`+` lines so a single-line regex would miss the regression pattern):
    1. **Forward gain (expected):** 5–8 rows that previously showed `Complete` now show `[PR #N](url) merged YYYY-MM-DD` (the ~5–8 legacy idea-only folders that carry strict patterns). Document the count in the PR body, listed by feature folder.
    2. **No regression (mandatory):** Zero rows transition from `[PR #N](...)` to `[PR #M](...)` with a different PR number. The new code path is below the canonical priority-1–3 cascade, so an existing PR-linked shipped row should be unaffected. If any row's PR number changes, the change is a bug AND the spec's priority cascade is wrong — investigate before merge.
    3. **Verification method (deterministic):** a small ad-hoc Python script (run during PR-prep, not committed as a permanent test) parses the shipped table from `git show HEAD~1:docs/00_overview/MVP1_DASHBOARD.md` and from the current `docs/00_overview/MVP1_DASHBOARD.md`, keys rows by feature folder slug, extracts the PR-number column, and asserts: (a) `{folder: pr#}` map's pre-existing entries are unchanged; (b) the new entries are listed in the PR body. The script's transcript goes in the PR body. The grep-based pattern (`diff … | grep -E 'PR #[0-9]+.*PR #[0-9]+'`) is explicitly **not** sufficient — unified diff format would mostly emit separate `-` / `+` lines that the single-line regex would not catch.

## 15) Documentation update requirements

- `docs/01_architecture/`: minor — add a one-paragraph subsection to the dashboard-regen documentation (currently at `architecture.md` per CLAUDE.md "Compressed Context First") describing the new `**PR:**` frontmatter convention and the strict-pattern extraction. This is the only externally-visible convention change.
- `docs/02_product/`: none beyond finalization (idea + spec + plan stay in planned-features until finalization moves them).
- `docs/03_runbooks/`: none.
- `docs/04_security/`: none.
- `docs/05_quality/`: none.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** N/A — build-script change with no runtime user impact.
- **Migration/backfill expectations:** N/A — no schema. Backfilling idea-body `**PR:**` frontmatter on legacy folders is explicit out-of-scope (see §3).
- **Operational readiness gates:** N/A.
- **Release gate:** PR-level — green CI + Gemini review + final GPT-5.5 review.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (signature change) | AC-11 | Story 1.1 (signature + skeleton) | `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` | architecture.md dashboard subsection |
| FR-2 (strict patterns + line-anchor) | AC-1, AC-2, AC-3, AC-4, AC-6, AC-7, AC-8, AC-9, AC-14, AC-15, AC-16 | Story 1.1 (patterns + priority insertion) | same file | same |
| FR-3 (frontmatter fallback + bounded metadata block) | AC-5, AC-6, AC-13, AC-17 | Story 1.1 (frontmatter pattern + metadata-block algorithm with 30-line cap) | same file | same |
| FR-4 (call-site updates) | AC-12 | Story 1.2 (`_load_implemented` + `_load_planned` updates) | same file | none |
| FR-5 (line-anchoring as safeguard, no stripping) | AC-4, AC-13, AC-14 | Story 1.1 (no extra code path; the line-anchor in FR-2/3 IS the safeguard) | covered by AC-4/13/14 | none |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-17) pass in CI via `make test-unit`.
- [ ] `make backend-fmt` / `make backend-lint` / `make backend-typecheck` / `make test-unit` are all green locally on the feature branch before push.
- [ ] CI workflow (`.github/workflows/pr.yml`) is green on the PR.
- [ ] Empirical verification recorded in the PR body: `make dashboard` produces a regen with 5–8 newly-resolved PR rows in the shipped table (with the count + a representative diff snippet).
- [ ] Gemini Code Assist review comments adjudicated.
- [ ] Final GPT-5.5 review (per CLAUDE.md cross-model review policy) is clean or has documented Accept/Reject adjudications.
- [ ] No open questions remain in §19.
- [ ] `architecture.md` dashboard-regen subsection mentions the new `**PR:**` frontmatter convention.
- [ ] Finalization PR moves `planned_features/chore_dashboard_pr_extraction_from_idea/` to `implemented_features/<YYYY_MM_DD>_chore_dashboard_pr_extraction_from_idea/` and updates `state.md`.

## 19) Open questions and decision log

### Open questions

None.

### Decision log

- **2026-05-23 — Locked Option (c): strict patterns + optional `**PR:**` frontmatter fallback** (from preflight §"Open questions" §1). Strict patterns ship now; `**PR:**` frontmatter is a documented convention for future opportunistic backfills. Rejected (a) strict-only — leaves a viable escape hatch unimplemented; rejected (b) frontmatter-only — would require backfilling ~50 legacy folders to recover the strict-pattern wins, ballooning scope.
- **2026-05-23 — Locked no-backfill** (from preflight §"Open questions" §2). This chore is about extraction logic; backfill of specific legacy folders is separate scope and captured as a future-work observation.
- **2026-05-23 — Locked priority 3.5/3.6 slotting** (from preflight §"Open questions" §3). Strict idea patterns slot between current 3 (fuzzy `merged`-context) and current 4 (last-resort). Frontmatter fallback slots immediately after at 3.6. Rationale: canonical artifacts (pipeline_status.md, plan `**Status:**`, fuzzy `merged`-context in pipe/plan/spec) keep their authority order; idea body is consulted only when none of those provided an answer.
- **2026-05-23 — Default `idea: str = ""` parameter** for backward compat. Existing call sites that don't pass `idea` continue to work; both `_load_implemented` and `_load_planned` are updated in the same PR.
- **2026-05-23 — New test file `test_dashboard_pr_extraction.py` rather than appending to `test_dashboard_expand_transitive_deps.py`.** Different unit-of-behavior (PR# extraction vs. dependency-graph expansion); separate file keeps the assertions discoverable and makes future targeted runs (`pytest test_dashboard_pr_extraction.py`) cheap.
- **2026-05-23 — `_strip_dependency_table_rows` not applied to idea content.** All FR-2 and FR-3 patterns are line-anchored (`^…` with `re.MULTILINE`). The line-anchor is the single load-bearing safeguard against false positives — dependency cites embedded mid-line (`Depends on chore_X (**shipped … as PR #N**)`), table-row cells (lines starting with `|`), and headings (lines starting with `#`) all fail to match. Adding a stripping step would be redundant and create a maintenance footgun (a future regex change that loses the anchor would silently introduce false positives unless stripping was preserved). Adopted after GPT-5.5 cycle-1 review surfaced the original Pattern C as unanchored.
- **2026-05-23 — GPT-5.5 cycle-1 review applied** — 7 findings (1 High / 4 Medium / 2 Low). All 6 actionable findings accepted and incorporated into FR-2 / FR-3 / FR-5 / §14 / §18 / decision log:
  - **High (A1):** Pattern C was unanchored → added `^…` line anchor + `\b` boundary. Locked in FR-2 with explicit "leading `^` is load-bearing" annotation.
  - **Medium (A2):** `**PR:**` was unbounded across the body → restricted to the metadata block (text before first `## ` heading). New AC-13 locks the body-section exclusion.
  - **Medium (A3):** FR-5's "stripping not needed" rationale was too broad → reframed around the line-anchor being the safeguard. AC-14 locks the dependency-cite-in-narrative case.
  - **Low (A4):** Pattern A allowed partial-token forms like `[#124abc` → tightened to balanced alternation `(?:\[#(\d+)\]\([^)]*\)|\[#(\d+)\]|#(\d+))\b` + `\b` boundary. New AC-15 and AC-16 lock partial rejection and the fully-bracketed link form.
  - **Medium (B1):** Test list omitted AC-8 through AC-11 → §14 now requires explicit cases for all 16 ACs.
  - **Medium (B2):** False-positive coverage was thin → added AC-13 (body-section `**PR:**` excluded) + AC-14 (dependency-cite-in-narrative excluded). Both are mandatory test cases per §14.
  - **Medium (B3):** Empirical verification only counted forward gain → added "no regression" assertion that no existing PR-linked row's PR# changes.
  - **Low (B4):** Multiple-strict-pattern + malformed-token edge cases → added AC-15 and the §14 "mutual exclusion" case.
  - **Low (B5):** Default-arg backward-compat claim was correct → no spec change; AC-11 already locks it.
- **2026-05-23 — GPT-5.5 cycle-2 review applied** — 4 findings (1 High / 3 Medium / 0 Low). All 4 accepted and incorporated:
  - **High (A1):** Pattern A's trailing `\b` after the alternation didn't fire for the `[#N]` and `[#N](url)` alternatives because `)` and `]` are non-word characters and `\b` requires a word↔non-word transition AT the boundary. The corrected regex now places `\b` immediately after each `\d+` capture inside the alternation (digit↔non-digit transition fires correctly for all three alternatives). AC-1 and AC-16 are the canaries — they would silently fail against the cycle-1 regex.
  - **Medium (A2):** §3 still carried the pre-patch regex snippets. Reframed §3 to reference FR-2 / FR-3 as the source of truth rather than duplicating the regexes (preventing future drift).
  - **Medium (B1):** FR-3's metadata-block "before first `## ` heading, or entire idea if no heading" rule weakened the frontmatter-only guarantee for headingless ideas. Replaced with a precise algorithm: contiguous metadata-key lines + 30-line cap. New AC-17 locks the cap-based stop.
  - **Medium (B2):** §14's `diff … | grep -E 'PR #[0-9]+.*PR #[0-9]+'` would not reliably detect PR-number changes because unified diffs emit `-` / `+` lines separately. Replaced with a deterministic structural-comparison script that keys rows by feature folder slug, extracts PR numbers, and asserts the pre-existing map is unchanged.
- **2026-05-23 — GPT-5.5 cycle-3 review applied** — 1 finding (0 High / 0 Medium / 1 Low). Low accepted:
  - **Low (B1):** AC count bookkeeping mismatch — §14 still said "All 16 ACs" + traceability §17 didn't map FR-3 to AC-17. Updated §14 to "All 17 ACs", added explicit AC-17 to the inventory list, and extended FR-3's traceability row.
  - Cycle 3 reports zero new High/Medium findings; convergence reached per Step 7 stop rule ("Stop when GPT-5.5 reports no new High-severity findings AND Opus has no unresolved accepted changes").
