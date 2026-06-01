# Feature Specification — Apply-path-side normalizer declaration (Phase 3 of query-normalization tuning)

**Date:** 2026-06-01
**Status:** Draft — **DESIGN-AHEAD. Implementation is GATED (see §5 + §16). Do NOT `/impl-execute` until both gates clear.**
**Owners:** Product — soundminds.ai · Engineering — RelyLoop core
**Related docs:**
- [`idea.md`](idea.md)
- [`feat_query_normalization_tuning/feature_spec.md`](../feat_query_normalization_tuning/feature_spec.md) — **Phase 1, the foundation this spec builds on.** Specifically §3 "Phase boundaries" (defines Phase 3) and §19 D-1 (the prod-reproducibility hand-off fork; Phase 3 is option (a) of that fork).
- [`feat_query_normalizer_typed_pipeline/idea.md`](../feat_query_normalizer_typed_pipeline/idea.md) — Phase 2 (typed `NormalizerPipelineParam` + `NormalizerStep` vocabulary); a candidate source for this feature's manifest step vocabulary.
- [`docs/01_architecture/apply-path.md`](../../../../01_architecture/apply-path.md) — Git-PR posture; this is the first feature to push structured payload through the apply path beyond scalar parameter values.
- [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) — the `query_normalizer` reserved-key contract Phase 1 establishes.

---

## 0) Design-ahead status and gating (read first)

This spec is a **design-ahead artifact**. It is written now — while Phase 1 is in the Plan stage and unmerged — so that when the friction it addresses materializes, the design is already reviewed and the implementation plan exists. It is **not** ready to execute.

Two hard gates MUST both be satisfied before this feature is implemented (`/impl-execute`):

- **Gate G-1 — Phase 1 merged.** [`feat_query_normalization_tuning`](../feat_query_normalization_tuning/feature_spec.md) MUST be merged to `main`. Phase 3 extends Phase 1's reserved `query_normalizer` Categorical key, its `NORMALIZER_CHOICES` allowlist, its `_PR_BODY_NORMALIZER_SNIPPETS` dict, and its "Operator-side requirement" PR-body section. None of those symbols exist in the codebase today (verified 2026-06-01: `grep -rn "query_normalizer\|NORMALIZER_CHOICES" backend/app backend/workers` returns zero non-comment hits). Building Phase 3 against an unmerged Phase 1 would fork the design.
- **Gate G-2 — Operator-friction evidence.** A body of evidence MUST show that Phase 1's option (b) documentation hand-off (the "copy this Python snippet into your query layer" merge contract) is causing real production friction. Acceptable evidence: GitHub issues reporting under-reproduced production gains traced to a forgotten/incorrect manual normalizer copy; in-product feedback; an adoption survey; or a design-partner escalation. Absent this evidence, Phase 1's prose hand-off remains adequate (per Phase 1 §19 D-1 rationale) and this feature stays deferred.

**Both gates are product/operator decisions that cannot be unilaterally locked at spec time.** They are restated as the release gate in §16. The remainder of this spec assumes both gates have cleared.

## 1) Purpose

- **Problem:** Phase 1 (D-1, option (b)) closes the prod-reproducibility loop with *prose*: the winning normalizer travels in `proposals.config_diff` as a scalar `query_normalizer` value, the PR body's "Operator-side requirement" section names it and embeds a copy-pasteable Python snippet, and the merge contract is "you must replicate this normalizer in your query layer for production parity." That hand-off is adequate when the operator reads PRs end-to-end, owns a Python (or trivially-translatable) query layer, and owns its deployment. It is **frictionful** when the query layer is owned by a different team without the PR-author's merge rights, when the deployment pipeline expects structured config rather than prose, or when the manual "replicate this" step is forgotten or done wrong — causing the production gain to under-reproduce what the loop measured.
- **Outcome:** The winning normalizer ships as a **structured, language-agnostic manifest** in the config-repo PR — not just prose. The operator's CI consumes the manifest directly (parses the YAML, wires it into the query layer's startup config) instead of a human re-implementing a snippet. The merge contract transitions from "copy this Python snippet" to "apply the parameters AND wire the emitted normalizer manifest into your query layer." Production parity becomes a config-consumption step, not a manual re-implementation step.
- **Non-goal (preserved):** RelyLoop still never sits on the live search-serving path, never writes to the cluster, never modifies analyzer/index-mapping settings (umbrella §4). The tool's role still ends at the PR. Phase 3 only changes **what** the apply path emits (a structured manifest alongside the scalar `params.json`), not where RelyLoop's responsibility ends. The operator's CI still owns consuming the manifest and deploying the query layer.

## 2) Current state audit

### Existing implementations

> **Note on Phase 1 dependency:** Several rows below reference symbols that Phase 1 *introduces* (`NORMALIZER_CHOICES`, `_PR_BODY_NORMALIZER_SNIPPETS`, the "Operator-side requirement" PR-body section, the reserved `query_normalizer` Categorical key). These do not exist in the codebase today — they are the Phase 1 deliverable. The rows describe the **post-Phase-1** state Phase 3 builds on. Rows describing code that exists *today* are marked "EXISTS NOW."

| File / symbol | What it does | Notes (relevant to this feature) |
|---|---|---|
| [`backend/workers/git_pr.py:422`](../../../../../backend/workers/git_pr.py) (`_apply_config_diff`) — **EXISTS NOW** | Reads the existing `{template_name}.params.json`, validates each `config_diff` key against `declared_params` (raises `_ParamNotInTemplateError` → `PARAM_NOT_IN_TEMPLATE` on drift), deep-merges `change["to"]` per key, and writes the merged dict back via `params_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")`. | The single scalar-params writer. Phase 1 lets `query_normalizer` flow through here as just another scalar key in `params.json` — but Phase 1 deliberately does NOT emit a structured manifest (D-1 option (b)). **Phase 3's new manifest-emit step runs alongside this function**, after `_apply_config_diff` writes `params.json` and before the commit/push step. |
| [`backend/workers/git_pr.py:404`](../../../../../backend/workers/git_pr.py) (`_validate_params_path`) — **EXISTS NOW** | Computes + containment-checks the params-file path: `(clone_dir / config_path / f"{template_name}.params.json").resolve()`, asserting it stays under the clone root (symlink / traversal guard via `validate_config_path` + `relative_to`). **Note:** this guards clone-root *containment*, not that `template_name` is a bare basename — a `template_name` carrying path separators could still resolve to a different location *within* the clone root. | Phase 3's manifest path MUST be derived as a guaranteed sibling of the validated params path (FR-2: `params_path.with_name(...)` after a basename guard on `template_name`), then containment-checked identically. A new `_validate_manifest_path` helper mirrors this AND adds the basename guard. |
| [`backend/workers/git_pr.py:540`](../../../../../backend/workers/git_pr.py) (`_render_pr_body_study_backed`) — **EXISTS NOW (Phase 1 extends)** | Renders the study-backed PR markdown (Metric delta / Confidence / Config diff / Suggested follow-ups / Parameter importance). | Phase 1 inserts an "Operator-side requirement" section here when `config_diff` carries `query_normalizer`. **Phase 3 rewrites that section's body** from "copy this Python snippet" to "your CI applies the emitted manifest automatically — no copy step required," referencing the manifest filename. |
| [`backend/workers/git_pr.py:595`](../../../../../backend/workers/git_pr.py) (`_render_pr_body_manual`) — **EXISTS NOW** | Markdown body for hand-crafted proposals (no metrics). | **Explicitly excluded** from Phase 3 (as from Phase 1): manual proposals never pass through the loop, so they never carry a `query_normalizer`. No manifest emitted for manual proposals. |
| [`backend/workers/git_pr.py:~877-895`](../../../../../backend/workers/git_pr.py) (`open_pr` worker body, Steps 9–12) — **EXISTS NOW** | The 15-step worker: validates params path (Step 8), applies config_diff (Steps 9–10), commits the params file (Step 12) via `_git_commit_file(clone_dir, params_path, commit_msg, token)` — which `git add`s and commits exactly ONE file — optionally commits the chart PNG as a separate commit, then `git push`. | Phase 3 adds a manifest-emit step between Step 10 (apply config_diff) and the commit step. Because the existing `_git_commit_file` commits a single file and D-3-3 requires `params.json` + manifest in ONE commit, Phase 3 introduces a multi-file commit helper (e.g., `_git_commit_files(clone_dir, [params_path, manifest_path], msg, token)`) that stages both paths before a single commit — it does NOT add a second `_git_commit_file` call for the manifest. The chart PNG stays its own separate commit (unchanged). See §9 / D-3-3. |
| [`backend/workers/git_pr.py:633`](../../../../../backend/workers/git_pr.py) (`_ParamNotInTemplateError`, `_ParamsFileNotFoundError`, `_BranchExistsError`) — **EXISTS NOW** | Domain exceptions raised inline, mapped to error codes by the worker's exception handler (e.g., `PARAM_NOT_IN_TEMPLATE`). | Phase 3 adds one new inline exception class (`_NormalizerManifestEmitError`) following the identical pattern; mapped to a new `NORMALIZER_MANIFEST_EMIT_FAILED` worker error code that funnels into the existing token-redacted `pr_open_error` path (the proposal stays `pending`, not crashed). |
| [`backend/app/db/models/proposal.py:64`](../../../../../backend/app/db/models/proposal.py) (`Proposal.config_diff`) — **EXISTS NOW** | `JSONB NOT NULL`, `{param: {from, to}}`. The digest worker builds it at [`backend/workers/digest.py`](../../../../../backend/workers/digest.py) as every winning param's `{from, to}`. | Source of the winning `query_normalizer` value: `config_diff["query_normalizer"]["to"]`. Phase 3 reads it identically to Phase 1's PR-body renderer. No schema change. |
| [`backend/app/db/models/config_repo.py`](../../../../../backend/app/db/models/config_repo.py) (`pr_base_branch`, `auth_ref`, `provider`) — **EXISTS NOW** | The config-repo registry row. `provider IN ('github')` CHECK; `pr_base_branch` default `main`; `auth_ref` names the mounted PAT secret. | Phase 3's back-compat env gate (D-3-4) decides whether the manifest is emitted globally; a per-repo opt-in column on this table is explicitly **out of scope** (see §3). |
| [`backend/app/db/models/cluster.py:75`](../../../../../backend/app/db/models/cluster.py) (`Cluster.config_path`) — **EXISTS NOW** | `String`, nullable. The directory within the config repo holding the template + params files. | The manifest is written under the same `config_path` directory, sibling to `{template_name}.params.json`. |
| [`docs/01_architecture/apply-path.md`](../../../../01_architecture/apply-path.md) — **EXISTS NOW** | Documents the "tool only edits `*.params.json`, never templates" contract + the PR-creation flow. | Phase 1 keeps this unchanged. **Phase 3 materially extends it** — it documents the first non-`params.json` structured artifact the apply path emits. FR-7 covers the doc patch. |
| [`ui/src/components/proposals/config-diff-panel.tsx`](../../../../../ui/src/components/proposals/config-diff-panel.tsx) — **EXISTS NOW** | Renders `proposals.config_diff` as a From/To table on the proposal-detail page (`ui/src/app/proposals/[id]/page.tsx`). | Phase 3's UI surfacing (Capability C / FR-6) adds a manifest-preview block on the proposal-detail page below this table, rendered when `config_diff` carries `query_normalizer`. |
| `NORMALIZER_CHOICES`, `DEFAULT_NORMALIZER`, `_PR_BODY_NORMALIZER_SNIPPETS`, `normalize(...)` in `backend/app/domain/study/normalizers.py` — **PHASE 1 DELIVERABLE (does not exist today)** | Phase 1's pure-domain normalizer module: the four-value allowlist, the runtime normalizer, and the per-choice Python snippet dict. | Phase 3's manifest **builder** lives in the same module (or a sibling `normalizer_manifest.py`) so the manifest, the runtime `normalize()`, and the snippets share one source of truth (mirrors Phase 1's I-4 single-source discipline). |

**Why this matters:** The apply-path worker writes exactly one structured artifact today (`params.json`) and validates it against the template's `declared_params`. Phase 3 introduces a *second* emitted artifact (the normalizer manifest) on the same commit/push path. Confining the change to (a) a manifest-builder in the normalizer domain module and (b) a manifest-emit step in `git_pr.py` keeps the blast radius to two backend files plus the PR-body wording and one UI block — it does not touch the orchestrator, trial runner, evaluator, or adapter render hooks (those are Phase 1's territory).

