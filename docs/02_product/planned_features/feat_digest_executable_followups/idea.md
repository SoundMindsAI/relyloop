# Executable Digest Follow-ups — turn `suggested_followups` from dead narrative text into structured proposals an operator can run with one click

**Date:** 2026-05-21
**Status:** Idea — surfaced during the 2026-05-21 Karpathy-loop audit.
**Priority:** P2 — turns LLM-suggested followups from dead text into actionable proposals. Medium-scope feature; needs an LLM-output schema change + new UI affordance. High value once it lands but no immediate pain pushing it now.
**Origin:** Standalone audit at `~/.claude/plans/compressed-sparking-hamming.md` — recommendation #4. The audit observation: the digest worker's LLM output already includes `suggested_followups`, but the field is shaped as plain strings, rendered in the proposals UI as bullet text, and has no path back into `create_study` or `propose_search_space`. Operators read suggestions like "narrow the title_boost range to [0.5, 3.0]" and have to manually translate them into a new study configuration.
**Depends on:** None. Composes with [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md) (which automates the deterministic followup); this feature handles the **LLM-suggested** followups separately.

## Problem

The digest worker's LLM contract at [`backend/workers/digest.py:168-189`](../../../../backend/workers/digest.py) defines `suggested_followups` as a flat `array of string`:

```python
DIGEST_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "suggested_followups": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
        },
    },
    ...
}
```

The strings are LLM-generated freeform — typical examples (from real digest outputs):

- "Try narrowing `title_boost` to the range [1.5, 3.0] where the top-decile trials clustered."
- "Investigate the `tie_breaker` parameter — its importance was 0.18 but the search space only sampled three values."
- "Add a `category_boost` parameter to the template since several winning trials suggest category prioritization matters."

These suggestions are useful — but **operationally inert**. They render as bullet text on the proposal detail page at [`ui/src/app/proposals/[id]/page.tsx`](../../../../ui/src/app/proposals/%5Bid%5D/page.tsx). The operator must:

1. Read each suggestion.
2. Translate it into a `search_space` JSON manually.
3. Open the create-study wizard.
4. Re-enter cluster, target, template, query set, judgment list, objective.
5. Paste the translated `search_space`.
6. Hit Submit.

That's the 6-step manual workflow every overnight digest produces *up to 5 times*. The Karpathy-loop equivalent is one click: "Run this followup." The data the LLM has at digest time is rich enough to populate a `CreateStudyRequest` deterministically — the only missing piece is the JSON structure to carry it.

