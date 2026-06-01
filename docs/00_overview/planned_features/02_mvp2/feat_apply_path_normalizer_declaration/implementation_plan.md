# Implementation Plan — Apply-path-side normalizer declaration (Phase 3 of query-normalization tuning)

**Date:** 2026-06-01
**Status:** Draft — **DESIGN-AHEAD. Execution is GATED. Do NOT `/impl-execute` until both gates clear (see §0).**
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`feat_query_normalization_tuning/feature_spec.md`](../feat_query_normalization_tuning/feature_spec.md) §3 + §19 D-1 (Phase 1, the foundation); [`docs/01_architecture/apply-path.md`](../../../../01_architecture/apply-path.md)

---

## 0) EXECUTION GATE — read before any story

This plan is a **design-ahead artifact**. The stories below are fully specified, FR-traced, and cross-model reviewed, but **MUST NOT be executed** until BOTH gates hold (spec §0, §16, I-1):

- **G-1 — Phase 1 (`feat_query_normalization_tuning`) merged to `main`.** Stories 1–7 extend Phase-1-introduced symbols (`NORMALIZER_CHOICES`, `normalize()`, `_PR_BODY_NORMALIZER_SNIPPETS`, the reserved `query_normalizer` Categorical key, the "Operator-side requirement" PR-body section). Verified 2026-06-01: none exist in `backend/app/` yet — Phase 1 is in the Plan stage. Story 1 in particular assumes `backend/app/domain/study/normalizers.py` already exists (Phase 1 ships it).
- **G-2 — Operator-friction evidence materialized.** A cited friction artifact (GitHub issue / in-product feedback / adoption survey / design-partner escalation) showing Phase 1's prose hand-off is causing under-reproduced production gains.

