# bug — relyloop-spec.md §"Click-derived judgments" has stale title + broken sibling links

**Date:** 2026-05-29
**Status:** Idea — captured during `feat_ubi_judgments` preflight (2026-05-29)
**Priority:** P2 — doc-only; no operator impact today, but the broken links and stale title surface immediately to anyone who hits §706+ of the umbrella spec.
**Origin:** Surfaced during `/idea-preflight` of [`feat_ubi_judgments`](../../02_mvp2/feat_ubi_judgments/idea.md) on 2026-05-29 when verifying the idea's spec citations.

## Problem

[`docs/00_overview/relyloop-spec.md`](../../../relyloop-spec.md) §"Click-derived judgments — OpenSearch UBI as the engine-neutral primary path" (line ~706) carries two staleness bugs from the 2026-05-27 release-matrix reshuffle (which compressed MVP1.5 into MVP2 per [`state_history.md`](../../../../state_history.md) "Release-matrix reshuffle (2026-05-27)"):

1. **Stale title:** The section header still reads `(MVP1.5)` — but MVP1.5 no longer exists as a release stop; the canonical matrix is MVP1 → MVP2 → MVP3 → GA v1. Should read `(MVP2)`. Concrete location: [`relyloop-spec.md:706`](../../../relyloop-spec.md).
2. **Broken sibling links:** The section's closing paragraph (line ~724) links to the two planned-features siblings via relative paths missing the `02_mvp2/` bucket directory AND using an extra `../00_overview/` prefix (wrong from inside `docs/00_overview/relyloop-spec.md`):
   - Currently: `[feat_ubi_judgments/idea.md](../00_overview/planned_features/feat_ubi_judgments/idea.md)` — resolves to `docs/00_overview/00_overview/planned_features/feat_ubi_judgments/idea.md` (404).
   - Correct: `[feat_ubi_judgments/idea.md](planned_features/02_mvp2/feat_ubi_judgments/idea.md)`.
   - Same problem for the `infra_adapter_solr/idea.md` link on the same line.

## Proposed fix

Single targeted patch to `docs/00_overview/relyloop-spec.md` updating the §706 header from `(MVP1.5)` to `(MVP2)` and rewriting the two relative paths at line ~724 to include the `02_mvp2/` bucket and drop the stray `../00_overview/` prefix. No code change. No test change.

## Scope signals

- **Backend / Frontend / Migration / Config / Audit events:** all N/A. Pure doc edit.
- **Tests:** none required — this is a markdown link/title fix.

## Why deferred / not inline

`feat_ubi_judgments` preflight could have applied this patch in the same edit pass, but the spec staleness is bigger than just the UBI feature (the relyloop-spec.md edit would mix scopes: a UBI-feature idea patch + an unrelated spec-doc fix). Capturing as a standalone P2 chore so the spec fix lands in its own focused PR (or rolls into the next docs-sweep PR). The broken links don't block anything operational — they just surface to anyone reading the umbrella spec.

## Relationship to other work

- **Surfaced by:** [`feat_ubi_judgments`](../../02_mvp2/feat_ubi_judgments/idea.md) preflight 2026-05-29.
- **Adjacent staleness:** the 2026-05-27 release-matrix reshuffle (see [`state_history.md`](../../../../state_history.md) "Release-matrix reshuffle (2026-05-27)") updated 24 active-doc references but missed this spec section. Worth one grep pass for any other `MVP1.5` references in `docs/00_overview/relyloop-spec.md` while the section is open.

## Open questions for /spec-gen

None — this is a 3-line targeted fix; doesn't warrant a spec stage. Can ship via direct PR or as part of the next docs-only finalization sweep.
