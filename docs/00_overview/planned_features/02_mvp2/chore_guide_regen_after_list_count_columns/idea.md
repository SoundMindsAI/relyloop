# chore_guide_regen_after_list_count_columns — regen guides 03 + 04 on populated stack

**Date:** 2026-06-03
**Status:** Idea — deferred from `feat_list_count_columns` PR (forthcoming, the one shipping `query_count` + `param_count` list-summary fields)
**Type:** `chore_`
**Priority:** P2 (cosmetic doc debt; the column code ships fine without it)

## Origin

Tangential discovery during the in-flight `feat_list_count_columns` PR
(adding `query_count` to `/query-sets` + `param_count` to `/templates`
list tables). The post-implementation guide-impact audit identified
that two in-app walkthrough guides screenshot the affected list views
and need regeneration:

* `ui/public/guides/03_create_query_template/01-templates-list.png`
* `ui/public/guides/04_create_query_set/01-query-sets-list.png`

A regen was attempted in the feature PR per the operator's "regenerate
in this PR" preference, but the operator's local DB was empty at regen
time (0 clusters, 0 query-sets, 0 templates). The Playwright guide
specs ran cleanly against the empty DB and produced screenshots that:

1. **Guide 03 / `04-template-created.png` (1 of 5)** — captured the new
   `PARAMETERS` column populated with value `2` for the just-created
   template. **Value-add screenshot.**
2. **The other 9 of 10 screenshots** — empty-state UI ("No templates yet"
   / "No query sets yet") replacing the populated-list illustration the
   previous screenshots carried.

The PR reverted all 10 to preserve the operator-useful populated-list
imagery, accepting the cosmetic debt that the screenshots reflect the
old 4-column shape (Name/Engine/Version/Created for templates;
Name/Cluster/Created for query-sets) until a populated regen happens.

CLAUDE.md rubric row that justified the deferral: *"Fix requires an
operator-environment change you can't make"* — the regen needs a
populated demo DB (e.g., from `make seed-demo`), which is an operator
decision about local state, not something the agent should drive.

## Problem

`ui/public/guides/03_create_query_template/01-templates-list.png` +
`ui/public/guides/04_create_query_set/01-query-sets-list.png` (and the
`02-create-modal-*` screenshots that show the list behind the modal)
will show 4-column / 3-column tables — missing the new `Parameters` /
`Queries` columns shipped in the `feat_list_count_columns` PR. Operators
viewing these guides in-app will see a column count in the screenshots
that doesn't match what they see in their own running UI.

The discrepancy is cosmetic (the guides still teach the canonical flow
correctly; the new column is additive, not a renamed/moved one) and
self-resolves as soon as someone runs the regen against a populated DB.

## Proposed scope

```bash
# 1. Populate the DB (any combination that gets templates + query-sets in):
make up                                 # bring the stack up if not already
make seed-demo                          # full demo seed (4-5 scenarios)
# OR use the in-app "Reset to demo state" button on the home page

# 2. Regen the two affected guides:
cd ui
pnpm exec playwright test -c playwright.demo.config.ts \
  tests/e2e/guides/03_create_query_template.spec.ts \
  tests/e2e/guides/04_create_query_set.spec.ts \
  --reporter=line

# 3. Spot-check that 01-*-list.png now shows the new column header
#    (Parameters or Queries) plus populated data rows.

# 4. Commit the regenerated PNGs (the .webm walkthroughs auto-regenerate too).
```

Roughly 3-5 minutes once the stack is up + seeded. No code changes.

## Why deferred

The screenshots are doc artifacts, not part of the column-shipping
contract. The column itself ships in `feat_list_count_columns` covered
by:

* 10 backend unit tests (`test_openapi_export.py`)
* 5 integration tests (`test_list_count_fields.py` — real Postgres)
* 2 contract tests (`test_list_count_fields_contract.py` — OpenAPI shape)
* 7 vitest cases (`list-count-columns.test.tsx` — column rendering)

The in-app guides degrade gracefully when stale — they still teach the
flow; only one screenshot per guide is mildly misleading about column
count. Holding the PR until a populated regen was infeasible in the
operator's session (DB had been wiped pre-session), so the regen path
moved out-of-band.

## Scope signals

* **Frontend artifacts only** — `ui/public/guides/03_*/` +
  `ui/public/guides/04_*/`. PNG + WEBM bytes change; no `.ts` / `.tsx`
  source changes.
* **No backend impact.** No migration, no API changes.
* **No test changes.** The Playwright guide specs themselves are
  unchanged — only the captured output PNGs.
* **Operator-environment requirement:** local stack up + populated
  with templates + query-sets via `make seed-demo` or equivalent.

## Related

* `feat_list_count_columns` (this PR) — ships the new columns whose
  visual representation this chore captures.
* `infra_generated_artifact_freshness_gate` (shipped 2026-06-03, PR
  #433) — the canonical `bash scripts/regen-generated-artifacts.sh`
  command + `ui/.prettierignore` rules. Same posture: artifact
  drift caught by CI for `types.ts`/`openapi.json`, but the guide
  screenshots are NOT in that gate (they live under `ui/public/guides/`,
  not in the regen-generated-artifacts list).
