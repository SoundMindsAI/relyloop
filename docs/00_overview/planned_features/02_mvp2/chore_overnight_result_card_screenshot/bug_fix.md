# Bug fix — chore_overnight_result_card_screenshot

**Source idea:** [idea.md](./idea.md)
**Branch:** `chore/overnight-result-card-screenshot`
**Type:** chore — medium (design fork locked at preflight; this skill's scope)
**Date:** 2026-06-05

## Problem

`feat_overnight_final_solution_phase2` PR #442 shipped Step 12 of the first-study tutorial with a new sub-section *"In the morning — read the overnight result card"* — prose only, no screenshot. FR-9 explicitly required the screenshot. The plan's hard-fallback escape hatch authorized filing this chore because the standard CI demo seed (`make seed-demo`) does not produce a chain that exercises the card's full rendered state (path + best config + stop reason + narrative excerpt). Operators reading the tutorial saw the prose but had no visual reference.

## Reproduction

```bash
# Before: zero image references in the tutorial source.
grep -c '!\[' docs/08_guides/tutorial-first-study.md
# → 0
ls docs/08_guides/images/
# → No such file or directory
```

After the fix:

```bash
grep '!\[Overnight result card\]' docs/08_guides/tutorial-first-study.md
# → ![Overnight result card](images/12-overnight-result-card.png)
ls docs/08_guides/images/12-overnight-result-card.png
# → present (34 KB)
```

## Root cause

Two-part:

1. **Asset-path convention was fictional.** The implementation_plan hedged with `docs/08_guides/images/12-overnight-result-card.png (or similar; placement per existing convention)`. There was no existing convention — `docs/08_guides/images/` did not exist, the four long-form guides had zero image references, and the walkthrough-deck plumbing under `ui/public/guides/<NN_slug>/` was a parallel convention that doesn't apply to the long-form tutorial surface.
2. **Three-consumer fan-out unaddressed.** `docs/08_guides/tutorial-first-study.md` is mirrored to two destinations: `ui/public/docs/tutorial-first-study.md` via [`ui/scripts/copy-docs.mjs`](../../../../ui/scripts/copy-docs.mjs) (Next.js consumer) and `website/docs/guides/in-depth/tutorial-first-study.md` via [`website/scripts/build_guides.py`](../../../../website/scripts/build_guides.py) (MkDocs consumer for relyloop.com). A naive PNG drop would resolve only at the source path; both copy pipelines needed an `images/` subtree mirror or the deployed site would 404.

- Owning layer: **docs build pipeline** (cross-layer, two generator scripts + one source markdown edit + one binary asset)
- Origin: [docs/08_guides/tutorial-first-study.md:510](../../../../docs/08_guides/tutorial-first-study.md#L510) (the FR-9-owed Step 12 sub-section)
- Propagation: [ui/scripts/copy-docs.mjs:115](../../../../ui/scripts/copy-docs.mjs#L115) + [website/scripts/build_guides.py:880](../../../../website/scripts/build_guides.py#L880) (the two regen pipelines)

## Fix design (locked decisions — inherited from preflight)

1. **D-1 — PNG path: `docs/08_guides/images/12-overnight-result-card.png`** — co-located with the source-of-truth markdown. Markdown reference is the idiomatic relative `![Overnight result card](images/12-overnight-result-card.png)`. Alternatives `ui/public/guides/<NN>/...` and `ui/public/docs/images/...` rejected per preflight rationale (walkthrough-deck namespace + generated-mirror tree respectively).
2. **D-2 — Regen tool: `bash scripts/regen-generated-artifacts.sh`** — invokes both `copy-docs.mjs` and `build_guides.py`, the only spelling that refreshes every consumer. `pnpm prebuild` skips the website copy.
3. **D-3 — Build-pipeline plumbing in scope.** `copy-docs.mjs` gains `copyImageAssets` + `pruneStaleImages` exports and ferries `docs/08_guides/images/*.png` → `ui/public/docs/images/*.png`. `build_guides.py` gains `copy_long_form_images()` and ferries `docs/08_guides/images/*.png` → `website/docs/guides/in-depth/images/*.png`. Both add `"images"` to the flat-prune expected set so the subdir survives the top-level prune, and both prune the images subdir to exactly the source set so a removed source PNG cleans up automatically.

## Regression test plan

The plumbing edits add four guard layers; the FR-9 markdown reference is verified by the freshness gate that already runs in CI.

| Layer | Path | What it asserts |
|---|---|---|
| unit (Node) | [ui/src/__tests__/scripts/copy-docs.prune.test.ts](../../../../ui/src/__tests__/scripts/copy-docs.prune.test.ts) — 10 new cases | `copyImageAssets` (5) + `pruneStaleImages` (3) + runCopyDocs image subtree end-to-end (4): copies png, skips non-png, no-op on missing src, no-op on non-dir, overwrites stale dest, prunes vs. set, preserves non-png, end-to-end mirrors + prunes + does-not-rmtree-images-during-md-prune. |
| unit (Python) | [backend/tests/unit/scripts/test_build_guides.py](../../../../backend/tests/unit/scripts/test_build_guides.py) — 7 new cases | `copy_long_form_images` (5): copies png, skips non-png (incl. `.gitkeep`), no-op on missing src, no-op on non-dir, overwrites stale dest. `prune_all` images contract (2): protects images subdir during in-depth prune + prunes stale images; backwards-compat shim leaves images alone when caller doesn't pass `copied_long_form_images`. |
| freshness gate (CI) | [.github/workflows/pr.yml](../../../../.github/workflows/pr.yml) `generated-artifacts-fresh` + `copy-docs-freshness` + `build-guides-freshness` | Re-runs the regen script on every PR and fails on `git status --porcelain` drift — catches the regression where someone edits the tutorial without updating both public copies. |

## Rollout

None. Docs + test infra + one binary asset. No data migration, no feature flag, no operator action, no migration head movement (Alembic head stays `0023`).

The PNG was captured locally against `http://localhost:3000` against a deterministically-seeded chain. Capture recipe (so the next refresh is reproducible) — both `.py` and `.mjs` are ephemeral capture-time scaffolding, NOT committed:

1. `make up` to boot the stack. Confirm `acme-products-prod` (or any cluster + 4 entity IDs) exist; otherwise `make seed-demo`.
2. Seed a 2-link chain via the existing test endpoint:
   ```bash
   curl -sS -X POST http://localhost:8000/api/v1/_test/auto-followup/seed-chain \
     -H "Content-Type: application/json" \
     -d '{"cluster_id":"<id>","query_set_id":"<id>","template_id":"<id>","judgment_list_id":"<id>","depth":1,"in_flight_leaf":false,"in_flight_middle":false}'
   ```
3. Patch the leaf with a winning Proposal + Digest + `auto_followup_selected_kind='narrow'` + bumped `best_metric=0.532` (writes a friendly anchor/follow-up name pair). The seeded chain skeleton doesn't include winning rows — the morning card needs them.
4. Verify the chain endpoint reports `stop_reason ≠ 'in_flight'` AND `links.length >= 2` AND `best_link_id` non-null AND `proposal_id_for_best_link` non-null:
   ```bash
   curl -sS http://localhost:8000/api/v1/studies/<root_id>/chain | python3 -m json.tool
   ```
5. Capture via `@playwright/test` chromium against `http://127.0.0.1:3000/studies/<root_id>`, waiting on `[data-testid="overnight-result-card"]`, screenshotting the element at viewport 1440×960. Save to `docs/08_guides/images/12-overnight-result-card.png`.
6. Add the `![Overnight result card](images/12-overnight-result-card.png)` line to `docs/08_guides/tutorial-first-study.md` Step 12.
7. `bash scripts/regen-generated-artifacts.sh` to refresh `ui/public/docs/` and `website/docs/guides/in-depth/`.

## Tangential observations

None worth deferring. The "optional `seed-chain` extension" raised at preflight Q1 (seed `selected_followup_kind` + winning proposal + winning digest in the test endpoint so `pnpm capture-guides` could auto-produce the card image without manual wizard clicks) remains deferred-until-needed — when AC-12's E2E click-through actually needs to flip from best-effort to required, file `chore_seed_chain_winning_proposal_kind` at that point. The morning card markdown reference (`**narrowed**` in the captured narrative) renders as literal text rather than bold; that's a pre-existing card-rendering decision, not a regression.