### Navigation and link impact

No URL changes. Phase 3 extends the existing proposal-detail page (`ui/src/app/proposals/[id]/page.tsx`) with a manifest-preview block; it adds no route, tab, or modal.

| Source file | Current link target | New link target |
|---|---|---|
| _none_ | _none_ | _none_ |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`backend/tests/unit/workers/test_git_pr_body.py`](../../../../../backend/tests/unit/workers/test_git_pr_body.py) (Phase 1 augments this) | PR-body markdown assertions, incl. Phase 1's "Operator-side requirement" section | augment | Update the Phase 1 assertions for the rewritten section body (manifest-filename reference instead of inline snippet) — gated on D-3-4: if the back-compat gate is OFF, the section retains Phase 1's snippet wording. Add a case asserting the manifest-filename reference when the gate is ON. |
| `backend/tests/unit/workers/test_git_pr_manifest.py` (NEW) | manifest builder + manifest-emit logic | new | Unit-test the manifest builder: given `config_diff["query_normalizer"]["to"] = "lowercase+trim+expand_contractions"`, the built manifest YAML round-trips to the expected structured shape (steps + params + reference-impl pointer). |
| `backend/tests/integration/workers/test_open_pr_*.py` (Phase 1-era + earlier) | `open_pr` end-to-end against a local git fixture repo | augment | One new integration test: an `open_pr` run on a proposal whose `config_diff` carries `query_normalizer` writes BOTH `{template_name}.params.json` AND `{template_name}.query_normalizer.yaml` (or the inline key, per D-3-1) into the clone, and both land in the pushed commit. |
| `backend/tests/contract/` | error-envelope shape | augment (conditional) | If D-3-4's env gate is exposed via any endpoint surface, a contract test asserts the `NORMALIZER_MANIFEST_EMIT_FAILED` envelope. (Default: worker-only error, no endpoint surface → no contract test needed; this row is conditional on the open question OQ-2 resolution.) |
| `ui/src/__tests__/components/proposals/` | proposal-detail component rendering | new | A vitest case asserting the manifest-preview block renders when `config_diff.query_normalizer` is present and is hidden otherwise. |
| `ui/tests/e2e/` (Phase 1's `query-normalization.spec.ts`) | real-backend normalizer flow | augment | Extend Phase 1's E2E (or add a sibling spec) to assert the proposal preview shows the manifest block + the PR body references the manifest filename. Real-backend only, no `page.route()`. |

### Existing behaviors affected by scope change

- **`open_pr` worker emitted artifacts**: Current (Phase 1) — the worker writes exactly one file, `{template_name}.params.json`, into the clone and commits it. New (Phase 3) — when `config_diff` carries `query_normalizer` AND the back-compat gate is ON, the worker ALSO writes `{template_name}.query_normalizer.yaml` (D-3-1 default) and includes it in the pushed commit. **Decision needed:** Yes — the manifest shape (inline vs separate file) and the back-compat gate are spec-time decisions; see §19 D-3-1 + D-3-4.
- **"Operator-side requirement" PR-body section** (introduced by Phase 1): Current (Phase 1) — body reads "copy this Python snippet into your query layer." New (Phase 3, gate ON) — body reads "your CI applies the emitted manifest `{filename}` automatically — no copy step required," and the Python snippet becomes a *fallback reference* (kept for operators whose CI can't consume the manifest), not the primary instruction. **Decision needed:** Yes — whether the snippet is dropped or retained-as-fallback; see §19 D-3-5. **Recommended default: retain as fallback.**
- **Proposal-detail page**: Current — renders the config-diff From/To table. New — adds a manifest-preview block below it when `query_normalizer` is in `config_diff`. **Decision needed:** No — additive, conditional on a key being present.

---

## 3) Scope

### In scope

- **A manifest builder** in the Phase-1 normalizer domain module (`backend/app/domain/study/normalizers.py`) or a sibling `backend/app/domain/study/normalizer_manifest.py`: a pure function `build_normalizer_manifest(choice: str) -> str` that, given one of Phase 1's `NORMALIZER_CHOICES` values, returns a deterministic YAML document string describing the normalizer in a language-agnostic structured form (named choice + ordered step list + per-step params + a pointer to the reference implementation). Same-input → same-output; no I/O.
- **A manifest-emit step** in the `open_pr` worker (`backend/workers/git_pr.py`): after `_apply_config_diff` writes `params.json` and before the commit/push, when `config_diff` carries a valid `query_normalizer` key AND the back-compat gate is ON, the worker writes the manifest to `{template_name}.query_normalizer.yaml` (D-3-1) under the cluster's `config_path`, path derived + containment-checked via a `_validate_manifest_path` helper, and stages it alongside `params.json` in a SINGLE commit via a new multi-file commit helper `_git_commit_files(...)` (D-3-3; the existing single-file `_git_commit_file` cannot commit two files in one commit).
- **PR-body section rewrite**: `_render_pr_body_study_backed`'s "Operator-side requirement" section (introduced by Phase 1) is rewritten when the gate is ON to instruct the operator that their CI consumes the emitted manifest, naming the manifest filename. The Python snippet is **retained as a fallback reference** (D-3-5 recommended default).
- **Proposal-detail manifest preview** (`ui/src/components/proposals/`): a read-only preview block on the proposal-detail page showing the manifest YAML (and naming its target filename) when `config_diff.query_normalizer` is present. Glossary-grounded helper copy (one new glossary key).
- **A back-compat env gate** (D-3-4): a single non-secret boolean Compose env var (default OFF) controls whether the manifest is emitted, so config repos consuming the current `params.json`-only shape continue working unchanged until the operator opts in. New field is purely additive — existing repos are never broken.
- **A step vocabulary** for the manifest, sourced from Phase 2's `NormalizerStep` enum **if Phase 2 has shipped at Phase 3 implementation time**; otherwise Phase 3 defines a minimal frozen step vocabulary covering exactly the four Phase 1 bundles (D-3-2).
- **Apply-path doc extension** (`docs/01_architecture/apply-path.md`): documents the manifest as the first structured non-`params.json` artifact the apply path emits, the manifest filename convention, the back-compat gate, and the operator-CI consumption contract.
- **`backend/workers/git_pr.py` error handling**: one new inline exception (`_NormalizerManifestEmitError`) → `NORMALIZER_MANIFEST_EMIT_FAILED` worker error code, funneled into the existing token-redacted `pr_open_error` path (proposal stays `pending`, study unaffected).

### Out of scope

- **Anything Phase 1 owns**: the reserved `query_normalizer` Categorical key, the `NORMALIZER_CHOICES` allowlist, the runtime `normalize()` pre-render hook, the `_PR_BODY_NORMALIZER_SNIPPETS` dict, the digest analyzer-redundancy advisory, the create-study Categorical row. Phase 3 *consumes* these; it does not redefine them.
- **A per-repo opt-in column** on `config_repos` (a `emit_normalizer_manifest` boolean). The back-compat gate is a single global Compose env var in MVP2 (D-3-4); per-repo granularity is deferred (would need a migration + UI + the multi-repo registration surface that doesn't exist yet).
- **Operator-CI reference parsers/consumers.** RelyLoop emits the manifest; the operator's CI parses it. Phase 3 ships NO reference GitHub Action / parser library / consumer SDK — only the manifest spec + a documented consumption contract. (A reference consumer could be a Phase 3.5 follow-on if operators ask.)
- **Multi-language reference snippets in the manifest** beyond a pointer. Phase 2 owns the JS/TypeScript snippet. The manifest's reference-impl field is a pointer/identifier, not an inlined multi-language implementation.
- **The typed `NormalizerPipelineParam` search-space type** — that is Phase 2 (`feat_query_normalizer_typed_pipeline`). Phase 3 reuses Phase 2's `NormalizerStep` vocabulary *if available* but does not introduce the search-space type itself.
- **Any cluster write, analyzer change, LLM call, or new third-party dependency** (beyond the YAML serializer already in the dependency tree — verify at implementation time; `PyYAML` is commonly already present, else use a stdlib-only emitter).
- **Migration in RelyLoop's own DB.** No new table, no new column. (Operators may need migrations in *their* config repo to add the manifest to their CI — that is the operator's concern, documented, not RelyLoop's migration.)
- **Audit events.** `audit_log` lands at MVP3; Phase 3 (if it ships within MVP2) emits none. If Phase 3 ships post-MVP3, it picks up the audit-event matrix discipline then (see §6).

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints; unprefixed for operator/webhook endpoints — per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md).
- **Router namespace for this feature's endpoints:** **None — no new endpoints.** The feature rides the existing `open_pr` worker path (`POST /api/v1/proposals/{id}/open_pr` triggers it) and the existing `GET /api/v1/proposals/{id}` read path. The manifest is emitted into the Git repo, not exposed via a new API surface. The new `NORMALIZER_MANIFEST_EMIT_FAILED` code is a **worker** error recorded on `proposals.pr_open_error` (the existing field), not an HTTP envelope (unless OQ-2 resolves to expose the gate via an endpoint).
- **HTTP methods for CRUD:** N/A — no new CRUD surface.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per `api-conventions.md` — only relevant if OQ-2 surfaces the gate via an endpoint.
- **Auth error shape:** N/A — single-tenant, no auth surface (MVP1–MVP3).

### Phase boundaries

This feature **is itself Phase 3** of the parent `feat_query_normalization_tuning` (parent §3 "Phase boundaries", parent §19 D-1). It is not internally multi-phase. For completeness:

- **Phase 1 (`feat_query_normalization_tuning`, MVP2):** Normalizer library + adapter pre-render hook + Categorical reservation + PR-body "Operator-side requirement" prose hand-off (D-1 option (b)). **This is the foundation; G-1 requires it merged.**
- **Phase 2 (`feat_query_normalizer_typed_pipeline`, deferred):** Typed `NormalizerPipelineParam` + `NormalizerStep` enum + JS snippet + smart-quote contractions. **Composes with Phase 3** — if shipped first, its `NormalizerStep` vocabulary becomes Phase 3's manifest step vocabulary (D-3-2). Phase 3 does NOT depend on Phase 2 (it can define a minimal vocabulary itself).
- **Phase 3 (this spec, deferred + gated):** Apply-path-side structured manifest (D-1 option (a)). Gated on G-1 + G-2.

There is no Phase 4 carved from this spec. If a reference consumer is requested, it is a new sibling idea (Phase 3.5), not an internal phase here.

## 4) Product principles and constraints

- **Additive and back-compat by construction.** The manifest is a *new* emitted artifact, gated OFF by default (D-3-4). Config repos consuming the current `params.json`-only shape are never broken. Turning the gate ON is an explicit operator opt-in.
- **The tool's role still ends at the PR.** Phase 3 changes *what* the PR contains (a structured manifest), not RelyLoop's boundary. The operator's CI still owns consuming the manifest and deploying the query layer. No cluster write, no analyzer change (umbrella §4).
- **Single source of truth for the normalizer definition.** The manifest builder, the runtime `normalize()` (Phase 1), and the `_PR_BODY_NORMALIZER_SNIPPETS` (Phase 1) all derive from the same `NORMALIZER_CHOICES` allowlist and live in the same domain module. The manifest MUST NOT encode a normalizer the runtime can't produce — enforced by a test (FR-1 / I-2) that asserts the manifest's named choice is in `NORMALIZER_CHOICES`.
- **Pure-domain manifest builder.** `build_normalizer_manifest` is deterministic, no I/O, no async. Same input → same output. All Git/file I/O lives in the worker.
- **Path containment discipline.** The manifest path MUST pass the same symlink/traversal containment check as `params.json` (`_validate_manifest_path` mirrors `_validate_params_path`). No path escapes the clone root.
- **Adapter/worker boundary unchanged.** Phase 3 touches only the `open_pr` worker + a domain manifest builder + the PR-body renderer + one UI block. It does NOT touch the `SearchAdapter` Protocol, the render hooks, the orchestrator, the trial runner, the evaluator, or the digest worker.
- **Worker-failure isolation.** A manifest-emit failure MUST NOT crash the worker or leave the proposal in an inconsistent state — it funnels into the existing token-redacted `pr_open_error` path, leaving the proposal `pending` and retryable (identical to today's `PARAM_NOT_IN_TEMPLATE` / `git push failed` handling).

### Anti-patterns

- **Do not** implement this before G-1 (Phase 1 merged) and G-2 (operator-friction evidence). It is a design-ahead artifact; building it speculatively forks the design against an unmerged foundation and risks shipping unneeded scope.
- **Do not** add a per-repo `config_repos.emit_normalizer_manifest` column in MVP2 — the global env gate (D-3-4) is the back-compat mechanism; per-repo granularity needs a migration + UI not justified on day one.
- **Do not** redefine `NORMALIZER_CHOICES`, the runtime `normalize()`, or `_PR_BODY_NORMALIZER_SNIPPETS` — those are Phase 1's. The manifest builder consumes them.
- **Do not** write the manifest from anywhere except the `open_pr` worker. The digest worker, orchestrator, and adapters MUST NOT emit it — the apply path is the single emit site (mirrors I-3 from Phase 1, which confines the PR-body section to `_render_pr_body_study_backed`).
- **Do not** emit a manifest for manual (hand-crafted) proposals (`_render_pr_body_manual`). They never carry a `query_normalizer`.
- **Do not** bypass the path containment check for the manifest file. A manifest written to a symlinked/traversed path is a write-outside-the-clone vulnerability identical to the one `_validate_params_path` guards.
- **Do not** make the manifest emission silently swallow a failure and push an incomplete commit. Either both `params.json` and the manifest land in the commit, or the worker fails into `pr_open_error` with `NORMALIZER_MANIFEST_EMIT_FAILED` (atomicity, see I-3).
- **Do not** invent a manifest step vocabulary divergent from Phase 2's `NormalizerStep` enum if Phase 2 has shipped — that would create two competing vocabularies for the same concept (D-3-2).
- **Do not** drop Phase 1's Python snippet entirely from the PR body when the gate is ON — retain it as a fallback (D-3-5) for operators whose CI can't yet consume the manifest. Dropping it regresses the operators Phase 1 already served.

## 5) Assumptions and dependencies

- **Dependency (HARD, G-1): `feat_query_normalization_tuning` (Phase 1) merged.**
  - Why required: Phase 3 extends Phase 1's reserved `query_normalizer` key, `NORMALIZER_CHOICES`, the normalizer domain module, the `_PR_BODY_NORMALIZER_SNIPPETS` dict, and the "Operator-side requirement" PR-body section.
  - Status: **Plan stage, NOT merged** (verified 2026-06-01). Phase 1's `feature_spec.md` (82 KB) + `implementation_plan.md` (77 KB) exist; no Phase 1 symbol is in `backend/app/` yet.
  - Risk if missing: building Phase 3 forks the design against an unmerged foundation. **This is gate G-1 — blocks implementation.**
- **Dependency (PRODUCT GATE, G-2): operator-friction evidence.**
  - Why required: Phase 1 §19 D-1 explicitly accepts option (b) (prose hand-off) as adequate "unless MVP2 adoption shows the manual replication is frictionful." Phase 3 ships only on that signal.
  - Status: **No evidence today.** This is a product call, not a code state.
  - Risk if missing: shipping unneeded apply-path scope expansion. **This is gate G-2 — blocks implementation.**
- **Dependency (SOFT): `feat_query_normalizer_typed_pipeline` (Phase 2).**
  - Why required: Phase 2's `NormalizerStep` enum is the *preferred* source for the manifest's step vocabulary (D-3-2).
  - Status: idea-only.
  - Risk if missing: none blocking — Phase 3 defines a minimal four-bundle step vocabulary itself if Phase 2 hasn't shipped. Composes-with, does not depend-on.
- **Dependency (HARD, shipped): the apply-path worker** (`feat_github_pr_worker`, shipped MVP1).
  - Why required: the manifest-emit step extends the `open_pr` worker.
  - Status: implemented.
  - Risk if missing: none — shipped.
- **YAML serialization:** verify at implementation time whether `PyYAML` (or equivalent) is already in the dependency closure. If present, use it; if not, the manifest is simple enough to emit with a stdlib-only deterministic writer (no new dependency). **Do not add a new third-party dep without operator authorization** (per CLAUDE.md inline-fix rubric).

## 6) Actors and roles

- **Primary actor: Relevance Engineer** (umbrella §6) — runs the normalizer-tuning study (Phase 1), opens the proposal PR; with Phase 3 the PR now carries a structured manifest their CI consumes instead of a snippet they copy.
- **Secondary actor: Approver** — reviews the PR (including the manifest file + the rewritten "Operator-side requirement" section) and merges it in the config repo.
- **Secondary actor: the operator's CI** (a system actor, outside RelyLoop) — parses the merged manifest and wires it into the query layer's startup config. RelyLoop does not own this; it is documented as the consumption contract.
- **Role model:** N/A — single-tenant install, no auth surface (MVP1–MVP3).
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A for MVP2 — `audit_log` lands at MVP3. **Conditional note:** if Phase 3 implements *after* MVP3 ships (plausible given the G-2 gate may not clear until well into MVP3 adoption), the manifest-emit step is a state-affecting apply-path action and SHOULD emit an `audit_log` event (e.g., `proposal.normalizer_manifest_emitted`, system-visibility, metadata = `{proposal_id, choice_name, manifest_filename}` — no credentials/tokens). This is flagged here so the implementation-plan stage re-checks the active release at execution time and adds the audit matrix row if MVP3 has landed. Metadata MUST contain no PATs, tokens, or PII.

## 7) Functional requirements

### FR-1: Pure-domain normalizer manifest builder

- Requirement:
  - The system **MUST** ship a pure function `build_normalizer_manifest(choice: str) -> str` (in `backend/app/domain/study/normalizers.py` or a sibling `normalizer_manifest.py`) that returns a deterministic YAML document string given one of Phase 1's `NORMALIZER_CHOICES` values.
  - The function **MUST** raise `ValueError("unknown normalizer: <choice>")` (or reuse Phase 1's identical guard) when `choice ∉ NORMALIZER_CHOICES` — the manifest can never encode a normalizer the runtime `normalize()` can't produce.
  - The manifest document **MUST** conform to the **normative manifest schema** locked in §9 "Normative manifest schema" (D-3-8) — not merely contain those keys "at minimum." The exact top-level keys, key ordering, the `steps[*]` item shape (`{id: <step>, params: {<k>: <v>}}`), the no-op representation (empty `steps`), and the `reference_implementation` structure are all fixed there so operator CI, docs, and tests target one stable contract. Unknown top-level keys are **forbidden** in v1 (a strict schema) — additive evolution goes through a version bump (`relyloop_query_normalizer_manifest_version: 2`), not silent extra keys.
  - For `choice == "none"`, the manifest **MUST** still be well-formed but **MUST** declare an empty `steps` list and a reference-impl marker indicating "no transform" — so the operator's CI consumes a valid (no-op) manifest rather than a missing file. (Mirrors Phase 1's `none`-branch PR-body handling.)
  - The builder **MUST** be deterministic (stable key ordering, stable serialization) so the emitted manifest is byte-stable across runs for a given `choice` (enables clean Git diffs and a byte-equality test).
  - The builder **MUST** be pure: no async, no DB, no httpx, no `openai`, no file I/O.
- Notes: The `steps` vocabulary source is decided in D-3-2 (Phase 2's `NormalizerStep` enum if shipped, else a minimal frozen four-bundle vocabulary). The reference-impl pointer composes with Phase 1's snippet but is not a copy of it.

### FR-2: Manifest shape — separate `{template_name}.query_normalizer.yaml` file

- Requirement (D-3-1 resolution: **separate file**, recommended default locked as engineering judgment):
  - The manifest **MUST** be written to a file named `{template_name}.query_normalizer.yaml`, sibling to `{template_name}.params.json`, under the cluster's `config_path` directory in the cloned config repo.
  - The manifest path **MUST** be computed by a new `_validate_manifest_path(clone_dir, config_path, template_name) -> Path` helper that (1) guards `template_name` is a bare basename — no path separators, no `.`/`..` traversal components (raise `InvalidConfigPathError` otherwise); (2) derives the manifest path as a guaranteed sibling of the validated params path — `params_path.with_name(f"{template_name}.query_normalizer.yaml")` — rather than independently re-joining `config_path`, so the manifest can never land anywhere but next to `params.json`; and (3) re-runs the same `relative_to(clone_root)` containment assertion as `_validate_params_path` for defense-in-depth. A path that escapes the clone root OR a `template_name` carrying separators **MUST** raise `InvalidConfigPathError` (reusing the existing exception).
  - **Why the basename guard matters (closes a gap in the bare clone-root check):** `_validate_params_path`'s `relative_to(clone_root)` proves the path stays *inside* the clone but does NOT prove it is a sibling of `params.json` — a `template_name` like `subdir/foo` would resolve to a different in-clone location. Deriving via `with_name` after the basename guard makes sibling placement structural, not incidental.
  - The manifest **MUST NOT** be inlined as a top-level key inside `params.json`. Rationale (locking D-3-1): `params.json` is consumed verbatim by the operator's deploy pipeline and injected into the template (per apply-path.md); injecting a structured non-parameter object into that file risks template-render breakage in the operator's existing pipeline, whereas a sibling file is purely additive and ignorable by pipelines that don't opt in. A separate file is also the cleaner Git diff and the simpler back-compat story.
- Notes: The `.yaml` extension is chosen over `.json` because the idea brief and parent-spec language consistently describe a "YAML manifest," and YAML is the dominant format for the CI/startup-config files the manifest targets. (If implementation discovers the operator CI ecosystem prefers JSON, that is a doc/format note, not a contract change — the builder's output format is the only thing that flips.)

### FR-3: Manifest-emit step in the `open_pr` worker

- Requirement:
  - In the `open_pr` worker (`backend/workers/git_pr.py`), AFTER `_apply_config_diff` writes `params.json` (Step 10) and BEFORE the commit/push (Step 12), the worker **MUST**, when ALL of the following hold:
    1. the proposal is study-backed (NOT manual — `_render_pr_body_manual` path is excluded),
    2. `config_diff` contains a `query_normalizer` key whose `["to"]` value ∈ `NORMALIZER_CHOICES`,
    3. the back-compat gate (FR-5) is ON,

    compute the manifest path via `_validate_manifest_path`, build the manifest via `build_normalizer_manifest(config_diff["query_normalizer"]["to"])`, write it to that path, and stage it alongside `params.json`.
  - The manifest file **MUST** land in the SAME commit as `params.json` (D-3-3: single commit), staged together via the new `_git_commit_files(clone_dir, [params_path, manifest_path], msg, token)` helper, so a reviewer sees the parameter change and its normalizer manifest atomically. (Rationale: the two artifacts are one logical change; a separate commit fragments the diff and complicates the merge contract.) The existing single-file `_git_commit_file` is NOT reused for the manifest — a second `_git_commit_file` call would produce two commits, violating D-3-3.
  - **Invalid-value handling (defense-in-depth path, reconciled with I-3):** if `config_diff["query_normalizer"]["to"]` is present but NOT in `NORMALIZER_CHOICES` — unreachable in normal flow because Phase 1's FR-2 gate validates the choice at study-create time — the worker **MUST** log a token-redacted warning and SKIP manifest emission, committing `params.json` ALONE (params-only behavior). In this single exempted case the worker **MUST** also render the PR body WITHOUT a manifest-emitted claim (FR-6's gate-OFF / no-manifest branch), so the PR never asserts a manifest was emitted when it wasn't. **This invalid-value skip is explicitly exempt from I-3's both-or-neither rule** — I-3 governs only the valid-choice path; an invalid value is treated as "no manifest to emit," not "manifest emission failed." A `build_normalizer_manifest` raising `ValueError` on a value that passed this check (should never happen) IS an FR-4 failure (`NORMALIZER_MANIFEST_EMIT_FAILED`), aborting before commit.
  - When the gate is OFF, or `query_normalizer` is absent from `config_diff`, the worker **MUST NOT** write a manifest and behaves exactly as today (params-only).

### FR-4: Worker error handling for manifest emission

- Requirement:
  - The system **MUST** define an inline exception `_NormalizerManifestEmitError(ValueError)` in `git_pr.py` following the existing `_ParamNotInTemplateError` / `_ParamsFileNotFoundError` pattern.
  - A failure to compute the manifest path (containment violation), build the manifest, or write the manifest file **MUST** be caught and funneled into the existing token-redacted `pr_open_error` path via a new worker error code `NORMALIZER_MANIFEST_EMIT_FAILED`, leaving the proposal `status='pending'` (retryable) — NOT crashing the worker and NOT pushing a partial commit.
  - Atomicity (I-3): the manifest write **MUST** be staged such that if it fails, the params commit is not pushed in a half-applied state. The simplest correct implementation: build + write the manifest to the clone working tree BEFORE the single `git add`/commit; if the manifest step fails, the worker aborts before committing/pushing anything new.
- Notes: This mirrors how `git push failed` and `PARAM_NOT_IN_TEMPLATE` are already handled — recorded on `proposals.pr_open_error` (existing field; verify exact field name at implementation against the proposal model) with the token redacted.

### FR-5: Back-compat env gate

- Requirement (D-3-4 resolution: **single global Compose env var, default OFF**):
  - The system **MUST** read a single non-secret boolean setting from `Settings` (e.g., `EMIT_NORMALIZER_MANIFEST`, default `false`) controlling whether the manifest-emit step (FR-3) runs.
  - The var **MUST** be a bare (non-secret) env var per CLAUDE.md Absolute Rule #2 (it's non-secret config like `OPENAI_BASE_URL`), read via the existing `Settings` pattern in `backend/app/core/settings.py`, never instantiated directly.
  - Default OFF guarantees: an existing config repo consuming the current `params.json`-only shape sees zero behavior change after this feature deploys. The operator opts in by setting `EMIT_NORMALIZER_MANIFEST=true` once their CI is ready to consume the manifest.
  - When OFF, the PR-body "Operator-side requirement" section retains Phase 1's prose-snippet wording (FR-6 gate branch).
- Notes: A per-repo column is explicitly out of scope (§3). The global gate is the MVP2 mechanism.

### FR-6: PR-body "Operator-side requirement" section rewrite

- Requirement:
  - When the gate (FR-5) is ON AND `config_diff` carries a valid `query_normalizer`, `_render_pr_body_study_backed`'s "Operator-side requirement" section (introduced by Phase 1) **MUST** be rewritten to:
    1. State that RelyLoop has emitted a structured manifest file named `{template_name}.query_normalizer.yaml` in this PR.
    2. State the new merge contract: "Apply the parameters AND wire this normalizer manifest into your query layer's startup config — your CI consumes it directly; no manual snippet copy is required."
    3. **Retain** Phase 1's Python snippet as a clearly-labeled fallback reference (D-3-5: retain-as-fallback) under a sub-heading like "Fallback (if your CI cannot yet consume the manifest)" — so operators on Phase 1's prose path are not regressed.
  - When the gate is OFF, the section **MUST** render exactly as Phase 1 specifies (prose + Python snippet, no manifest reference).
  - When the chosen normalizer is `"none"`, the section **MUST** still render but state that the emitted manifest is a no-op (empty `steps`) and no production change is required — consistent with FR-1's `none`-branch manifest and Phase 1's `none`-branch PR-body handling.
  - The section **MUST NOT** render at all when `config_diff` does not carry `query_normalizer` (unchanged from Phase 1).

### FR-7: Proposal-detail manifest preview (UI)

- Requirement:
  - The proposal-detail page (`ui/src/app/proposals/[id]/page.tsx`) **MUST** render a read-only manifest-preview block (a new component under `ui/src/components/proposals/`) below the existing `<ConfigDiffPanel>` when BOTH: (a) the proposal is study-backed (NOT manual — see the source guard below), AND (b) `proposal.config_diff` contains a `query_normalizer` key.
  - **Manual-proposal guard (reconciles with I-5):** the block **MUST NOT** render for manual (hand-crafted) proposals. By invariant manual proposals don't carry `query_normalizer` (they don't pass through the loop), but FR-7 keys defensively on the proposal's source/type (e.g., `proposal.study_id` present / a `source` discriminator — verify the exact field on the proposal model at implementation) in addition to the `config_diff` key, so an accidentally-seeded `query_normalizer` on a manual proposal never surfaces a preview. A vitest fixture covers a manual proposal carrying a stray `query_normalizer` key → block hidden.
  - **Manifest content source (resolves OQ-1 toward the no-drift option):** the preview's manifest content **MUST NOT** be independently re-implemented in TypeScript in a way that can drift from the backend `build_normalizer_manifest`. Two acceptable implementations, in preference order: (1) **server-rendered (preferred)** — the existing `GET /api/v1/proposals/{id}` response gains an additive read-only `normalizer_manifest_preview: str | null` field populated by `build_normalizer_manifest` (additive field, no breaking shape change); the block renders it verbatim. (2) **client mirror with parity tests (fallback)** — a frontend renderer keyed on a shared manifest schema/version, locked by a golden-fixture parity test that asserts the frontend output byte-matches backend `build_normalizer_manifest` output for every `NORMALIZER_CHOICES` value (fixtures generated FROM the backend builder). OQ-1's recommended default is updated to **option (1)**.
  - The block **MUST** be hidden entirely when `config_diff.query_normalizer` is absent (no empty card).
  - **Gate-OFF copy (resolves Finding-5 ambiguity):** the preview's content is the manifest that WOULD be / WAS emitted; because the frontend has no reliable signal of the per-install `EMIT_NORMALIZER_MANIFEST` value (no API shape change carries it by default — §8.1), the block's helper copy **MUST** be phrased gate-agnostically: it describes the manifest as "the structured normalizer contract for this proposal; RelyLoop emits it into the PR as `{filename}` when manifest emission is enabled for this install." This avoids asserting "a file was emitted" when the gate may be OFF, without needing to plumb the gate value to the frontend.
  - Helper copy **MUST** be sourced from a NEW glossary key (e.g., `proposal.normalizer_manifest`) per CLAUDE.md contextual-help discipline — no inline string. The key text states what the manifest is, that it is emitted when manifest emission is enabled, and that the operator's CI consumes it.
  - The block is informational only; it **MUST NOT** gate the "Open PR" / reject actions and **MUST NOT** modify `config_diff`.
- Notes: This composes with Phase 1's create-study Categorical row and digest advisory — it is a third, proposal-stage surface. No new route. If OQ-1 resolves to option (1), `GET /api/v1/proposals/{id}` gains one additive nullable field — §8.1 updated accordingly.

### FR-8: Documentation updates

- Requirement:
  - [`docs/01_architecture/apply-path.md`](../../../../01_architecture/apply-path.md) **MUST** be extended with a section describing: the normalizer manifest as the first structured non-`params.json` artifact the apply path emits, the `{template_name}.query_normalizer.yaml` filename convention, the `EMIT_NORMALIZER_MANIFEST` gate, and the operator-CI consumption contract. (This is the "material extension" the idea's Capability B flagged — Phase 1 keeps apply-path.md unchanged; Phase 3 changes it.)
  - [`docs/03_runbooks/`](../../../../03_runbooks/) **MUST** gain (or extend an existing runbook with) operator guidance: how to turn on the gate, what the manifest looks like, and a sketch of consuming it in CI.
  - The parent Phase 1 spec's §3 phase-boundary entry and §19 D-1 reference Phase 3; on Phase 3 ship, update the parent's status pointer + this feature's status to Implemented.
  - [`CLAUDE.md`](../../../../../CLAUDE.md) **MUST** document the new `EMIT_NORMALIZER_MANIFEST` env var in the Settings/env section (non-secret config).
  - `state.md` — add the merge one-liner; full narrative to `state_history.md`.

## 8) API and data contract baseline

### 8.1 Endpoint surface

**No new endpoints.** Existing surfaces affected:

| Method | Path | Affected behavior |
|---|---|---|
| `POST` | `/api/v1/proposals/{id}/open_pr` | Triggers the `open_pr` worker, which now ALSO emits `{template_name}.query_normalizer.yaml` when the gate is ON and `config_diff` carries `query_normalizer`. New worker error code: `NORMALIZER_MANIFEST_EMIT_FAILED` (recorded on `proposals.pr_open_error`, NOT an HTTP envelope by default). |
| `GET` | `/api/v1/proposals/{id}` | Returns the existing proposal shape; `query_normalizer` rides inside `config_diff`. **Per FR-7's OQ-1 default (option 1), gains one ADDITIVE read-only nullable field `normalizer_manifest_preview: str | null`** populated by `build_normalizer_manifest` ONLY when the proposal is **study-backed** (NOT manual) AND `config_diff` carries a **valid** `query_normalizer` choice; `null` in every other case — including a manual proposal carrying a stray `query_normalizer` key (the backend mirrors FR-7's source guard so the API never exposes a preview for a manual proposal; the frontend guard is then defense-in-depth) and an out-of-allowlist value. Additive-only — no existing field changes, no breaking shape change; clients ignoring the field are unaffected. If OQ-1 instead resolves to the client-mirror fallback, no field is added. |

### 8.2 Contract rules

- Error body **MUST** include machine-readable `error_code` under `detail` (only relevant if OQ-2 surfaces the gate via an endpoint).
- Worker errors are recorded on the existing `proposals.pr_open_error` field with the token redacted — same pattern as `PARAM_NOT_IN_TEMPLATE` and `git push failed`.
- N/A — no auth surface, no cross-tenant anti-enumeration concerns.

### 8.3 Response examples

No new HTTP error responses by default (the manifest-emit failure is a worker-recorded `pr_open_error`, not an HTTP envelope). If OQ-2 resolves to expose the gate or the failure via an endpoint, the envelope follows the existing shape from [`backend/app/api/errors.py`](../../../../../backend/app/api/errors.py):

```json
{
  "detail": {
    "error_code": "NORMALIZER_MANIFEST_EMIT_FAILED",
    "message": "failed to emit query-normalizer manifest for template <name>",
    "retryable": true
  }
}
```

The `proposals.pr_open_error` recorded value (worker path, default) is a token-redacted human string, e.g. `"normalizer manifest emit failed: manifest path escapes the clone root"`.

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `proposals[*].config_diff.query_normalizer.{from,to}` (GET response) | `none`, `lowercase`, `lowercase+trim`, `lowercase+trim+expand_contractions` | `backend/app/domain/study/normalizers.py` (`NORMALIZER_CHOICES`, **Phase 1 deliverable**) | Manifest builder `build_normalizer_manifest` keys on the same allowlist; the FR-7 manifest-preview block reads `config_diff.query_normalizer.to`. |
| `EMIT_NORMALIZER_MANIFEST` (Compose env) | `true`, `false` (default `false`) | `backend/app/core/settings.py` (`Settings.emit_normalizer_manifest: bool` — NEW) | Not a frontend wire value; operator-set Compose env var only. |
| manifest `steps[*]` vocabulary | per D-3-2: Phase 2's `NormalizerStep` enum values if shipped, else a minimal frozen set (`lowercase`, `trim`, `expand_contractions_en`) | Phase 2 `backend/app/domain/study/search_space.py` (`NormalizerStep`) OR a Phase-3-local frozen tuple | Internal to the manifest builder; not a user-editable wire value. |

The `query_normalizer` choice values are owned and validated by Phase 1 (its FR-2 reservation gate). Phase 3 introduces no new operator-editable enumerated wire value — the only new config is the boolean env gate.

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `NORMALIZER_MANIFEST_EMIT_FAILED` | N/A (worker error → `proposals.pr_open_error`); `400`/`500` only if OQ-2 surfaces it via an endpoint | Manifest path containment failure, build failure, or write failure during the `open_pr` worker. Funneled into the existing token-redacted `pr_open_error` path; proposal stays `pending` (retryable). |

Existing codes `PARAM_NOT_IN_TEMPLATE`, `BRANCH_EXISTS`, `GITHUB_NOT_CONFIGURED`, `INVALID_STATE_TRANSITION` remain unchanged and may fire on adjacent paths. Phase 1's `NORMALIZER_CHOICE_INVALID` / `NORMALIZER_PARAM_SHAPE` / `RESERVED_PARAM_REFERENCED` are owned by Phase 1.

## 9) Data model and state transitions

### New entities

**None.** No new table, no new column in RelyLoop's DB.

The `query_normalizer` value rides inside existing JSONB columns (all introduced by Phase 1's data flow):
- `proposals.config_diff` ([`backend/app/db/models/proposal.py:64`](../../../../../backend/app/db/models/proposal.py), `JSONB NOT NULL`) — the `{from, to}` change Phase 3 reads to build the manifest.

The emitted manifest is a **file in the operator's Git repo**, not a row in RelyLoop's DB.

### Normative manifest schema (v1) — D-3-8

The manifest is the external operator-CI consumption contract, so its shape is locked (not "at minimum"). v1 is a **strict** schema: exactly these top-level keys, in this order; unknown keys are forbidden (additive evolution = a version bump). Format is YAML by default (OQ-3); if OQ-3 flips to JSON the same object shape applies.

Top-level keys (ordered):
1. `relyloop_query_normalizer_manifest_version: 1` (int).
2. `choice: <one of NORMALIZER_CHOICES>` (str).
3. `steps:` — an ordered list; each item is `{id: <step-vocabulary value>, params: {<k>: <v>}}`. `params` is always present (an empty mapping `{}` when the step takes no parameters). Empty list `[]` for the `none` no-op choice.
4. `reference_implementation:` — a mapping `{language: "python", function_name: "normalize_query", source: "relyloop:<choice>"}`. The `source` identifier maps to Phase 1's `_PR_BODY_NORMALIZER_SNIPPETS[<choice>]` entry; it is a pointer/identifier, NOT an inlined snippet (the snippet itself stays in the PR body per FR-6).

Canonical examples (YAML; step vocabulary per D-3-2 — `expand_contractions_en` shown for the Phase-3-local minimal vocabulary):

`choice == "none"`:
```yaml
relyloop_query_normalizer_manifest_version: 1
choice: none
steps: []
reference_implementation:
  language: python
  function_name: normalize_query
  source: relyloop:none
```

`choice == "lowercase+trim"`:
```yaml
relyloop_query_normalizer_manifest_version: 1
choice: lowercase+trim
steps:
  - id: lowercase
    params: {}
  - id: trim
    params: {}
reference_implementation:
  language: python
  function_name: normalize_query
  source: relyloop:lowercase+trim
```

`choice == "lowercase+trim+expand_contractions"`:
```yaml
relyloop_query_normalizer_manifest_version: 1
choice: lowercase+trim+expand_contractions
steps:
  - id: lowercase
    params: {}
  - id: trim
    params: {}
  - id: expand_contractions_en
    params:
      dictionary: builtin_en_30
reference_implementation:
  language: python
  function_name: normalize_query
  source: relyloop:lowercase+trim+expand_contractions
```

The `dictionary: builtin_en_30` param value references Phase 1's frozen 30-entry `_CONTRACTIONS` dictionary by a stable identifier (so the operator's CI knows which dictionary the loop used without inlining all 30 entries). If Phase 2 has shipped its `NormalizerStep` enum (D-3-2), the `id` values use Phase 2's vocabulary instead of the Phase-3-local minimal set, but the object shape is identical.

A unit test (`test_normalizer_manifest.py`) **MUST** assert the emitted YAML parses to exactly this object shape per choice (strict-key assertion — no extra top-level keys), in addition to the determinism/byte-stability assertion.

### Modified entities

**None in the DB.** A new non-secret `Settings.emit_normalizer_manifest: bool` field is added to `backend/app/core/settings.py` (config, not a DB column).

### Required invariants

- **I-1 (gating).** This feature is NOT implemented until G-1 (Phase 1 merged) AND G-2 (operator-friction evidence) both hold. Restated as the release gate in §16.
- **I-2 (manifest ⊆ runtime).** Every manifest `build_normalizer_manifest` produces names a `choice ∈ NORMALIZER_CHOICES` and encodes steps the runtime `normalize(query_text, choice)` actually applies. The manifest can never describe a transform the runtime can't reproduce. Enforced by a unit test that, for each `NORMALIZER_CHOICES` value, asserts the manifest's declared steps correspond to the runtime's behavior (and that an out-of-allowlist choice raises `ValueError`). This is the Phase-3 analogue of Phase 1's I-4 (snippet ≡ runtime).
- **I-3 (atomic emit, valid-choice path).** When the gate is ON and a VALID `query_normalizer` choice is present, the manifest file and `params.json` land in the SAME pushed commit (staged together via `_git_commit_files`), or neither new state is pushed. A manifest build/path/write FAILURE aborts before the commit/push (FR-4), leaving the proposal `pending` and retryable. There is never a pushed commit with `params.json` changed but the manifest missing on the valid-choice path. **Exemption:** the defense-in-depth invalid-value skip (FR-3 — an out-of-allowlist value, unreachable given Phase 1 FR-2) is NOT a failure; it commits `params.json` alone and renders the PR body with no manifest claim. I-3's both-or-neither rule does not apply to that case because there is no valid manifest to emit.
- **I-4 (single emit site).** Only the `open_pr` worker writes the manifest. No other code path (digest worker, orchestrator, adapters, services) emits it. Audit: `grep -rn "build_normalizer_manifest\|query_normalizer.yaml" backend/app backend/workers` returns the builder definition (domain) + its single call site (the `open_pr` worker) and zero other writers.
- **I-5 (manual-proposal exclusion).** `_render_pr_body_manual` and the manual-proposal worker path never emit a manifest.

### State transitions

N/A — no new state machine. Rides the existing `proposal.status` machine (`pending → pr_opened`); a manifest-emit failure keeps the proposal at `pending` (existing failure behavior), it does not introduce a new state.

### Idempotency/replay behavior

- Re-running `open_pr` on a `pending` proposal after a manifest-emit failure re-attempts the full flow (clone/pull, apply config_diff, emit manifest, commit, push). The manifest write is idempotent for a given `choice` (byte-stable per I-2 determinism), so a retry produces the identical manifest file. Re-running on an already-`pr_opened` proposal returns `INVALID_STATE_TRANSITION` (existing behavior, unchanged).

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Path traversal / symlink attack via the manifest filename.** A malicious `config_path` or `template_name` could try to write the manifest outside the clone root. Mitigated by `_validate_manifest_path` mirroring `_validate_params_path`'s `validate_config_path` + `relative_to(clone_root)` containment check (FR-2). No path escapes the clone.
  2. **Token/secret leakage into the manifest, the PR body, or a worker error.** The manifest contains only the normalizer choice + step vocabulary + a reference-impl pointer — no secret material. Worker errors funnel through the existing `redact_token` path before being recorded on `pr_open_error` (FR-4). No PAT or secret can land in the manifest, the commit message, or the error string.
  3. **Manifest drifts from the runtime normalizer**, misleading the operator's CI into applying a transform that differs from what the loop measured. Mitigated by I-2 (manifest ⊆ runtime, enforced by test) and by sharing the single `NORMALIZER_CHOICES` source of truth.
  4. **A half-applied commit** (params changed, manifest missing) misrepresents the production contract. Mitigated by I-3 (atomic emit — both or neither).
  5. **Back-compat break for existing config repos.** A repo whose CI doesn't expect the manifest file could choke. Mitigated by FR-5's default-OFF gate — the manifest is never emitted until the operator opts in.
- **Controls:**
  - Path containment check identical to the existing `params.json` writer.
  - Default-OFF env gate (FR-5).
  - I-2 manifest ≡ runtime test; I-3 atomicity; I-4 single-emit-site grep audit.
  - Token redaction on all worker error strings (existing `redact_token`).
  - Glossary-grounded UI copy (no inline strings).
- **Secrets/key handling:** N/A — the manifest carries no secrets; the per-repo PAT is resolved by the existing worker path and never touches the manifest.
- **Auditability:** The manifest file in GitHub is the human-readable record of the emitted normalizer contract; `proposals.config_diff` records the choice. (Plus the conditional MVP3 `audit_log` event per §6 if Phase 3 ships post-MVP3.)
- **Data retention/deletion/export impact:** None — no new persisted RelyLoop state beyond a config flag; the manifest lives in the operator's repo.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** One surface — the **proposal-detail page** (`/proposals/[id]`), below the existing config-diff table. No new route, tab, or modal.
- **Labeling taxonomy:**
  - Manifest-preview block title: "Query normalizer manifest" (matches "Config diff" sentence-case sibling).
  - PR-body section title: `## Operator-side requirement` (unchanged from Phase 1; the body text is rewritten).
- **Content hierarchy:** Proposal-detail page order: proposal header → PR panel → config-diff table → **(NEW) manifest-preview block (when present)** → suggested follow-ups. The manifest block sits directly below config-diff because it is the structured complement to the `query_normalizer` row in that table.
- **Progressive disclosure:** The manifest block is hidden entirely when `config_diff.query_normalizer` is absent. When present, it shows the target filename + the manifest YAML preview inline (no collapse needed — the manifest is short).
- **Relationship to existing pages:** Extends the existing proposal-detail page; composes with Phase 1's create-study Categorical row + digest advisory (different pages).

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| "Query normalizer manifest" block heading | "The structured normalizer contract for this proposal. When manifest emission is enabled for this install, RelyLoop emits it into the PR so your CI can apply the winning query normalizer automatically — no manual snippet copy required." (gate-agnostic per FR-7 — does NOT assert a file was emitted, since the preview renders regardless of the per-install `EMIT_NORMALIZER_MANIFEST` value) | hover info icon | top | `proposal.normalizer_manifest` (NEW) |

The new glossary key ships in the FR-7 frontend story and passes the existing length/no-jargon lint at `ui/src/__tests__/lib/glossary.test.ts`.

### Primary flows

1. **Operator enables the gate.** Operator sets `EMIT_NORMALIZER_MANIFEST=true` in their Compose `.env` once their CI can consume the manifest. (Default OFF until then.)
2. **Loop runs a normalizer-tuning study (Phase 1) and the winner includes a non-`none` normalizer.** The proposal's `config_diff` carries `query_normalizer`.
3. **Operator opens the proposal PR.** The `open_pr` worker applies `params.json`, builds the manifest from `config_diff["query_normalizer"]["to"]`, writes `{template_name}.query_normalizer.yaml`, and pushes both in one commit. The PR body's "Operator-side requirement" section names the manifest file and the new merge contract (snippet retained as fallback).
4. **Operator's CI consumes the manifest.** On merge, the operator's CI parses the manifest YAML and wires the normalizer into the query layer's startup config. Production parity achieved without a manual snippet copy.
5. **Operator reviews on the proposal-detail page.** The manifest-preview block shows the target filename + manifest content alongside the config diff.

### Edge/error flows

- **Gate OFF** → no manifest emitted; PR body retains Phase 1's prose+snippet wording; the manifest-preview block still renders on the proposal page if `config_diff` carries `query_normalizer` (the value + the `normalizer_manifest_preview` field exist regardless of the gate), but its gate-agnostic copy (FR-7) describes the manifest as "emitted when manifest emission is enabled for this install" rather than asserting a file was written — so the operator is never misled when the gate is OFF.
- **Winning normalizer is `none`** → manifest still emitted (gate ON) with empty `steps`; PR body + preview state "no-op / no production change required."
- **Manifest path escapes the clone root** → `_validate_manifest_path` raises `InvalidConfigPathError` → `NORMALIZER_MANIFEST_EMIT_FAILED` on `pr_open_error`; proposal stays `pending`; nothing pushed (I-3).
- **Manifest write fails (disk/permission)** → `_NormalizerManifestEmitError` → `NORMALIZER_MANIFEST_EMIT_FAILED`; proposal stays `pending`; nothing pushed.
- **Out-of-allowlist `query_normalizer` value reaches the worker** (unreachable given Phase 1 FR-2) → logged warning, manifest skipped, params-only behavior (defense-in-depth).
- **Manual (hand-crafted) proposal** → no manifest, no preview block (I-5).
- **`config_diff` lacks `query_normalizer`** → no manifest, no PR section, no preview block (unchanged behavior).

## 12) Given/When/Then acceptance criteria

### AC-0: Gating is documented and honored (design-ahead)

- Given this spec and its implementation plan
- When a future session considers `/impl-execute`
- Then the spec + plan state that implementation is blocked until G-1 (Phase 1 merged) AND G-2 (operator-friction evidence) both hold, and the release gate in §16 lists both
- Example values: G-1 verified via `grep -rn "NORMALIZER_CHOICES" backend/app` returning the Phase 1 symbol on `main`; G-2 verified via a cited friction artifact (issue/survey/feedback).

### AC-1: Manifest builder — pure function over the allowlist

- Given `build_normalizer_manifest`
- When called with `"lowercase+trim+expand_contractions"`
- Then it returns a deterministic YAML string that parses to EXACTLY the §9 normative v1 object shape for that choice (strict: `relyloop_query_normalizer_manifest_version: 1`, `choice`, ordered `steps[*]` of `{id, params}`, `reference_implementation: {language, function_name, source}`, no extra top-level keys)
- Example values:
  - Input: `build_normalizer_manifest("none")` → Expected: parses to the §9 `none` example (empty `steps: []`, `source: relyloop:none`)
  - Input: `build_normalizer_manifest("lowercase+trim")` → Expected: parses to the §9 `lowercase+trim` example (two steps, both `params: {}`)
  - Input: `build_normalizer_manifest("stem")` → Expected: raises `ValueError("unknown normalizer: stem")`
  - Determinism: two calls with the same choice return byte-identical strings.
  - Strictness: the parsed object has no top-level key beyond the four normative keys.

### AC-2: Manifest ⊆ runtime (I-2)

- Given the manifest builder and Phase 1's runtime `normalize(...)`
- When the test iterates every `NORMALIZER_CHOICES` value
- Then each manifest's declared steps correspond to the transform the runtime applies for that choice (e.g., the `lowercase+trim` manifest declares lowercase-then-trim and the runtime applies exactly that), and no manifest names a choice outside `NORMALIZER_CHOICES`

### AC-3: Worker emits the manifest file when gate ON

- Given `EMIT_NORMALIZER_MANIFEST=true`, a study-backed proposal whose `config_diff` includes `{"query_normalizer": {"from": "none", "to": "lowercase+trim"}}`, and a local git fixture config repo
- When the `open_pr` worker runs
- Then the cloned repo contains BOTH `{template_name}.params.json` (with the applied params) AND `{template_name}.query_normalizer.yaml` (the built manifest), and both are present in the single pushed commit

### AC-4: Worker does NOT emit the manifest when gate OFF

- Given `EMIT_NORMALIZER_MANIFEST=false` and the same proposal as AC-3
- When the `open_pr` worker runs
- Then the cloned repo contains `{template_name}.params.json` only; no `.query_normalizer.yaml` file is written; behavior is byte-identical to today's params-only worker

### AC-5: Worker skips manifest when `query_normalizer` absent

- Given the gate ON and a proposal whose `config_diff` does NOT contain `query_normalizer`
- When the `open_pr` worker runs
- Then no manifest file is written and the PR body contains no "Operator-side requirement" section

### AC-6: Manifest-emit failure → pending, no partial push (I-3)

- Given the gate ON and a `_validate_manifest_path` containment violation (simulated symlink/traversal)
- When the `open_pr` worker runs
- Then the proposal stays `status='pending'`, `pr_open_error` records a token-redacted `NORMALIZER_MANIFEST_EMIT_FAILED` message, and nothing is pushed (no commit with `params.json` changed but manifest missing)

### AC-7: PR body references the manifest when gate ON

- Given the gate ON and a proposal whose `config_diff` carries `query_normalizer = {..., "to": "lowercase+trim"}`
- When `_render_pr_body_study_backed` renders
- Then the "Operator-side requirement" section names `{template_name}.query_normalizer.yaml`, states the "your CI consumes it; no copy required" merge contract, and retains a clearly-labeled fallback Python snippet

### AC-8: PR body retains Phase 1 wording when gate OFF

- Given the gate OFF and the same proposal as AC-7
- When `_render_pr_body_study_backed` renders
- Then the section renders Phase 1's prose+snippet wording with NO manifest-filename reference

### AC-9: PR body `none`-branch (gate ON)

- Given the gate ON and `config_diff.query_normalizer.to = "none"`
- When `_render_pr_body_study_backed` renders
- Then the section states the manifest is a no-op (empty steps) and no production change is required

### AC-10: Proposal-detail manifest preview visible

- Given a proposal whose `config_diff.query_normalizer` is present
- When the proposal-detail page renders
- Then the "Query normalizer manifest" block renders below the config-diff table, showing the target filename and a manifest preview, with the helper copy sourced from glossary key `proposal.normalizer_manifest`

### AC-11: Proposal-detail manifest preview hidden when absent or manual

- Given a proposal whose `config_diff` lacks `query_normalizer`
- When the proposal-detail page renders
- Then the manifest block is NOT rendered (no empty card)
- And: Given a MANUAL proposal that (defensively) carries a stray `query_normalizer` key in `config_diff`
- When the proposal-detail page renders
- Then the manifest block is still NOT rendered (the FR-7 source guard excludes manual proposals — I-5)

### AC-11b: Manifest preview source has no drift (OQ-1 option 1)

- Given OQ-1 resolved to the server-rendered field
- When `GET /api/v1/proposals/{id}` returns a STUDY-BACKED proposal with a valid `query_normalizer` in `config_diff`
- Then `normalizer_manifest_preview` is the exact string `build_normalizer_manifest(config_diff.query_normalizer.to)` produces
- And it is `null` when: `query_normalizer` is absent; the value is out-of-allowlist; OR the proposal is MANUAL even if it carries a stray `query_normalizer` key (backend source guard mirrors FR-7)
- (If OQ-1 resolved to the client mirror: a golden-fixture parity test asserts the TS renderer output byte-matches the backend builder for every `NORMALIZER_CHOICES` value.)

### AC-12: Single emit site (I-4)

- Given the codebase after implementation
- When `grep -rn "build_normalizer_manifest\|query_normalizer\.yaml" backend/app backend/workers` runs
- Then the only writer is the `open_pr` worker; the builder lives in the domain module; no other service/worker/adapter emits the manifest

### AC-13: End-to-end — manifest reaches the PR (real-backend)

- Given a fresh stack with `EMIT_NORMALIZER_MANIFEST=true`, a registered ES cluster + config repo, a Phase-1 normalizer-tuning study run to completion with a non-`none` winner, and a test config repo
- When the operator opens the proposal PR via the UI and inspects the PR + proposal-detail page
- Then the proposal-detail page shows the manifest preview, the pushed PR contains `{template_name}.query_normalizer.yaml`, and the PR body names the manifest file
- Test path: extend Phase 1's `ui/tests/e2e/query-normalization.spec.ts` or add a sibling real-backend spec (no `page.route()` mocking)

## 13) Non-functional requirements

- **Performance:** The manifest builder is one deterministic in-memory serialization (sub-millisecond) plus one extra small-file write + `git add` in the worker — negligible against the existing clone/push round-trip. No SLA impact.
- **Reliability:** No new runtime failure mode on the loop path (the manifest is apply-path-only). The worker's new failure mode (manifest emit) is isolated to the existing `pr_open_error` retry path; the study and its trials are unaffected.
- **Operability:** One new non-secret env var (`EMIT_NORMALIZER_MANIFEST`); no new metric/alert. The manifest is observable in the pushed commit + the proposal-detail preview.
- **Accessibility/usability:** The manifest-preview block uses existing card primitives; the one new glossary entry passes the length/no-jargon lint.

## 14) Test strategy requirements

Per CLAUDE.md "Testing Conventions" (every layer touched needs coverage):

- **Unit tests** (`backend/tests/unit/`):
  - `test_normalizer_manifest.py` (NEW) — `build_normalizer_manifest` over all `NORMALIZER_CHOICES` (well-formedness, determinism/byte-stability, `none`-branch empty steps, `ValueError` on out-of-allowlist). Covers AC-1.
  - `test_normalizer_manifest_runtime_parity.py` (NEW) — I-2: manifest steps ≡ runtime `normalize` behavior for each choice. Covers AC-2.
  - `test_git_pr_body_manifest.py` (NEW or augment Phase 1's `test_git_pr_body.py`) — `_render_pr_body_study_backed` over {gate ON + non-none; gate ON + none; gate OFF; key absent}. Covers AC-7, AC-8, AC-9, AC-5 (PR-body half).
- **Integration tests** (`backend/tests/integration/`):
  - `test_open_pr_normalizer_manifest.py` (NEW) — `open_pr` worker against a local git fixture repo over {gate ON → both files staged in ONE commit (assert the pushed branch has a single new commit touching both `params.json` and the `.yaml`); gate OFF → params-only; containment violation / separator-bearing `template_name` → pending + `pr_open_error`, nothing pushed; invalid-but-present `query_normalizer` value (defense-in-depth) → params-only commit + PR body asserts NO manifest claim (I-3 exemption per FR-3)}. Covers AC-3, AC-4, AC-6, AC-12 (emit-site half), and the FR-3 invalid-value reconciliation.
- **Contract tests** (`backend/tests/contract/`):
  - `test_proposals_normalizer_manifest_preview_contract.py` (NEW, OQ-1 option-1) — `GET /api/v1/proposals/{id}` returns `normalizer_manifest_preview` as the exact `build_normalizer_manifest(...)` string for a study-backed proposal with a valid `query_normalizer`; `null` for {absent key; out-of-allowlist value; manual proposal with a stray key}; the field is present as an additive nullable in the response shape. Covers AC-11b backend half + Finding-1 (cycle-2) source-guard contract. (If OQ-1 resolves to the client mirror, this test is replaced by the golden-fixture parity test in frontend vitest.)
  - `NORMALIZER_MANIFEST_EMIT_FAILED` envelope test — conditional (OQ-2): only if the gate/failure is surfaced via an endpoint. Default — none needed (worker-recorded error on `pr_open_error`).
- **E2E tests** (`ui/tests/e2e/`):
  - Extend Phase 1's `query-normalization.spec.ts` (or sibling, NEW) — real-backend: gate ON, run a normalizer study, open the PR, assert the manifest preview + the pushed manifest file + the PR-body reference. Covers AC-13. No `page.route()` mocking.
- **Frontend vitest** (`ui/src/__tests__/`):
  - `proposal-normalizer-manifest.test.tsx` (NEW) — manifest-preview block renders when study-backed + `config_diff.query_normalizer` present; hidden when absent; hidden for a manual proposal carrying a stray `query_normalizer` (I-5 source guard); helper copy from the glossary key; gate-agnostic wording. Covers AC-10, AC-11. Plus the OQ-1 parity assertion (server-field verbatim render, or golden-fixture parity if client-mirror). Covers AC-11b.

## 15) Documentation update requirements

- `docs/01_architecture/apply-path.md` — Add a "Structured normalizer manifest (Phase 3)" section: the manifest as the first non-`params.json` structured artifact, the filename convention, the `EMIT_NORMALIZER_MANIFEST` gate, the operator-CI consumption contract (per FR-8). **This is the material apply-path.md extension the idea flagged.**
- `docs/03_runbooks/` — Add/extend a runbook: enabling the gate + a CI-consumption sketch.
- `docs/02_product/` — No update; no new persona-level capability shift (the relevance-engineer workflow is unchanged; only the hand-off mechanism improves).
- `docs/04_security/` — No update; no new secret/data-flow surface (the path-containment + token-redaction controls are reuses, noted in §10).
- `docs/05_quality/testing.md` — No update; existing conventions cover the new layers.
- `CLAUDE.md` — Document `EMIT_NORMALIZER_MANIFEST` in the Settings/env section.
- The parent `feat_query_normalization_tuning` spec §3 + §19 D-1 status pointers — update on Phase 3 ship.
- `state.md` — merge one-liner; narrative to `state_history.md`.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** The `EMIT_NORMALIZER_MANIFEST` env gate IS the staged rollout — default OFF, operator opts in per install when their CI is ready. No global flip.
- **Migration/backfill expectations:** None in RelyLoop's DB. Operators may add the manifest to their own config-repo CI (their concern, documented).
- **Operational readiness gates:** None new — the loop path is untouched.
- **Release gate (the two hard gates — restating I-1):**
  - **G-1: Phase 1 (`feat_query_normalization_tuning`) merged to `main`** — verified by the Phase 1 symbols existing in `backend/app/domain/study/normalizers.py`.
  - **G-2: operator-friction evidence materialized** — verified by a cited friction artifact (GitHub issue / in-product feedback / adoption survey / design-partner escalation).
  - Plus the standard per-PR gates once unblocked: all AC pass in CI; 80% backend coverage; frontend ESLint+tsc+vitest+Next build; glossary lints; cross-model GPT-5.5 review converged; I-4 grep audit clean.
- **Do NOT `/impl-execute` until G-1 AND G-2 both hold.**

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2 | Story 1: manifest builder (domain) | `test_normalizer_manifest.py`, `test_normalizer_manifest_runtime_parity.py` | — |
| FR-2 | AC-3, AC-6 | Story 2: manifest path + containment helper | `test_open_pr_normalizer_manifest.py` | `apply-path.md` |
| FR-3 | AC-3, AC-4, AC-5, AC-12 | Story 2: worker emit step | `test_open_pr_normalizer_manifest.py` | `apply-path.md` |
| FR-4 | AC-6 | Story 2: worker error handling | `test_open_pr_normalizer_manifest.py` | `docs/03_runbooks/` |
| FR-5 | AC-3, AC-4, AC-8 | Story 3: env gate (Settings) | `test_open_pr_normalizer_manifest.py` | `CLAUDE.md` |
| FR-6 | AC-7, AC-8, AC-9 | Story 4: PR-body rewrite | `test_git_pr_body_manifest.py` | — |
| FR-7 | AC-10, AC-11 | Story 5: proposal-detail preview + glossary | `proposal-normalizer-manifest.test.tsx`, E2E | — |
| FR-8 | AC-0 | Story 6: docs + gate documentation | — | `apply-path.md`, `docs/03_runbooks/`, `CLAUDE.md`, parent spec |
| — | AC-13 | Story 7: real-backend E2E | `query-normalization.spec.ts` (extend) | — |

## 18) Definition of feature done

- [ ] **Gates G-1 + G-2 both satisfied** (Phase 1 merged + operator-friction evidence cited) — checked BEFORE any story is implemented.
- [ ] All acceptance criteria (AC-0 through AC-13) pass in CI.
- [ ] All test layers (unit/integration/contract-if-applicable/e2e) green.
- [ ] Documentation updates per FR-8 merged (incl. `apply-path.md` extension + `CLAUDE.md` env var).
- [ ] Rollout gates from §16 satisfied.
- [ ] No open questions remain in §19.
- [ ] `state.md` updated with the merge one-liner.

## 19) Open questions and decision log

### Open questions

These remain genuine product/operator-preference forks that cannot be unilaterally locked at design-ahead time. Each has a recommended default the implementation plan assumes unless the operator overrides at G-2-clearing time.

- **OQ-1 — Manifest-preview data source on the proposal page.** Does the API serve the rendered manifest string on `GET /api/v1/proposals/{id}` (additive nullable `normalizer_manifest_preview` field, populated by the backend `build_normalizer_manifest`), OR does the frontend re-derive it from `config_diff.query_normalizer.to` via a TS mirror locked by golden-fixture parity tests? **Recommended default (updated after GPT-5.5 cycle-1 Finding-3): option (1), server-rendered additive field** — it eliminates the drift risk of a second manifest implementation in TS (the same I-2 drift threat the manifest builder exists to prevent), and an additive nullable field is not a breaking shape change. The client-mirror fallback is acceptable only with golden-fixture parity tests generated from the backend builder. Owner: Engineering — Due: before implementation plan finalization (revisit at G-2 clear).
- **OQ-2 — Surface the gate/failure via an endpoint?** Should `NORMALIZER_MANIFEST_EMIT_FAILED` ever appear as an HTTP envelope (e.g., a synchronous validation on `open_pr` before enqueue), or remain worker-only on `pr_open_error`? **Recommended default: worker-only** (matches the existing `PARAM_NOT_IN_TEMPLATE`/`git push failed` pattern; the failure is intrinsically async). Owner: Engineering — Due: before implementation plan finalization.
- **OQ-3 — Manifest format: YAML vs JSON.** The idea + parent spec say "YAML manifest"; the existing apply-path artifact is JSON (`params.json`). **Recommended default: YAML** (FR-2 rationale — dominant CI/startup-config format; the builder's output format is the only thing that flips if operators prefer JSON). Owner: Product/operator — Due: at G-2 clear, informed by the operators whose friction motivated the feature.

### Decision log

- **2026-06-01 — D-3-1: Manifest shape — separate sibling file, not inline in `params.json`.** Locked as engineering judgment. The manifest is written to `{template_name}.query_normalizer.yaml` sibling to `params.json`. Rationale: `params.json` is consumed verbatim by the operator's existing deploy pipeline and injected into the template (apply-path.md); inlining a structured non-parameter object risks breaking that injection, whereas a sibling file is purely additive and ignorable by pipelines that don't opt in. A separate file also yields a cleaner Git diff and a simpler back-compat story. The idea's Capability B flagged this as needing an "operator preference signal"; the back-compat + injection-safety argument is strong enough to lock the default now while leaving the format (YAML vs JSON) as OQ-3.

- **2026-06-01 — D-3-2: Step vocabulary source.** Manifest `steps` use Phase 2's `NormalizerStep` enum **if Phase 2 (`feat_query_normalizer_typed_pipeline`) has shipped at Phase 3 implementation time**; otherwise Phase 3 defines a minimal frozen step vocabulary (`lowercase`, `trim`, `expand_contractions_en`) covering exactly the four Phase 1 bundles. Rationale: avoid two competing vocabularies for the same concept; but Phase 3 must not hard-depend on Phase 2 (which is idea-only). The implementation plan checks Phase 2's status at execution time and picks the source. Locked as engineering judgment with a runtime branch.

- **2026-06-01 — D-3-3: Single commit for params + manifest.** Both artifacts land in the SAME pushed commit, staged together via a new multi-file commit helper `_git_commit_files(clone_dir, [params_path, manifest_path], msg, token)`. The existing single-file `_git_commit_file` is NOT reused for the manifest — a second `_git_commit_file` call would produce two separate commits, fragmenting the diff and breaking the "one logical change" atomicity. Rationale: a reviewer sees the parameter change and its normalizer contract atomically; underpins I-3. Locked as engineering judgment. (Updated after GPT-5.5 cycle-1 Finding-1, which caught the §2 prose still floating the "second `_git_commit_file`" option.)

- **2026-06-01 — D-3-4: Back-compat env gate — single global Compose var, default OFF.** `EMIT_NORMALIZER_MANIFEST` (non-secret bare env var, default `false`). Rationale: guarantees zero behavior change for existing config repos until the operator opts in; a per-repo column needs a migration + UI not justified in MVP2 and is explicitly out of scope. Locked as engineering judgment.

- **2026-06-01 — D-3-5: Retain Phase 1's Python snippet as a fallback when the gate is ON.** The rewritten "Operator-side requirement" section leads with the manifest-consumption contract but keeps the Python snippet under a "Fallback" sub-heading. Rationale: dropping it regresses operators whose CI can't yet consume the manifest; the snippet is short and already maintained by Phase 1's I-4 test. Locked as engineering judgment.

- **2026-06-01 — D-3-6: Manifest builder lives in the normalizer domain module, single emit site in the worker (I-4).** The builder is a pure-domain function alongside Phase 1's `normalize()` + `NORMALIZER_CHOICES`; the only writer is the `open_pr` worker. Rationale: single source of truth for the normalizer definition; confines I/O to the worker; mirrors Phase 1's I-3 single-PR-body-site discipline. Locked as engineering judgment.

- **2026-06-01 — D-3-8: Normative manifest schema locked (strict v1).** The manifest is the external operator-CI consumption contract, so §9 "Normative manifest schema" fixes the exact top-level keys + ordering, the `steps[*]` item shape `{id, params}`, the no-op (`steps: []`) representation, and the `reference_implementation` structure. v1 is strict — unknown top-level keys forbidden; additive evolution goes through a version bump. Rationale (GPT-5.5 cycle-3 finding): FR-1's earlier "at minimum" wording let implementers produce incompatible-but-compliant YAML, undermining the stable contract operator CI and tests target. Locking a concrete example per choice is exactly the design-ahead value this spec provides. Format (YAML vs JSON) remains OQ-3; the object shape is format-independent. Locked as engineering judgment.

- **2026-06-01 — D-3-7: No reference consumer / parser ships.** RelyLoop emits the manifest + documents the consumption contract; it ships no GitHub Action / parser library / SDK. Rationale: scope discipline — emitting the structured artifact is the friction-closing step; a reference consumer is a speculative Phase 3.5 follow-on if operators ask. Locked as engineering judgment.
