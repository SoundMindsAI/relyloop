# Query normalization as a tunable, opt-in query-time parameter

**Date:** 2026-05-29
**Status:** Idea — exploratory. Placed in `00_unsure/` because the release target is genuinely unresolved: the core capability is small and fits the existing parameter model, but a prod-reproducibility question (below) must be answered before it can be committed to a release.
**Priority:** P2 (exploratory) — a scope-respecting differentiator in the "query understanding" space no competitor's *optimizer* touches, but gated on a design decision, not ready to schedule.
**Origin:** Operator observation (2026-05-29) from a real-world search-relevance exercise: "before we ever discussed boosting or parameters, we normalized the incoming query — lowercasing, whitespace removal, expanding `what's` → `what is`." This is the **query-understanding / query-rewriting** stage, which sits *upstream* of the ranking stage RelyLoop tunes. RelyLoop currently passes `query_text` through verbatim ([`ElasticAdapter.render`](../../../../../backend/app/adapters/elastic.py)) and has no parameter representing normalization. No prior backlog idea existed for this — confirmed by search.
**Depends on:** MVP1 study lifecycle + search space (shipped). Composes with — does not block — the MVP2 anchors.

## Problem

A relevance pipeline runs in stages: (1) query understanding / normalization → (2) retrieval → (3) ranking / boosting → (4) re-ranking. RelyLoop tunes **stage 3 only**. But stage 1 is often where the largest relevance wins hide (vocabulary mismatch, not bad boosts, is the common cause of zero-results), and operators routinely tune it by hand — exactly what the originating exercise did.

"Normalization" is two different mechanisms, and only one is a candidate here:

- **Analyzer-level** (lowercase, stemming, stopwords, synonyms as token filters): governed by index analyzers with index-time/query-time symmetry; changing it requires reindexing. **Permanently out of scope** per umbrella spec §4 ("Make schema/mapping/analyzer changes" is a non-goal). RelyLoop reads analyzer names, never writes them. This idea does **not** touch this.
- **Pre-query rewriting** (contraction expansion, whitespace/case normalization applied to the *query string* before it reaches the engine, light spell-normalization): an application-layer transform. It does **not** touch the cluster, so it is query-time — RelyLoop's domain — and RelyLoop simply has no parameter for it today. **This is the candidate.**

So the gap: RelyLoop can tell an operator the best `title_boost`, but it cannot empirically answer "does expanding contractions on the incoming query improve nDCG on my judgment set?" — even though that's a query-time question its loop is built to answer.

## Proposed capability (sketch)

Make the normalization choice a **categorical search-space parameter** — RelyLoop already supports categoricals ([`CategoricalParam`](../../../../../backend/app/domain/study/search_space.py)). A template could declare:

```
query_normalizer: { "type": "categorical",
                    "choices": ["none", "lowercase", "lowercase+trim", "lowercase+trim+expand_contractions"] }
```

A small **pre-render hook** applies the selected normalizer to `query_text` *before* the template interpolates it (`query_text` is the implicit render param — [`template_validator.py:53`](../../../../../backend/app/domain/study/template_validator.py#L53)). The Optuna loop then *discovers* whether a normalization rule helps the judgment set, the same way it discovers the best boost — and the winning normalizer travels in the proposal/PR like any other parameter.

Normalizers are a small, **pure-domain, deterministic** library (`none` / `lowercase` / `trim` / `expand_contractions` from a small dictionary). No LLM, no cluster write, no new external dependency.

## The opt-in requirement (operator's explicit ask)

**This must be optional and off by default.** Two reasons, the second decisive:

1. **Not every operator can act on normalization.** Some have no control over their query-rewriting layer (it lives in a separate team's service, or a vendor front-end). For them, a normalization parameter would tune something they can't deploy. Default behavior stays exactly as today: `query_text` passes through verbatim; the parameter only exists when a template opts in by declaring it.
2. **Prod-reproducibility is the gating design question.** If RelyLoop applies a rewrite at *its* query-time but the operator's *production* query pipeline does not apply the same rewrite, the winning config will not reproduce in production — RelyLoop would be optimizing against a query the live system never issues. This violates the core invariant that a merged proposal reproduces the measured gain. **Therefore the rewrite must be one the operator can also deploy** (e.g. carried in the config repo via the Git-PR apply path, or explicitly acknowledged as "you must replicate this normalizer in your query service"). Until this is resolved, the feature can't be committed to a release — hence `00_unsure/`.

## Open questions (must resolve before promoting out of `00_unsure/`)

1. **Prod reproducibility** — how does the chosen normalizer get deployed in the operator's actual query pipeline? Options: (a) the apply-path PR carries a normalizer declaration the operator's search service reads; (b) the proposal body documents the required normalizer and the operator replicates it manually; (c) scope to only normalizers the engine itself can apply at query time (narrow). This decision determines whether the feature is viable at all.
2. **Normalizer library scope** — which rules ship? Lowercasing and trim are safe and engine-symmetric-ish; contraction expansion needs a dictionary (English-only? operator-supplied?); spell-correction is probably too far (drifts toward the analyzer/index-time boundary and needs a corpus).
3. **Overlap with analyzers** — lowercasing at query-time may *duplicate or conflict* with a lowercase token filter already in the index analyzer (double-normalization is usually harmless but worth validating). The capability probe / schema read could warn when a chosen normalizer is redundant with the field's analyzer.
4. **Is categorical the right shape, or should it be a typed sub-object** (an ordered list of normalization steps)? Categorical keeps it inside the existing search-space model with zero schema change; a sub-object is more expressive but more work.

## Scope signals (rough, pending the open questions)

- **Backend:** small if scoped to a pure-domain normalizer library + a pre-render hook on `query_text` + categorical wiring. Larger if prod-reproducibility requires apply-path changes (question 1).
- **Frontend:** small — the normalizer is just another categorical in the search-space builder.
- **Migration:** none for the tuning mechanism (rides existing `CategoricalParam`); possibly one if the apply-path carries a normalizer declaration.
- **Config:** none required.
- **Audit events:** N/A (pre-`audit_log`).

## Relationship to other work

- **Documented in** [`docs/01_architecture/optimization.md` §"Where RelyLoop fits in your relevance pipeline"](../../../../01_architecture/optimization.md) (the Tier-1 boundary doc that landed with this idea) — that section is the operator-facing "normalize first; RelyLoop tunes ranking" guidance and points here for the tunable extension.
- **Distinct from analyzer changes** — those stay a permanent non-goal (umbrella spec §4); this is strictly query-time string rewriting that never touches the cluster.
- **Composes with the apply path** ([`apply-path.md`](../../../../01_architecture/apply-path.md)) — if resolved via option (a), the winning normalizer ships in the config-repo PR like any other tuned parameter.
- **Mirrors the UBI on-ramp opt-in philosophy** ([`feat_ubi_onramp`](../../02_mvp2/feat_ubi_onramp/idea.md)) — a capability for operators who *can* participate must not degrade the experience for those who can't; default behavior is unchanged.