The audit's framing: this is the **smaller** of the two compounding gaps. [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md) handles the *deterministic* compounding (Optuna's TPE narrowed around a winner). This feature handles the *LLM-suggested* compounding (the model spotting patterns Optuna can't, like "the importance signal suggests adding a new dimension"). Both are needed; they cover orthogonal failure modes.

## Proposed capabilities

Tiered. Tier A reshapes the LLM output and adds the "Run this followup" button for the **narrow** kind (same template, modified search space). Tier B extends to `swap_template` (different template). Tier C is a stretch goal — allowing the LLM to propose template edits.

### Tier A — structured followups for "narrow / widen" within the same template

- **New LLM output schema** in [`backend/workers/digest.py:168-189`](../../../../backend/workers/digest.py):
  ```python
  {
      "narrative": str,
      "suggested_followups": [
          {
              "kind": "narrow" | "widen" | "text",
              "rationale": str,  # human-readable, always present
              "search_space": SearchSpace | None,  # required for narrow/widen, null for text
          }
      ]
  }
  ```
- **Backward-compatible read path.** Old digests (pre-migration) have `suggested_followups: list[str]`. Reader code wraps plain strings as `{kind: "text", rationale: <string>, search_space: null}` so the UI surface handles both shapes uniformly. No backfill required.
- **LLM prompt update** in [`prompts/digest_narrative.user.jinja`](../../../../prompts/digest_narrative.user.jinja) + [`prompts/digest_narrative.system.md`](../../../../prompts/digest_narrative.system.md):
  - System prompt gains a section explaining the three kinds and when to use each. "Narrow" = the prior search space was too wide and the winner sits in a sub-region; emit the narrower bounds. "Widen" = the winner is at an edge of the prior space (`= low` or `= high`); emit broader bounds. "Text" = a suggestion that requires operator judgment (e.g., "consider adding a new parameter to the template").
  - User template renders the parent study's `search_space` as a structured input the LLM can transform, not just narrative.
- **Validator** at [`backend/app/domain/study/search_space.py`](../../../../backend/app/domain/study/search_space.py): the existing `SearchSpace` Pydantic model already validates structure + cardinality. Use it directly to validate each followup's `search_space` field at digest-persist time; invalid ones get the `kind` downgraded to `"text"` with `rationale = "[validation failed: <error>] " + original_rationale` so the operator still sees the intent.
- **UI surface** at [`ui/src/app/proposals/[id]/page.tsx`](../../../../ui/src/app/proposals/%5Bid%5D/page.tsx):
  - "Narrow"/"Widen" followups render as a card with: rationale text, a collapsed "Show search space" detail (renders the diff vs parent study), and a primary "Run this followup" button.
  - "Run this followup" pre-fills the create-study modal with: parent study's cluster/target/template/query_set/judgment_list/objective + the LLM's proposed `search_space` + parent's stop conditions. Operator reviews + submits.
  - "Text" followups render unchanged — bullet text. The kind discriminator means freeform suggestions stay supported indefinitely.
- **Traceability.** New nullable column `studies.parent_proposal_followup_index: int | None` records "this study was created from followup #N of proposal X." Lets the UI render "Study A.2 was suggested by digest from proposal B at index 3." Helps the team measure whether LLM-suggested followups produce wins.

### Tier B — `swap_template` followups

- **Additional `kind: "swap_template"`** carrying `template_id: UUID` + a remapped `search_space`. Lets the LLM say "this query template is a better fit for the observed traffic — try template X."
- **Cross-template search-space remapping.** The hard part: when swapping templates, the prior winner's params don't all map onto the new template's `declared_params`. A new domain helper at [`backend/app/domain/study/template_swap.py`](../../../../backend/app/domain/study/template_swap.py) computes the intersection (common param names) and the disjoint set (new params get default heuristic bounds per [`backend/app/domain/study/search_space_defaults.py`](../../../../backend/app/domain/study/search_space_defaults.py); removed params are dropped).
- **LLM prompt extension** to teach the model when to suggest a swap (typically: parameter-importance distribution is highly skewed, suggesting some params are dead weight; OR several winning trials cluster around a sub-set of params that map cleanly onto a different template's declared params).
- **UI surface:** swap-template followups render with a side-by-side comparison of the two templates' `declared_params` before the operator commits.

### Tier C (stretch / probably deferred) — template-edit suggestions

- **`kind: "edit_template"`** carrying a proposed JSON-patch on the parent template's `body_jsonata` (or equivalent). The LLM could suggest "add a `category^2` field-boost to the template body." Today templates are operator-authored only; this would let LLM suggestions flow into template edits with an explicit review step.
- **Likely out of scope for MVP1.** Template edits change query rendering semantics — a much larger trust-and-validation surface than search-space narrowing. Captured here to acknowledge the natural extension; feature spec defers.

### Out of scope for Tier A/B

- **Auto-running followups without operator click.** That's [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md). This feature stays in the "human clicks one button" lane — the LLM proposes; the operator commits.
- **Followups that span multiple studies.** A meta-followup like "run studies A.1 and A.2 in parallel with different starting points" would need its own surface. Not now.
- **Persistence of "I tried this LLM followup and it didn't help."** A negative-result feedback loop into future LLM prompts (so the model learns the operator's preferences) is an interesting MVP4 idea, gated on Langfuse. Out of scope now.

## Scope signals

- **Backend:** ~400 LOC. New Pydantic models for the followup discriminated union (~30) + LLM prompt updates (~60 in `.system.md` + `.user.jinja`) + validator at digest-persist time (~40) + new `parent_proposal_followup_index` column + migration (~30) + service-layer "create study from followup" helper (~80) + tests across unit/integration/contract (~150).
- **Frontend:** ~400 LOC. Followup card component with kind discriminator (~150) + "Run this followup" prefill workflow (~80) + search-space diff renderer (~100) + tests (~70). Tier B adds ~200 LOC for the swap-template comparison.
- **Migration:** one Alembic migration adding `studies.parent_proposal_followup_index INT NULL`. Strictly additive. Round-trip-clean.
- **Config:** none.
- **Audit events:** N/A (MVP1). At MVP2: `digest.followup_run_clicked` + `study.created_from_followup` as canonical audit events.
- **Tests:**
  - Unit: discriminated-union parsing; validator downgrade on bad `search_space`; old-shape string-array backward compatibility.
  - Integration: digest LLM round-trip via stub returns structured followups; "create study from followup" copies the right parent fields.
  - Contract: digest response shape includes the new union.
  - E2E (Playwright): one happy-path spec — open a proposal with a `narrow` followup, click "Run this followup," confirm the create-study modal pre-populates correctly.

## Why not inline today

1. **LLM-contract change.** Reshaping `suggested_followups` from `string[]` to a discriminated union touches the response schema, the prompt files, the validator, the digest worker's parse logic, the storage representation in `digests.followups` JSONB, AND the UI renderer. Multiple coordinated surfaces — outside drive-by budget.
2. **Backward compatibility.** Existing digests in the DB have the old shape. The read path needs an adapter that wraps old strings into the new structure. Small but real — easy to get wrong as a drive-by.
3. **Real UX design surface.** The "Run this followup" workflow is a new top-level user action — how it renders, what it pre-fills, what it shows in the search-space diff are decisions worth scrutinizing in a spec.
4. **Composes with another planned feature.** [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md) and this idea cover orthogonal compounding paths (deterministic vs LLM-suggested). Shipping them in coordinated order — auto-followup first to establish the autonomy trust model, then this to add LLM-suggested manual overrides — gives reviewers a coherent story. Either could ship first, but the coordination is worth planning, not improvising.

## Relationship to other work

- **Most-leveraged in combination with [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md)** — the auto-chain provides the deterministic "narrow around winner" path; this feature adds the LLM-suggested "but consider widening on this axis" path. Together they cover what Karpathy's per-experiment agent does (propose a single change per experiment, then evaluate) — Optuna's TPE handles the within-study sampling, and these two features handle the across-study hypothesis evolution.
- **Adjacent to [`feat_pr_metric_confidence`](../feat_pr_metric_confidence/idea.md)** — the confidence framing (CI bands, named regressors) can feed into the followup prompts. "The winner is at +0.13 NDCG with a noise floor of σ=0.02 and 2 regressing queries" is much richer LLM context than "winner is 0.84" for proposing the next experiment.
- **Reuses [`feat_agent_propose_search_space`](../../../00_overview/implemented_features/2026_05_21_feat_agent_propose_search_space/)** (shipped 2026-05-21) — the underlying `search_space_defaults.py` heuristic is the natural fallback when the LLM proposes a `swap_template` followup that has a partial `search_space` (the disjoint params get heuristic bounds).
- **Composes with [`feat_create_study_search_space_builder`](../../../00_overview/implemented_features/2026_05_20_feat_create_study_search_space_builder/)** (shipped 2026-05-20) — the visual editor for `search_space` rows is where "Run this followup" lands, pre-populated. The diff visualization can leverage the same row primitive.
- **Eventually feeds [`feat_agent_propose_search_space`](../../../00_overview/implemented_features/2026_05_21_feat_agent_propose_search_space/)** at the conversational layer — once the LLM digest output is structured, the chat agent can fluently say "based on the digest from your last study, here are 3 followups I recommend; want me to run #2?" rather than today's freeform suggestion-paraphrase.