**A `/pipeline status` / `/impl-execute` invocation on this plan before both gates clear should refuse and surface this section.** When G-1 clears, re-run a one-pass plan-accuracy audit (Phase 1's actual symbol names + the `ProposalDetail` schema may have shifted) before executing.

---

## 0a) Planning principles

- Spec traceability first: every story maps to FR IDs (§1).
- No migration: this feature adds zero tables/columns. Alembic head stays `0022_solr_engine_auth_check` (verified `ls migrations/versions/ | sort | tail -1`).
- No audit events: MVP2 has no `audit_log` (lands MVP3). Conditional MVP3 note in spec §6 — re-check at execution if MVP3 has shipped by G-2-clear time.
- Pure-domain manifest builder; all Git/file I/O confined to the `open_pr` worker.
- Back-compat by construction: the `EMIT_NORMALIZER_MANIFEST` gate defaults OFF.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (manifest builder, pure-domain) | Epic 1 / Story 1 | `build_normalizer_manifest` + normative v1 schema (spec §9 D-3-8) |
| FR-2 (manifest path + containment + basename guard) | Epic 2 / Story 2 | `_validate_manifest_path` mirrors `_validate_params_path` + `with_name` derivation |
| FR-3 (worker emit step, single commit) | Epic 2 / Story 2 + Story 3 | emit step + `_git_commit_files` multi-file helper; gate-conditioned |
| FR-4 (worker error handling) | Epic 2 / Story 2 | `_NormalizerManifestEmitError` → `NORMALIZER_MANIFEST_EMIT_FAILED` on `pr_open_error` |
| FR-5 (back-compat env gate) | Epic 2 / Story 3 | `Settings.emit_normalizer_manifest: bool = False` |
| FR-6 (PR-body section rewrite) | Epic 2 / Story 4 | gate-ON manifest wording + retained fallback snippet |
| FR-7 (proposal-detail manifest preview UI + server field) | Epic 3 / Story 5 | `normalizer_manifest_preview` server field (OQ-1 opt 1) + UI block + glossary |
| FR-8 (docs) | Epic 4 / Story 6 | `apply-path.md` extension + runbook + `CLAUDE.md` env var + parent-spec pointers |
| — (AC-13 real-backend E2E) | Epic 4 / Story 7 | extend Phase 1's `query-normalization.spec.ts` |

All 8 FRs covered. No deferred sub-phase (this feature IS Phase 3; not internally multi-phase — spec §3). No `phase<N>_idea.md` to create.

## 2) Delivery structure — Epic → Story → Tasks → DoD

### Conventions (project-specific)

```
- Domain layer (backend/app/domain/study/) is PURE — no DB, no async, no I/O. build_normalizer_manifest is a pure function.
- All Git/file I/O lives in backend/workers/git_pr.py (the open_pr worker), never in domain.
- Worker error strings ALWAYS pass through redact_token before landing on proposals.pr_open_error (existing pattern, git_pr.py:220).
- Settings via pydantic-settings; bool config via `Field(default=...)` (settings.py:302 pattern); non-secret env var (Absolute Rule #2 — manifest gate is NON-secret config like relyloop_allow_private_clusters).
- Manual proposals are discriminated by `study_id IS NULL` (git_pr.py:37,132 + ProposalDetail.study_id: str | None at schemas.py).
- Frontend enum/option discipline: any wire value sourced from @/lib/enums.ts with a // Values must match backend/... comment. NORMALIZER_VALUES is Phase 1's deliverable in ui/src/lib/enums.ts.
- Glossary keys are the source of truth for tooltip copy (no inline strings); length/no-jargon lint at ui/src/__tests__/lib/glossary.test.ts.
```

### AI Agent Execution Protocol

0. **Re-verify G-1 + G-2 first** (this plan is gated). Then read `architecture.md` + `state.md`.
1. Read story scope + DoD.
2. Backend first: domain (Story 1) → worker (Story 2) → settings (Story 3) → PR-body (Story 4) → API field (Story 5 backend half).
3. Run backend tests (unit + integration + contract for touched surface).
4. Frontend (Story 5 UI half).
5. E2E (Story 7).
6. Docs (Story 6) in the same PR.
7. No migration round-trip needed (no schema change) — assert Alembic head unchanged at `0022`.
8. Attach evidence in PR.
9. After final story, update `state.md` + `architecture.md` (§4).

---

## Epic 1 — Pure-domain manifest builder

### Story 1 — `build_normalizer_manifest` + normative v1 schema

**Outcome:** A deterministic, pure-domain function turns a `NORMALIZER_CHOICES` value into the locked v1 manifest YAML (spec §9 D-3-8). Single source of truth alongside Phase 1's `normalize()` + snippets.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/domain/study/test_normalizer_manifest.py` | Unit tests: shape per choice, determinism/byte-stability, strict no-extra-keys, `none` empty-steps, `ValueError` on out-of-allowlist (AC-1). |
| `backend/tests/unit/domain/study/test_normalizer_manifest_runtime_parity.py` | I-2: manifest steps ≡ runtime `normalize` behavior per choice (AC-2). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/normalizers.py` (**Phase 1 deliverable — exists post-G-1**) | Add `build_normalizer_manifest(choice: str) -> str` + the step-vocabulary tuple (D-3-2 branch: reuse Phase 2's `NormalizerStep` if `feat_query_normalizer_typed_pipeline` has shipped, else a Phase-3-local frozen `_MANIFEST_STEPS_BY_CHOICE` map). Add `MANIFEST_VERSION: Final[int] = 1`. |

> **D-3-2 execution branch:** at execution time, `grep -rn "class NormalizerStep" backend/app/domain/study/search_space.py`. If present (Phase 2 shipped), use those enum values for the `steps[*].id`. Else define a Phase-3-local frozen vocabulary `("lowercase", "trim", "expand_contractions_en")` covering the four bundles. The manifest object shape is identical either way.

**Key interfaces**

```python
# backend/app/domain/study/normalizers.py  (extends the Phase 1 module)
MANIFEST_VERSION: Final[int] = 1

def build_normalizer_manifest(choice: str) -> str:
    """Return the deterministic v1 manifest YAML for a NORMALIZER_CHOICES value.

    Pure: no I/O. Raises ValueError('unknown normalizer: <choice>') when
    choice not in NORMALIZER_CHOICES. Output conforms to the strict v1
    schema in feature_spec.md §9 (top-level keys: version, choice, steps,
    reference_implementation; no extra keys; steps=[] for 'none').
    """
    ...
```

**Tasks**
1. Add `MANIFEST_VERSION` + the step-vocabulary source (D-3-2 branch).
2. Implement `build_normalizer_manifest` emitting the §9 normative shape; serialize deterministically (stable key order). Use `PyYAML` if in the dependency closure (`grep -n "pyyaml\|PyYAML" pyproject.toml uv.lock`), else a small stdlib deterministic emitter — do NOT add a new dep without operator authorization (spec §5).
3. `reference_implementation.source = f"relyloop:{choice}"` mapping to Phase 1's `_PR_BODY_NORMALIZER_SNIPPETS[choice]`.
4. Unit tests: per-choice shape (parse + strict-key assert against §9 examples), determinism (two calls byte-equal), `none` empty steps, `ValueError` on `"stem"`.
5. Runtime-parity test: for each `NORMALIZER_CHOICES` value, assert the manifest's declared steps correspond to what `normalize(query_text, choice)` applies (e.g., `lowercase+trim` manifest declares lowercase→trim; the runtime lowercases then trims).

**Definition of Done**
- `build_normalizer_manifest(c)` returns the exact §9 v1 shape for every `c ∈ NORMALIZER_CHOICES`; `ValueError` otherwise.
- `test_normalizer_manifest.py` covers AC-1 (shape, determinism, strictness, none-branch, error).
- `test_normalizer_manifest_runtime_parity.py` covers AC-2 / I-2.
- `make test-unit` green; `make lint`/`make typecheck` green; module stays import-pure (no DB/httpx/openai import added).

**Epic 1 gate:** the manifest builder exists, is pure, and is locked to the §9 schema with parity to the runtime normalizer.

---

## Epic 2 — Apply-path worker emission

### Story 2 — Manifest path helper, emit step, single-commit helper, error handling

**Outcome:** The `open_pr` worker writes `{template_name}.query_normalizer.yaml` next to `params.json` and commits both in one commit, gated on FR-5; failures funnel into the existing `pr_open_error` path.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/workers/test_open_pr_normalizer_manifest.py` | Integration: gate ON → both files in one commit; gate OFF → params-only; containment/separator violation → pending + `pr_open_error`, nothing pushed; invalid-but-present value → params-only + no manifest claim (AC-3, AC-4, AC-6, AC-12 emit-site half, FR-3 invalid-value reconciliation). |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/git_pr.py` | (1) Add `_validate_manifest_path(clone_dir, config_path, template_name) -> Path`: basename guard on `template_name` (raise `InvalidConfigPathError` on separators / `.`/`..`), derive via `params_path.with_name(f"{template_name}.query_normalizer.yaml")`, re-assert `relative_to(clone_root)`. (2) Add `_git_commit_files(clone_dir, file_paths: list[Path], message, token)` — `git add` all paths then ONE commit (generalizes the existing single-file `_git_commit_file` at L1106). (3) Add `_NormalizerManifestEmitError(ValueError)` inline (next to `_ParamNotInTemplateError` at L633). (4) In the `open_pr` worker body, after `_apply_config_diff` (Step 10) and before the commit (Step 12): when study-backed (`study_id is not None`) AND gate ON AND `config_diff` has a valid `query_normalizer`, build + write the manifest and stage it with `params.json` via `_git_commit_files`; map failures to `NORMALIZER_MANIFEST_EMIT_FAILED` via `_safe_set_proposal_pr_open_error` (existing helper, L212). Replace the single-file `_git_commit_file(clone_dir, params_path, ...)` params commit with `_git_commit_files(clone_dir, [params_path, *manifest_paths], ...)` (manifest list empty when not emitting). The chart PNG stays its own separate commit (unchanged). |

**Endpoints:** none (worker-only). `POST /api/v1/proposals/{id}/open_pr` triggers it; behavior extends, contract unchanged.

**Key interfaces**

```python
# backend/workers/git_pr.py
def _validate_manifest_path(clone_dir: Path, config_path: str, template_name: str) -> Path: ...
def _git_commit_files(clone_dir: Path, file_paths: list[Path], message: str, token: str) -> None: ...

class _NormalizerManifestEmitError(ValueError):
    """Manifest path/build/write failure during open_pr (FR-4)."""
```

**Tasks**
1. Implement `_validate_manifest_path` with the basename guard + `with_name` derivation + containment re-check.
2. Implement `_git_commit_files` (stage list, single commit) — model on `_git_commit_file` (L1106).
3. Add `_NormalizerManifestEmitError`.
4. Insert the gate-conditioned emit step; read the gate from `get_settings().emit_normalizer_manifest` (Story 3 adds the field).
5. Invalid-value defense-in-depth: if `config_diff["query_normalizer"]["to"] not in NORMALIZER_CHOICES`, log a redacted warning, SKIP the manifest, commit params alone, set `manifest_emitted=False`, and pass that to the PR-body renderer (Story 4) so it renders no manifest claim (FR-3 I-3 exemption). Compute `manifest_emitted = gate_on and qn_present and qn_choice in NORMALIZER_CHOICES` once and reuse it for both the emit decision and the renderer kwarg.
6. Map manifest build/path/write exceptions → `_safe_set_proposal_pr_open_error(... "normalizer manifest emit failed: ...")`; abort before commit/push (I-3 atomicity).
7. Integration tests (above) using the existing local-git-fixture pattern in `backend/tests/integration/workers/test_open_pr_*.py`.

**Definition of Done**
- Gate ON + valid normalizer → clone has both files; pushed branch has ONE new commit touching both (assert via `git log --name-only`).
- Gate OFF → params-only; byte-identical to today.
- `_validate_manifest_path` rejects separator-bearing `template_name` and clone-escaping paths with `InvalidConfigPathError`.
- Manifest-emit failure → proposal stays `pending`, `pr_open_error` carries the redacted `NORMALIZER_MANIFEST_EMIT_FAILED` string, nothing pushed (I-3).
- Invalid-but-present value → params-only commit, no manifest, no PR manifest claim (FR-3 exemption; AC asserted jointly with Story 4).
- `make test-integration` (targeted) green; I-4 grep (`build_normalizer_manifest`/`query_normalizer.yaml` writers) shows only the worker + domain builder.

### Story 3 — Back-compat env gate

**Outcome:** `EMIT_NORMALIZER_MANIFEST` (default OFF) controls manifest emission; existing repos unaffected by default.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | Add `emit_normalizer_manifest: bool = Field(default=False, ...)` (non-secret, mirrors `relyloop_allow_private_clusters` at L302). Read via `get_settings()`. |
| `backend/tests/unit/core/test_settings.py` (or the existing settings test) | Assert default `False`; assert `EMIT_NORMALIZER_MANIFEST=true` env resolves to `True`. |

**Key interfaces**

```python
# backend/app/core/settings.py  (inside Settings)
emit_normalizer_manifest: bool = Field(
    default=False,
    description="When True, the open_pr worker emits a {template}.query_normalizer.yaml "
    "manifest alongside params.json (feat_apply_path_normalizer_declaration). Default "
    "False for back-compat — existing config repos consuming params.json only are "
    "unaffected until the operator opts in once their CI can consume the manifest.",
)
```

**Tasks**
1. Add the field; confirm it's read where Story 2's emit step gates.
2. Settings unit test for default + env override.

**Definition of Done**
- `get_settings().emit_normalizer_manifest` defaults `False`; `EMIT_NORMALIZER_MANIFEST=true` → `True`.
- Story 2's emit step honors it (covered by Story 2's gate-OFF integration case, AC-4).
- `make test-unit` green.

### Story 4 — PR-body "Operator-side requirement" section rewrite

**Outcome:** When gate ON, the PR body instructs CI-driven manifest consumption (naming the manifest file) and retains Phase 1's Python snippet as a labeled fallback; gate OFF keeps Phase 1 wording.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/workers/test_git_pr_body_manifest.py` | `_render_pr_body_study_backed` over {`manifest_emitted=True` + non-none → manifest wording + fallback snippet; `manifest_emitted=True` + none → no-op statement; `manifest_emitted=False` → Phase 1 wording, no manifest ref; **gate ON but out-of-allowlist choice → worker passes `manifest_emitted=False` → body has NO manifest filename/reference** (Finding-3 / FR-3 defense path); key absent → no section}. Covers AC-7, AC-8, AC-9, AC-5 (PR-body half). |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/git_pr.py` (`_render_pr_body_study_backed`, L540) | Rewrite the Phase-1 "Operator-side requirement" branch: `manifest_emitted=True` → name `{template_name}.query_normalizer.yaml`, state the "CI consumes it; no copy required" contract, retain the Phase 1 snippet under a "Fallback (if your CI cannot yet consume the manifest)" sub-heading; `manifest_emitted=False` → Phase 1 prose+snippet verbatim (NO manifest reference); `none` choice → no-op statement (both branches); key absent → no section. |

> **Implementation note (revised per GPT-5.5 plan-review Finding-3):** `_render_pr_body_study_backed` currently takes keyword args (`proposal`, `study`, `digest`, `config_diff`, `chart_md`, `base_url`, `confidence`). Add `manifest_emitted: bool = False` and `template_name: str`. **Critically, the worker MUST pass `manifest_emitted` = "did we ACTUALLY emit a manifest this run", NOT the raw `emit_normalizer_manifest` gate value.** The worker computes it AFTER the choice-validity decision: `manifest_emitted = gate_on AND query_normalizer_present AND choice in NORMALIZER_CHOICES`. This guarantees the FR-3 defense-in-depth path (gate ON but out-of-allowlist choice → manifest skipped) renders the body WITHOUT a manifest claim, because `manifest_emitted` is `False` even though the gate is `True`. Threading the raw gate would falsely claim a manifest when an invalid value caused a skip. Keeping it a passed-in bool (not a settings read inside the renderer) also keeps the function unit-testable without monkeypatching settings. |

**Tasks**
1. Add `manifest_emitted: bool = False` + `template_name: str` kwargs to `_render_pr_body_study_backed`; the worker computes `manifest_emitted` (gate-ON AND valid-choice AND present — NOT the raw gate; Finding-3) at the same point it decides to write the manifest (Story 2) and threads it + the template name in.
2. Rewrite the section per FR-6's branches keyed on `manifest_emitted` (not the raw gate).
3. Unit tests covering AC-5/7/8/9 + the gate-ON+invalid-value→no-claim case.

**Definition of Done**
- Gate ON + non-none → body names the manifest file + retains fallback snippet (AC-7).
- Gate OFF → Phase 1 wording, no manifest reference (AC-8).
- `none` → no-op statement (AC-9).
- Key absent → no section (AC-5 / AC-6 from Phase 1 preserved).
- `make test-unit` green.

**Epic 2 gate:** the worker emits the manifest in one commit when the gate is ON, fails safely otherwise, and the PR body matches the gate state across all four branches.

---

## Epic 3 — Proposal-detail manifest preview (UI + server field)

### Story 5 — `normalizer_manifest_preview` server field + manifest-preview UI block

**Outcome:** The proposal-detail page shows a read-only manifest preview (target filename + content) for study-backed proposals carrying `query_normalizer`; the manifest string is server-rendered (OQ-1 option 1) so it can never drift from the backend builder.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/proposals/normalizer-manifest-panel.tsx` | Read-only preview block: target filename + `normalizer_manifest_preview` content + glossary tooltip. |
| `ui/src/__tests__/components/proposals/normalizer-manifest-panel.test.tsx` | Renders when study-backed + key present + non-null preview; hidden when absent; **hidden for a MANUAL proposal (`study_id: null`) carrying BOTH a stray `config_diff.query_normalizer` AND a non-null `normalizer_manifest_preview`** (defense-in-depth client guard, Finding-2 / I-5); gate-agnostic copy; glossary-sourced. Covers AC-10, AC-11. |
| `backend/tests/contract/test_proposals_normalizer_manifest_preview_contract.py` | `GET /api/v1/proposals/{id}` returns exact `build_normalizer_manifest(...)` for study-backed+valid; `null` for {absent, out-of-allowlist, manual w/ stray key}; field present as additive nullable. Covers AC-11b + cycle-2 Finding-1 source guard. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` (`ProposalDetail`, L~1298) | Add `normalizer_manifest_preview: str | None = None` after `config_diff`. Additive nullable — no breaking change. |
| `backend/app/api/v1/proposals.py` (`_assemble_proposal_detail`, L112; built at L177) | Populate `normalizer_manifest_preview`: `build_normalizer_manifest(config_diff["query_normalizer"]["to"])` ONLY when `proposal.study_id is not None` (study-backed) AND `config_diff` has a valid `query_normalizer` choice; else `None`. Guard with a try/except around the builder mapping an unexpected `ValueError` to `None` (defense-in-depth; never 500). |
| `ui/src/app/proposals/[id]/page.tsx` | Render `<NormalizerManifestPanel>` below `<ConfigDiffPanel>` when `proposal.normalizer_manifest_preview` is non-null (which already encodes the study-backed + valid-key guard server-side). |
| `ui/src/lib/glossary.ts` | Add `proposal.normalizer_manifest` (gate-agnostic copy per spec §11) with a `// Source-of-truth` note. |
| `ui/src/lib/types.ts` (GENERATED from backend OpenAPI) | Regenerate so the `ProposalDetail` TS type picks up `normalizer_manifest_preview: string | null` (Finding-5). This is a generated file — run the project's OpenAPI type-gen step (verify the command at execution; e.g., `pnpm gen:types` or equivalent), do NOT hand-edit. If the frontend `ProposalDetail` is hand-written elsewhere, add the field there instead. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/proposals/{id}` | — | `200` existing `ProposalDetail` + additive `normalizer_manifest_preview: str | null` | `404` `PROPOSAL_NOT_FOUND` (existing) |

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py  (add to ProposalDetail, after config_diff)
normalizer_manifest_preview: str | None = None
"""Server-rendered query-normalizer manifest (feat_apply_path_normalizer_declaration FR-7).
Non-null ONLY for study-backed proposals whose config_diff carries a valid query_normalizer;
null for manual proposals (even with a stray key), absent keys, and out-of-allowlist values."""
```

**UI element inventory**
- Card "Query normalizer manifest" (title, sentence case) — data source: `proposal.normalizer_manifest_preview` + derived filename `{template.name}.query_normalizer.yaml` (template name from the existing `_TemplateEmbed` on `ProposalDetail`).
- Info tooltip on the heading — glossary key `proposal.normalizer_manifest`.
- `<pre>`/code block rendering the manifest YAML verbatim (read-only; no interaction).
- No buttons, no inputs, no select — purely informational. No enumerated wire values introduced (the only enum, `query_normalizer` choices, is Phase 1's; this block renders, never submits).

**State dependency analysis:** The panel consumes `proposal` already fetched by `/proposals/[id]/page.tsx` (the page renders `<ConfigDiffPanel diff={proposal.config_diff} />` today). `normalizer_manifest_preview` + `template` are both on `ProposalDetail`, so no new fetch and no new prop plumbing beyond passing the two fields to the new component. Verified: `page.tsx` renders `ProposalDetail` and `ConfigDiffPanel` consumes `proposal.config_diff`.

**Tasks**
1. Backend: add the schema field + populate in `_assemble_proposal_detail` with the study-backed + valid-key guard.
2. Backend contract test (AC-11b + manual-exclusion).
3. Regenerate `ui/src/lib/types.ts` from the updated backend OpenAPI so `ProposalDetail` carries `normalizer_manifest_preview` (Finding-5; verify the gen command at execution — do not hand-edit the generated file).
4. Frontend: `NormalizerManifestPanel` component (filename + preview + tooltip), gate-agnostic glossary key.
5. Mount in `page.tsx` below `<ConfigDiffPanel>` with the three-fact defense-in-depth guard.
6. Vitest for show/hide/manual-exclusion/glossary (AC-10, AC-11).

**Definition of Done**
- `GET /api/v1/proposals/{id}` returns `normalizer_manifest_preview` == `build_normalizer_manifest(...)` for study-backed+valid; `null` for absent/invalid/manual (AC-11b, contract test).
- Panel renders for study-backed proposals with a normalizer; hidden when the field is null (AC-10, AC-11).
- Glossary key passes length/no-jargon lint; copy is gate-agnostic (no false "emitted" claim).
- `make test-contract` (targeted) + `cd ui && pnpm test` (targeted) + `pnpm lint`/`pnpm typecheck` green.

**Epic 3 gate:** the manifest preview renders for the right proposals, sourced from the backend builder (no TS drift), with the manual-proposal exclusion enforced on both layers.

---

## Epic 4 — Docs + E2E

### Story 6 — Documentation

**Outcome:** Apply-path, runbook, CLAUDE.md, and parent-spec pointers reflect the shipped manifest contract.

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/apply-path.md` | Add "Structured normalizer manifest (Phase 3)" section: manifest as the first non-`params.json` structured artifact, `{template}.query_normalizer.yaml` convention, the `EMIT_NORMALIZER_MANIFEST` gate, the §9 normative schema (link/excerpt), and the operator-CI consumption contract. |
| `docs/03_runbooks/` (new or extend an existing runbook) | Enabling the gate + a CI-consumption sketch (parse the YAML, wire into the query layer's startup config). |
| `CLAUDE.md` | Document `EMIT_NORMALIZER_MANIFEST` (non-secret env, Settings section). |
| `../feat_query_normalization_tuning/feature_spec.md` | Update §3 + §19 D-1 status pointers (Phase 3 shipped). |
| `feature_spec.md` (this feature) | Update Status from "Draft — DESIGN-AHEAD" to "Implemented" (FR-8 requires this feature's own status flip on ship). |
| `pipeline_status.md` (this feature) | Flip `## Implementation` to Complete + gates met. |
| `state.md` / `state_history.md` | Merge one-liner (state.md) + full narrative (state_history.md). |

**Tasks**
1. Write the apply-path.md section (covers AC-0's "gating documented" surface + the contract docs).
2. Runbook section.
3. CLAUDE.md env-var row.
4. Parent-spec pointer + state updates (at finalization).

**Definition of Done**
- `apply-path.md` documents the manifest artifact, filename, gate, schema, and consumption contract.
- `CLAUDE.md` lists `EMIT_NORMALIZER_MANIFEST`.
- Doc unit tests (e.g., `backend/tests/unit/docs/test_claude_md_sections.py`) stay green (verify no assertion broken by the CLAUDE.md edit).

### Story 7 — Real-backend E2E

**Outcome:** A real-backend Playwright flow proves the manifest reaches the PR + the proposal preview.

**New / modified files**

| File | Change |
|---|---|
| `ui/tests/e2e/query-normalization.spec.ts` (extend Phase 1's spec, or a sibling NEW spec) | With `EMIT_NORMALIZER_MANIFEST=true`: run a Phase-1 normalizer study to a non-`none` winner, open the proposal PR, assert (via `page`) the manifest-preview block + (via the test config repo) the pushed `{template}.query_normalizer.yaml` + the PR body naming the manifest file. Setup via API helpers; assertions via `page`; NO `page.route()`. Covers AC-13. |

**Tasks**
1. Extend Phase 1's E2E setup (cluster + normalizer template + query set + judgments + config repo) — reuse Phase 1's helpers.
2. Set the gate env for the E2E stack.
3. Drive the proposal-open flow via `page`; assert the manifest preview DOM + the pushed file + PR body.

**Definition of Done**
- E2E passes against the real backend (no mocking); asserts browser-visible manifest preview + repo-side manifest file + PR-body reference (AC-13).
- `cd ui && pnpm test:e2e` (or the stable profile) green for this spec.

**Epic 4 gate:** docs reflect the shipped contract; the real-backend E2E proves end-to-end manifest delivery.

---

## 3) Testing workstream

### 3.1 Unit tests (`backend/tests/unit/`)
- [ ] `test_normalizer_manifest.py` — builder shape/determinism/strictness/none/error (Story 1, AC-1).
- [ ] `test_normalizer_manifest_runtime_parity.py` — manifest ≡ runtime (Story 1, AC-2/I-2).
- [ ] `test_git_pr_body_manifest.py` — PR-body four branches (Story 4, AC-5/7/8/9).
- [ ] settings unit assertion — gate default + env override (Story 3).
- DoD: critical branches covered, deterministic.

### 3.2 Integration tests (`backend/tests/integration/`)
- [ ] `test_open_pr_normalizer_manifest.py` — emit ON/OFF, single-commit, containment/separator failure → pending, invalid-value params-only (Story 2, AC-3/4/6/12, FR-3 reconciliation).
- DoD: happy path + all failure paths covered; I-3 atomicity asserted (nothing pushed on failure).

### 3.3 Contract tests (`backend/tests/contract/`)
- [ ] `test_proposals_normalizer_manifest_preview_contract.py` — `normalizer_manifest_preview` field: study-backed+valid → builder string; null for absent/invalid/manual (Story 5, AC-11b).
- [ ] `NORMALIZER_MANIFEST_EMIT_FAILED` envelope test — **conditional (OQ-2)**: only if the gate/failure is surfaced via an endpoint. Default — NOT needed (worker-recorded on `pr_open_error`); documented as deliberately omitted.
- DoD: every accepted endpoint surface has contract coverage; the one new error code is worker-recorded (no envelope) per OQ-2 default.

### 3.4 E2E tests (`ui/tests/e2e/`)
- [ ] Extend `query-normalization.spec.ts` (Story 7, AC-13). Real-backend, `page`-driven, no `page.route()`.
- DoD: stable pass; assertions via `page` + repo-side file check.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/workers/test_git_pr_body.py` (Phase 1) | "Operator-side requirement" assertions | TBD post-G-1 | Update for the rewritten gate-ON wording; gate-OFF case must still match Phase 1 text. Re-audit at execution (Phase 1 owns this file). |
| `backend/tests/integration/workers/test_open_pr_*.py` | `open_pr` end-to-end | existing | No change to existing assertions (manifest emit is gate-OFF by default → existing tests run params-only path unchanged). New behavior in the new test file. |
| `backend/tests/contract/test_proposals_*` | `ProposalDetail` shape | existing | Additive field — verify existing shape assertions don't use `extra="forbid"` exact-key matching; if they do, add the new field. Re-audit at execution. |
| `backend/tests/unit/docs/test_claude_md_sections.py` | CLAUDE.md section assertions | existing | Verify the `EMIT_NORMALIZER_MANIFEST` addition doesn't break a section-presence assertion. |

### 3.5 Migration verification
- N/A — no schema change. **Assert Alembic head unchanged at `0022_solr_engine_auth_check`** (no new revision file).

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test` + `pnpm lint` + `pnpm typecheck` + `pnpm build`
- [ ] `cd ui && pnpm test:e2e` (stable profile) for the touched flow
- [ ] I-4 **emit-site** audit (distinguishes write sites from read-only call sites): the only code that WRITES a `query_normalizer.yaml` file is the `open_pr` worker — `grep -rn "query_normalizer.yaml" backend/app backend/workers` shows the worker write + `_validate_manifest_path` only. `build_normalizer_manifest` CALL sites are limited to exactly three: the domain builder definition (`normalizers.py`), the `open_pr` worker (emit), and the `GET /proposals/{id}` assembler (`proposals.py`, read-only preview — Story 5). No service/orchestrator/adapter/digest-worker calls it. (The read-only preview call in `proposals.py` is NOT a manifest *emit* and does not violate I-4's single-emit-site invariant — I-4 governs file emission, not in-memory rendering for a GET response.)

---

## 4) Documentation update workstream

### 4.0 Core context files
- [ ] `state.md` — add merge one-liner (Last 5 merges); Alembic head UNCHANGED (`0022`); note the new `EMIT_NORMALIZER_MANIFEST` env var under known config. Narrative → `state_history.md`.
- [ ] `architecture.md` — note (in the apply-path pointer) that the apply path now emits a structured manifest beyond `params.json` (first such artifact).
- [ ] `CLAUDE.md` — `EMIT_NORMALIZER_MANIFEST` env var (Story 6).

### 4.1 Architecture docs
- [ ] `docs/01_architecture/apply-path.md` — manifest section (Story 6, FR-8).

### 4.2 Product docs
- [ ] None — no persona-level capability shift (spec §15).

### 4.3 Runbooks
- [ ] `docs/03_runbooks/` — gate-enable + CI-consumption sketch (Story 6).

### 4.4 Security docs
- [ ] None — controls are reuses (path containment + token redaction); spec §10 notes this.

### 4.5 Quality docs
- [ ] None — existing conventions cover the new layers.

**Documentation DoD:** `state.md`/`architecture.md`/`CLAUDE.md` consistent with shipped behavior; `apply-path.md` documents the manifest contract; runbook dry-runnable.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Generalize the single-file commit into `_git_commit_files` (multi-file, single commit) WITHOUT breaking the existing single-file params + separate-chart commit behavior.

### 5.2 Planned refactor tasks
- [ ] Introduce `_git_commit_files`; route the params commit through it (`[params_path]` when no manifest, `[params_path, manifest_path]` when emitting). Keep `_git_commit_file` for the chart PNG (separate commit) OR have it delegate to `_git_commit_files([path])` — prefer delegation to remove duplication, verified by the existing open_pr integration tests passing unchanged.

### 5.3 Refactor guardrails
- [ ] Existing `open_pr` integration tests pass unchanged (params + chart commit behavior preserved).
- [ ] Lint/typecheck green.
- [ ] No product-scope expansion.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Phase 1 (`feat_query_normalization_tuning`) merged (G-1) | All stories | **Plan stage, NOT merged** | Stories extend non-existent symbols; do not execute (gate). |
| Operator-friction evidence (G-2) | Execution authorization | Not present | Shipping unneeded scope; do not execute (gate). |
| Phase 2 `NormalizerStep` enum (soft) | Story 1 (D-3-2 vocabulary) | idea-only | None — Story 1 defines a local vocabulary if absent. |
| `feat_github_pr_worker` (`open_pr` worker) | Story 2 | shipped MVP1 | None. |
| YAML serializer in dep closure | Story 1 | verify at execution | None — stdlib emitter fallback; no new dep without authorization. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Phase 1 symbol names drift before G-1 clears | M | M | One-pass plan-accuracy re-audit at G-1-clear (§0). |
| `ProposalDetail` schema shifts before execution | L | L | Story 5 re-verifies the insertion point (`config_diff` field) at execution. |
| Existing contract tests use exact-key matching on `ProposalDetail` | L | L | §3.5 audit checks for `extra="forbid"`; additive field handled. |
| Multi-file commit refactor regresses chart-PNG separate commit | L | M | Refactor guardrail: existing `open_pr` integration tests pass unchanged. |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Manifest path escapes clone / separator in `template_name` | Malformed `config_path`/`template_name` | `InvalidConfigPathError` → `NORMALIZER_MANIFEST_EMIT_FAILED` on `pr_open_error`; nothing pushed | Retry `open_pr` after fixing config (proposal stays `pending`). |
| Manifest write fails (disk/permission) | OSError on write | `_NormalizerManifestEmitError` → `pr_open_error`; nothing pushed (I-3) | Retry. |
| Out-of-allowlist `query_normalizer` reaches worker | (unreachable; Phase 1 FR-2 gate) | Redacted warning, manifest skipped, params-only commit, PR body no manifest claim (FR-3 exemption) | None needed — params still apply. |
| Builder `ValueError` on a value that passed the in-worker allowlist check | Logic bug | `NORMALIZER_MANIFEST_EMIT_FAILED`, abort before commit | Fix builder; retry. |

## 7) Sequencing and parallelization

### Suggested sequence
1. Story 1 (domain builder) — foundation.
2. Story 3 (settings gate) — small; unblocks Story 2's gate read.
3. Story 2 (worker emit) — depends on 1 + 3.
4. Story 4 (PR-body) — depends on 1 + 3.
5. Story 5 (API field + UI) — depends on 1.
6. Story 6 (docs), Story 7 (E2E) — last.

### Parallelization
- Stories 4 and 5 can run in parallel after 1+3 (different files: `git_pr.py` body renderer vs proposals API/UI). Story 2 also touches `git_pr.py`, so 2 and 4 should be sequenced (both edit `git_pr.py`) or carefully merged.

## 8) Rollout and cutover plan

- **Rollout:** the `EMIT_NORMALIZER_MANIFEST` gate IS the rollout — default OFF, operator opts in per install. No global flip.
- **Feature flag:** `EMIT_NORMALIZER_MANIFEST` (non-secret env).
- **Migration/cutover:** none in RelyLoop; operators add the manifest to their own CI (documented).

## 9) Execution tracker

### Current sprint
- [ ] BLOCKED — awaiting G-1 (Phase 1 merge) + G-2 (operator-friction evidence).

### Blocked items
- All 7 stories — blocker: G-1 + G-2 (design-ahead gate) — owner: product.

### Done this sprint
- [x] Spec + plan authored, GPT-5.5-reviewed (design-ahead).

## 10) Story-by-Story Verification Gate

Per story, attach evidence:
- [ ] Files created/modified match the New/Modified tables.
- [ ] Worker emit step + PR-body branches + API field implemented exactly as documented.
- [ ] Tests added for every applicable layer (unit/integration/contract/e2e).
- [ ] Commands passed: `make test-unit`, `make test-integration` (targeted), `make test-contract`, `cd ui && pnpm test` (+ e2e if UI touched).
- [ ] No migration (assert head unchanged at `0022`).
- [ ] Docs updated in the same PR when behavior/contract changed.
- [ ] I-4 emit-site audit clean (only the `open_pr` worker writes the manifest file; `build_normalizer_manifest` callers limited to domain builder + worker + GET assembler — §3.6).

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:** spec §8.1 lists 2 affected endpoints (`POST /open_pr` worker-trigger, `GET /proposals/{id}`). Plan: `open_pr` extended in Story 2; `GET /proposals/{id}` additive field in Story 5. ✓ (no NEW endpoints — both are existing surfaces.)
2. **Spec ↔ plan error code coverage:** spec §8.5 has 1 code, `NORMALIZER_MANIFEST_EMIT_FAILED` (worker-recorded). Covered by Story 2 (emission) + Story 2's integration test (AC-6). Contract test conditional per OQ-2 (default omitted, justified §3.3). ✓
3. **Spec ↔ plan FR coverage:** FR-1→S1, FR-2→S2, FR-3→S2+S3, FR-4→S2, FR-5→S3, FR-6→S4, FR-7→S5, FR-8→S6, AC-13→S7. All 8 FRs assigned. ✓
4. **Story internal consistency:** `normalizer_manifest_preview` schema field matches the endpoint table + AC-11b; new files unique per story (no ownership conflict — `git_pr.py` modified by S2 + S4, sequenced per §7); modified files verified to exist (git_pr.py, settings.py L302, schemas.py L1298 ProposalDetail, proposals.py L112/177, config-diff-panel.tsx, page.tsx, glossary.ts). ✓
5. **Test file count:** 4 unit + 1 integration + 1 contract + 1 e2e + 1 frontend vitest = 8 test artifacts, each assigned to a story DoD. ✓ No orphans.
6. **Gate arithmetic:** Epic gates reference the correct story counts. ✓
7. **Open questions resolved:** spec §19 OQ-1 (default: server-rendered field — plan Story 5 implements it), OQ-2 (default: worker-only — plan omits the contract envelope test, justified), OQ-3 (default: YAML — Story 1 emits YAML). All three have recommended defaults the plan assumes; they remain product-revisitable at G-2 clear but do NOT block plan execution (they are pre-decided defaults). ✓
8. **Frontend UI Guidance:** present below (Story 5 is the only frontend story). ✓
9. **Enumerated value contract audit:** the only enum is `query_normalizer` choices (Phase 1's `NORMALIZER_CHOICES` / `NORMALIZER_VALUES`). Story 5's UI block RENDERS the manifest but submits NO enumerated wire value (read-only preview), so no new `<select>`/filter introduces drift risk. The manifest's `steps[*].id` vocabulary is internal (D-3-2), not a user-editable wire value. ✓
10. **Audit-event coverage:** MVP2 has no `audit_log` (spec §6). No audit story. Conditional MVP3 note flagged for re-check at execution. ✓ (justified gap.)
11. **Migration path:** no migration; Alembic head stays `0022` (verified). ✓

No unresolved findings.

---

## UI Guidance (Story 5 — the only frontend-facing story)

### Reference: current component structure

- **`ui/src/components/proposals/config-diff-panel.tsx`** (115 LOC, verified): a `<Card>` with `<CardHeader><CardTitle>Config diff</CardTitle></CardHeader>` + a `<Table>` of From/To rows over `Object.entries(diff)`. Consumes `diff: Record<string, unknown>` only. The new panel sits as a SIBLING below it.
- **`ui/src/app/proposals/[id]/page.tsx`** (3.8K): renders the proposal detail, including `<ConfigDiffPanel diff={proposal.config_diff} />`. Insertion point: immediately AFTER the `<ConfigDiffPanel>` render. The page already has `proposal` (a `ProposalDetail`) in scope.

### Analogous markup pattern (copy from `config-diff-panel.tsx`)

```tsx
{/* Pattern — from ui/src/components/proposals/config-diff-panel.tsx:58-113 */}
import { InfoTooltip } from '@/components/common/info-tooltip';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export interface NormalizerManifestPanelProps {
  manifestYaml: string;        // proposal.normalizer_manifest_preview (non-null)
  filename: string;            // `${templateName}.query_normalizer.yaml`
}

export function NormalizerManifestPanel({ manifestYaml, filename }: NormalizerManifestPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          <span className="inline-flex items-center gap-1">
            Query normalizer manifest
            <InfoTooltip glossaryKey="proposal.normalizer_manifest" />
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-2 font-mono text-xs text-muted-foreground">{filename}</p>
        <pre className="overflow-x-auto rounded bg-muted p-3 text-xs">{manifestYaml}</pre>
      </CardContent>
    </Card>
  );
}
```

### Insertion in `page.tsx`

```tsx
{/* After <ConfigDiffPanel diff={proposal.config_diff} /> */}
{proposal.study_id != null &&
  proposal.config_diff?.query_normalizer != null &&
  proposal.normalizer_manifest_preview != null && (
    <NormalizerManifestPanel
      manifestYaml={proposal.normalizer_manifest_preview}
      filename={`${proposal.template.name}.query_normalizer.yaml`}
    />
  )}
```

> **Defense-in-depth client guard (GPT-5.5 plan-review Finding-2):** the render condition checks ALL three client-side facts — `study_id != null` (study-backed, NOT manual — mirrors the backend `study_id IS NULL` manual discriminator), `config_diff.query_normalizer` present, AND `normalizer_manifest_preview != null`. The backend already nulls the preview for manual/absent/invalid (Story 5 backend half), so any single condition suffices in practice; the redundant `study_id` + `config_diff` checks ensure that even a (buggy) non-null preview on a manual proposal is hidden. The Story 5 vitest manual-stray fixture asserts this by feeding a MANUAL proposal (`study_id: null`) with both a stray `config_diff.query_normalizer` AND a non-null `normalizer_manifest_preview` → block hidden.

### Layout and structure
- Stacked cards (matches the existing proposal-detail card stack). Full width. `<pre>` scrolls horizontally on overflow (`overflow-x-auto`).

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Open `/proposals/[id]` | Page fetches `ProposalDetail` (existing); renders the manifest panel iff `normalizer_manifest_preview != null` | `GET /api/v1/proposals/{id}` (existing; now carries the additive field) |

No buttons, no mutations from this panel.

### Information architecture placement
- Proposal-detail page, directly below the Config-diff card, above Suggested follow-ups. Discovered by the operator while reviewing the proposal before opening/merging the PR. No new route/tab.

### Tooltips and contextual help

| Element | Tooltip text (glossary) | Trigger | Placement | Glossary key | Source-of-truth comment |
|---|---|---|---|---|---|
| "Query normalizer manifest" heading | "The structured normalizer contract for this proposal. When manifest emission is enabled for this install, RelyLoop emits it into the PR so your CI can apply the winning query normalizer automatically — no manual snippet copy required." | hover info icon | top | `proposal.normalizer_manifest` (NEW) | `// Source-of-truth: feat_apply_path_normalizer_declaration FR-7 / spec §11` |

Gate-agnostic wording (does NOT assert a file was emitted — the preview renders regardless of the per-install gate). Uses the existing `<InfoTooltip glossaryKey=...>` primitive (same as config-diff-panel.tsx).

### Visual consistency table

| New element | CSS class / pattern | Source |
|---|---|---|
| Card wrapper | `<Card>`/`<CardHeader>`/`<CardTitle className="text-base">`/`<CardContent>` | `config-diff-panel.tsx` |
| Heading + tooltip | `inline-flex items-center gap-1` + `<InfoTooltip>` | `config-diff-panel.tsx:77-81` |
| Filename | `font-mono text-xs text-muted-foreground` | matches `config-diff` cell styling |
| YAML block | `<pre className="overflow-x-auto rounded bg-muted p-3 text-xs">` | standard shadcn muted block |

### Component composition
- Extracted component (`NormalizerManifestPanel`), not inline — mirrors `ConfigDiffPanel` extraction; props are the two display strings only (no callbacks, no shared state, no circular deps).

### Legacy behavior parity
No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan. The only frontend change is an ADDITIVE new component + one conditional render in `page.tsx`.

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs (§1, §11).
- [x] Every story includes New/Modified files, (endpoints where applicable), key interfaces, tasks, DoD.
- [x] Test layers (unit/integration/contract/e2e) explicitly scoped (§3).
- [x] Documentation updates planned (§4).
- [x] Lean refactor scope + guardrails explicit (§5).
- [x] Epic gates measurable.
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review performed, no unresolved findings (§11).
- [ ] **EXECUTION BLOCKED until G-1 + G-2 (§0).**
