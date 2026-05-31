# infra_adapter_solr — rework handoff (pause 2026-05-30)

**Why this file exists:** the Solr adapter feature (PR #336, branch
`feature/infra-adapter-solr`) was reworked because the original shipped against
wrong assumptions and didn't actually run. This session re-verified everything
against a LIVE Solr 10 and reconciled docs. Work paused mid-Phase-7 with flaky
local tooling. **Read this first, then `git status` + `git diff` to see exactly
what's uncommitted.**

## Core correction (the whole rework hinges on this)
Local Solr must run **security-DISABLED** (like local ES/OpenSearch), NOT with
BasicAuthPlugin/bootstrap-security.sh. Three facts proven against the real
`solr:10.0` binary this session:
1. **No `solr.UBIComponent`** ships in stock Solr (no module/class/ref-guide
   page). UBI on Solr is **read-path only** — demo synthesizes events into
   `ubi_queries`/`ubi_events`; probe reports `ubi_component_present=false`.
2. **No auth bootstrap.** `bootstrap-security.sh` deleted; `solr_admin_*`
   secrets removed. Solr runs security-disabled. `auth_kind=solr_basic` stays in
   the adapter for real operator clusters only.
3. **LTR form:** load via `SOLR_MODULES=ltr` (not `<lib>`); `[features]`
   transformer takes NO `fvCacheName` child; feature-vector cache is a
   `<featureVectorCache>` element inside `<query>` (matches Solr's shipped
   techproducts config; the 10.0 ref-guide's `fvCacheName` snippet is stale and
   the binary rejects it with "No setter corresponding to 'fvCacheName'").
4. Solr 10 boots SolrCloud by default — do NOT pass `-c` (removed; crashes).
   Configsets live in ZooKeeper; upload via Configsets UPLOAD API with conf
   files at ZIP ROOT (not nested under conf/).
5. `managed-schema.xml` needed a `color` field + `<dynamicField name="*">`
   catch-all (sample products.json has id/title/description/bullet_points[list]/
   brand/color — NO price/category/in_stock).

## Phases 0–6: DONE and VERIFIED LIVE
- **P1 configsets:** both collections CREATE cleanly (products + ubi_events).
- **P2 compose:** `relyloop-solr-1` healthy, SOLR_MODULES=ltr, 10.0.0, solrcloud.
- **P3 seed:** `make seed-solr` → 3 collections, 1000 docs, idempotent (re-run
  stays 1000). NOTE: required rebuilding the stale `relyloop/api:dev` image
  (`docker compose build api` + recreate) — backend/ is COPY'd, not bind-mounted.
- **P4 probe:** registered local-solr, reprobe → engine_config EXACTLY:
  mode=cloud, version=10.0.0, ltr_module_present=true, ubi_component_present=false,
  unique_key_per_target={products:id, ubi_events:id, ubi_queries:id}, ltr_models=[].
  GOTCHA: backfilling creds into a RUNNING stack needs `docker compose restart
  api` (settings YAML is @lru_cache'd at startup) — captured as idea file at
  `docs/00_overview/planned_features/00_unsure/chore_solr_cred_backfill_needs_api_restart/`.
- **P5 run_query:** `POST /clusters/{id}/run_query` → 200 with scored/ranked
  hits + full source; invalid query → 400 INVALID_QUERY_DSL.
- **P6 docs:** reconciled CLAUDE.md (lines 38 + 187), seed_clusters.py,
  probes.py, seed_meaningful_demos.py (removed `_read_solr_admin_password`
  apparatus — real bug, would've failed vs security-disabled Solr), adapters.md,
  mvp2-overview.md, comparison.md, adjacent-tools.md, relyloop-spec.md,
  solr-cluster-registration.md runbook. Added "Post-implementation correction"
  banners to infra_adapter_solr feature_spec.md + implementation_plan.md
  (historical review-log lines left intact under the banner — forward-only).

## Phase 7: IN PROGRESS — pick up HERE
- **Backend unit suite: 1951 PASSED** (verified this session). Solr capability
  probe tests: 22 passed (already assert ubi_component_present=False correctly —
  no change needed; tests match reality).
- **NOT YET DONE:**
  1. `make fmt && make lint && make typecheck` (CI parity:
     `./.venv/bin/ruff format --check backend/`).
  2. Confirm `test_claude_md_sections.py` still passes — I may have edited
     `test_solr_port_opt_in_documented` to match new line-187 wording; VERIFY
     with `git diff backend/tests/unit/docs/test_claude_md_sections.py`. If the
     edit didn't land and the test asserts old "opt-in/SOLR_HOST" wording, it
     will fail against the new CLAUDE.md line 187 — fix the test to assert the
     security-disabled posture (SOLR_MODULES/security, not opt-in/SOLR_HOST/
     bootstrap-security). The full suite passed 1951 so it's likely fine, but
     re-run `make test-unit` to be sure.
  3. `git add -A && git commit` (Conventional Commits; never --no-verify).
     EXPECT the pre-commit dashboard-regen to abort the FIRST commit because a
     new folder was added under planned_features/ (the cred-backfill idea +
     this handoff) — re-run `git add -A && git commit` a second time to land the
     dashboards in lockstep.
  4. `git push` to `feature/infra-adapter-solr`.

## Phase 8: PENDING
- Reconcile PR #336's review-log claims (the S1/G5-1/Gm-1 findings were about
  the now-deleted bootstrap-security.sh — note in the PR they're moot).
- Decide scope of any UBI-window demo-seed failures (3 pre-existing
  UBI_INSUFFICIENT_DATA on ES/OS scenarios — SEPARATE from this PR's diff).
- `gh run watch` CI on the push; adjudicate Gemini review with the 4-quadrant
  rubric; post summary verdict comment before merge.
- Per CLAUDE.md: do NOT merge until `make up` + a credentialed Solr round-trip
  works — which it now DOES (Phases 1–5 proved it).

## Separately deferred (NOT this PR)
- 3 pre-existing UBI_INSUFFICIENT_DATA demo failures (ES/OS scenarios).
- Local postgres 16→17 data-dir mismatch (operator-env; was resolved this
  session — stack came up healthy).

## Uncommitted files at pause (run `git status` to confirm — tooling was flaky)
Expected modified: CLAUDE.md, docker-compose.yml, scripts/install.sh,
scripts/seed_meaningful_demos.py, backend/app/scripts/seed_clusters.py,
backend/app/scripts/seed_solr_products.py, backend/app/api/probes.py,
docker/solr/configsets/relyloop_products/conf/{solrconfig.xml,managed-schema.xml},
docker/solr/configsets/relyloop_ubi/conf/solrconfig.xml,
docs/06_vendor_docs/README.md, several docs/*.md (active reconciliation),
infra_adapter_solr/{feature_spec.md,implementation_plan.md}.
Expected deleted (staged): docker/solr/bootstrap-security.sh.
Expected untracked: docs/06_vendor_docs/solr-9/, docs/06_vendor_docs/solr-10/,
the cred-backfill idea folder, this handoff file.

**Invocation to resume:** continue `/impl-execute` for infra_adapter_solr at
Phase 7 (fmt/lint/typecheck → commit → push), then Phase 8.
