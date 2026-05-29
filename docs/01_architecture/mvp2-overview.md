# MVP2 Overview — "Three-Engine + Real Signals"

**Status:** Planning. MVP1 (v0.1, "The Loop") shipped; the `01_mvp1/` backlog is fully drained. This page is the MVP2 release plan: goal, scope, an organized feature list with story stubs, sequencing, and exit criteria. It is a **navigation + planning** doc — the per-feature contracts live in each feature's `feature_spec.md` (produced by `/spec-gen` from the cited `idea.md`).

**Canonical sources this page derives from:**
- Product framing: [`docs/00_overview/relyloop-spec.md` §27 "MVP2 / v0.2"](../00_overview/relyloop-spec.md) (lines 2275–2326) + §8 SolrAdapter + §14 UBI judgments.
- Release matrix (authoritative; wins on any conflict): [`tech-stack.md` §"Canonical release matrix"](tech-stack.md).
- Live status board: [`MVP2_DASHBOARD.md`](../00_overview/MVP2_DASHBOARD.md) (regenerated from folder state).
- Sibling reading guide: [`mvp1-overview.md`](mvp1-overview.md).

> If a statement here conflicts with the canonical release matrix in `tech-stack.md`, the matrix wins — flag the drift in your PR.

---

## 1. Goal

**Make the engine-neutral claim verifiable, and let judgments come from real users instead of only an LLM.**

MVP1 proved the loop on Elasticsearch + OpenSearch with LLM-as-judge as the only authoritative judgment source. Two gaps remain before the positioning in [the umbrella spec §1](../00_overview/relyloop-spec.md) and [`docs/07_research/comparison.md`](../07_research/comparison.md) is *factual* rather than *rhetorical*:

1. **"Engine-neutral" is aspirational with only two engines.** Elasticsearch, OpenSearch, and Apache Solr are the three engines the OSC / Sease / Querqy / Haystack community treats as the canonical OSS search stack. Supporting all three makes "works wherever you are" demonstrable.
2. **LLM-as-judge is a weaker trust anchor than real behavior.** For operators with production traffic, ratings derived from clicks + dwell + conversions reflect what users *find* relevant, not what an LLM *guesses* should be relevant. The optimization loop's quality ceiling is the judgment list's quality — replacing that ceiling is the single biggest believability upgrade RelyLoop can ship.

MVP2 closes both in one release because they tell one coherent story and because **UBI on Solr is free once the adapter lands**: Solr's first-party `solr.UBIComponent` writes the same `ubi_queries` + `ubi_events` schema as the OpenSearch UBI plugin, so the engine-agnostic `UbiReader` works on Solr unchanged from day one.

## 2. Headline

> **RelyLoop runs on all three OSS engines (Elasticsearch, OpenSearch, Apache Solr) with UBI-derived judgments on every one of them — plus a hybrid UBI+LLM converter no competitor ships.**

This bundle delivers **four of RelyLoop's six differentiators**: all three OSS engines + the hybrid UBI+LLM judgment source. (The other two — the Bayesian full-search-space loop and the Git-PR apply path — shipped in MVP1.)

## 3. Audience expansion

- Apache Solr operators (the OSC + Sease + Querqy + Quepid/Chorus community, predominantly Solr-native).
- Operators with production search traffic and UBI logging enabled on any of the three engines.
- Operators who distrust LLM-as-judge as the only trust anchor.
- **Operators who do NOT yet collect user signals** — the large majority of OSS-search deployments. MVP2 must make them *more* capable, never less, and give them a clear path to UBI when they're ready.

## 4. Design principle — no-UBI operators stay first-class (the UBI on-ramp)

UBI is **progressive enhancement, not a gate.** The majority of operators have no UBI plugin installed and no clickstream when they first run RelyLoop. MVP2 must leave that experience strictly better than MVP1, and turn every UBI touchpoint into an on-ramp rather than a wall. Four tenets:

1. **LLM-as-judge remains the zero-config default.** Nothing in MVP2 degrades the no-UBI path. An operator who never enables UBI sees exactly the MVP1 experience, plus better guidance. Every UBI surface degrades gracefully to the LLM path — never to an error the operator can't act on.
2. **The tool detects readiness and nudges — it never acts on the cluster.** RelyLoop **never installs the UBI plugin, never writes to the cluster, never modifies schema** (consistent with the umbrella spec §4 non-goals). Nudges are *guidance*: detect that `ubi_queries` is absent or sparse, then point the operator at the engine-specific enablement runbook. The three engines have three different enablement paths (OpenSearch UBI plugin, o19s ES fork, Solr first-party `solr.UBIComponent`) — the nudge is engine-aware.
3. **Sparse UBI is a recommendation, not a failure.** An operator with *some* traffic is steered into hybrid mode ("UBI rates your dense head; LLM fills the tail") and told concretely what they'd gain by collecting more — not bounced with a 422.
4. **Show the value, don't just assert it.** The strongest nudge is the delta: "this UBI list covered 90% of last week's real traffic" beside "the previous LLM list rated 500 pairs on a snapshot." Surface coverage and, where a prior LLM list exists on the same query set, the metric delta — that's the moment a no-UBI operator decides UBI is worth enabling.

### UBI readiness ladder

Each cluster sits on a rung; the tool recommends the right judgment mode for the rung and nudges toward the next.

| Rung | State (detected via `get_schema` probe of `ubi_queries`) | Recommended mode | Nudge |
|---|---|---|---|
| 0 — No UBI | `ubi_queries` absent | **LLM-as-judge** (unchanged from MVP1) | "Enable real user signals" card → engine-specific runbook. Non-blocking, dismissible. |
| 1 — Installed, sparse | `ubi_queries` present, below `min_impressions_threshold` for most pairs | **Hybrid UBI+LLM** (UBI head + LLM tail) | "You have early signal — here's how much more traffic strengthens it." Show current coverage %. |
| 2 — Dense head | enough impressions on the head; long tail still thin | **Hybrid UBI+LLM** (default) | "Most adopters ship from here." Surface head/tail split. |
| 3 — Full coverage | dense across the query set | **UBI threshold converter** (CTR or dwell) | "Counterfactual click models (CCM/DBN) become viable — post-MVP2." |

This ladder is the spine of Workstream B's UX stories (B10–B13 below). It is also why the `HybridUbiLlmConverter` is the *default* recommended converter, not the conservative CTR one — hybrid is the rung most real operators occupy.

## 5. Definition of done (release exit criteria)

MVP2 ships when **all** of the following hold:

- [ ] A relevance engineer can register an Apache Solr cluster (9.x or 10.x, SolrCloud or standalone) and run the full loop — register → query set → judgments → study → digest → PR — end-to-end, proven by an automated E2E test against a live Compose `solr` service.
- [ ] The `SearchAdapter` conformance/contract suite passes for Solr on every method ES + OpenSearch already pass.
- [ ] `POST /api/v1/judgment-lists/generate-from-ubi` and the `generate_judgments_from_ubi` agent tool produce mixed-source judgment lists on **all three** engines.
- [ ] The hybrid UBI+LLM converter produces a mixed `source='click'` + `source='llm'` list, and calibration stats roll up across the source mix.
- [ ] One Alembic migration extends the `clusters.engine_type` + `auth_kind` CHECK constraints to accept Solr values, round-trips cleanly (`upgrade → downgrade -1 → upgrade`), and **no other schema migration is required** (UBI rides the existing `judgments.source = 'click'` enum).
- [ ] Coverage gate holds at the MVP1 bar (80% backend) across all new code; every new endpoint has a contract test, every new service an integration test, every new domain function a unit test, the Solr loop an E2E test.
- [ ] Two new runbooks (`solr-cluster-registration.md`, `ubi-judgment-generation.md`) and the tutorial extensions (Path C "run against Solr", Step 7 "swap LLM judgments for UBI") are published.
- [ ] **The no-UBI path is provably unchanged:** an operator with no `ubi_queries` index runs the full loop on LLM-as-judge with zero new friction (regression-tested), and is shown an engine-aware "enable real user signals" nudge rather than a dead-end error.
- [ ] **Sparse UBI degrades to a recommendation:** a cluster below the impression threshold is steered into hybrid mode (or LLM fallback) with a concrete "collect more" message — never a hard 422 with no next step.
- [ ] **Run-depth is a one-action choice:** the create-study wizard offers a clearly-labeled fast path (Quick, ~minutes, for demos/testing) and a deep path (Overnight, ~1000 trials + autonomous compounding) from a single screen; a Custom budget below the TPE warmup floor warns the operator it won't converge.
- [ ] **The overnight path produces a reviewable result from one action:** selecting Overnight runs a deep study that auto-compounds while unattended and, on return, presents a single summary of what ran and the best config found — one click from a PR, with no production change made without the operator.

## 6. Sequencing — do we gate MVP2 on the in-bucket bugs/chores?

**No.** Unlike the MVP1 drain (which reconciled a *shipped* release's leftovers), the 6 non-feature items in `02_mvp2/` were deliberately scoped *into* this release. None of them block the two anchors, and several are best done *during/after* the anchors because they harden or test exactly what the anchors add. They are organized below as **Workstream F (Hardening & test debt)** and fold in as the relevant surfaces land — not as a pre-flight gate.

**One standalone exception:** `bug_webhook_concurrent_merge_race_timing_sensitive` is a *real* correctness bug (the row-lock does not actually guarantee the newer-timestamp winner), not a latent-cosmetic one, and MVP2 may add lifespan startup tasks that trip it. It's a good "fix early as independent hygiene" candidate — do it first within Workstream F, but it still doesn't gate the anchors.

**Recommended build order:** A (Solr) ∥ B (UBI) in parallel → C (three-engine enablement, depends on A) → **G (run-depth ergonomics — quick-vs-overnight; independent, high operator value, can start immediately)** → D/E (chat + search UX, independent, fill gaps) → F (hardening, folds in continuously; webhook-race first). The on-ramp UX stories (B10–B13) ship *with* B, not after — they are what protect the no-signals majority.

---

## 7. Workstreams & feature list

Six workstreams. Each lists its goal, the source `idea.md`, story stubs (outline-level — full acceptance criteria come from `/spec-gen`), and the scope signals that matter for planning (migration? new deps? priority).

> **Anchors** = A + B. They are the release. Everything else is supporting, polish, or hardening.

### Workstream A — Apache Solr adapter (ANCHOR) · P1

**Goal:** a complete `SearchAdapter` implementation for Apache Solr 9.x + 10.x (SolrCloud + standalone) so the loop runs unchanged on a third engine.
**Source:** [`infra_adapter_solr/idea.md`](../00_overview/planned_features/02_mvp2/infra_adapter_solr/idea.md) · **Spec refs:** [spec §8 SolrAdapter](../00_overview/relyloop-spec.md), [adapters.md §Cross-engine parameter naming](adapters.md).
**Migration:** one (extends `engine_type` + `auth_kind` CHECK constraints; no new tables). **New Compose service:** `solr` (`solr:10`, Apache 2.0 image, `127.0.0.1:8983`). **Est:** ~2–3 engineer-weeks (~1,200 LOC backend, ~100 LOC frontend).

Story stubs:
- **A1 — Adapter skeleton + capability probe.** New `backend/app/adapters/solr.py`; on construction, probe Solr version, SolrCloud-vs-standalone, presence of `solr.UBIComponent`, presence of the `ltr` module; persist to `clusters.engine_config` JSONB for the search-space validator to consult.
- **A2 — `render` for `edismax`/`dismax`/`lucene`.** Emit a Solr request-parameter dict from the unified vocabulary; add `templates/solr/` Jinja templates mirroring `templates/elasticsearch/` shape; make the parameter-map's third column (the documented Solr mappings) real implementation — including richer `mm` arithmetic syntax and the `bf`-vs-`boost` additive/multiplicative split driven by `boost_fn.combine`.
- **A3 — `search_batch`.** Parallel `/select` requests over a connection pool sized by the existing `HTTPX_POOL_LIMITS` (Solr has no `_msearch` equivalent).
- **A4 — `get_schema` + `list_targets`.** Schema API (`/schema/fields|dynamicfields|fieldtypes`) → `Schema` type unchanged; CoresAdmin (standalone) / CollectionsAdmin (SolrCloud) for target listing, selected by the A1 probe.
- **A5 — `explain`.** `debugQuery=true&debug=results`, parse the `debug.explain` block.
- **A6 — Auth + migration.** Implement `solr_basic` (HTTP Basic) and `solr_apikey` (Solr 9+ JWT via `JWTAuthPlugin`); the one Alembic migration extending the `engine_type` + `auth_kind` CHECK constraints (with downgrade + round-trip per [CLAUDE.md](../../CLAUDE.md) Absolute Rule #5 — every migration has a reversible `downgrade()`).
- **A7 — LTR rescore (consume-only).** Render unified `rerank_model:{id,top_k}` to `rq={!ltr model=… reRankDocs=…}` applying a pre-existing `MultipleAdditiveTreesModel` from Solr's `/schema/model-store`. **Training is out of scope** (backlog).
- **A8 — Compose service + sample data.** Add the `solr` service + new optional env vars (`SOLR_HOST`/`SOLR_PORT`/`SOLR_ADMIN_USERNAME_FILE`/`SOLR_ADMIN_PASSWORD_FILE`, `*_FILE` mounted secrets per [CLAUDE.md](../../CLAUDE.md) Absolute Rule #2 — secrets via mounted files, never bare env vars); seed the `products` collection from the existing `samples/products.json`.
- **A9 — Frontend.** Add `solr` to the cluster-registration `engine_type` allowlist (per the Enumerated Value Contract Discipline — ground the option in the backend Literal); Solr auth help text; a Solr engine badge on cluster cards / study headers.
- **A10 — Tests + runbook.** Unit (param rendering, LTR injection, `mm` syntax, probe parsing, error mapping), integration (live Compose Solr; LTR round-trip; UBI reader against seeded indices), contract (Protocol conformance — Solr passes every method ES/OpenSearch pass), E2E (`ui/tests/e2e/solr-study-end-to-end.spec.ts`); new `docs/03_runbooks/solr-cluster-registration.md`; tutorial Step 0 Path C.

### Workstream B — UBI judgments (ANCHOR) · P1

**Goal:** click-derived, engine-agnostic judgments as a first-class source, with a differentiated hybrid UBI+LLM converter.
**Source:** [`feat_ubi_judgments/idea.md`](../00_overview/planned_features/02_mvp2/feat_ubi_judgments/idea.md) · **Spec refs:** [spec §14 Click-derived judgments](../00_overview/relyloop-spec.md), §19 agent tools, §20 API surface.
**Migration:** **none** (rides the existing `judgments.source IN ('llm','human','click')` CHECK). **Est:** ~2 engineer-weeks (~600 LOC backend, ~150 LOC frontend).

Story stubs:
- **B1 — `UbiReader` (engine-agnostic read layer).** New `backend/app/services/ubi_reader.py`; read standardized `ubi_queries` + `ubi_events` via any `SearchAdapter.search_batch` (two scrolling searches + client-side join on `query_id`); inputs `cluster_id`, `target`, `since`/`until`, optional `query_filter`, `max_queries` (default 5000). No new adapter method, no engine-specific UBI code.
- **B2 — Feature aggregation.** New `backend/app/domain/ubi/features.py`; per-(query, doc) feature vector: click count, impression count, position-bias-corrected CTR (Wang–Bendersky correction with a configurable prior), post-click dwell-time mean, conversion rate (NULL where not emitted), refinement rate.
- **B3 — `SignalsConverter` Protocol + two threshold converters.** New `backend/app/domain/ubi/converter.py`: the pure-domain Protocol `convert(features) -> ratings(0–3)`; `CtrThresholdConverter` (default, conservative; defaults 0.05/0.15/0.30) and `DwellTimeThresholdConverter` (content-discovery surfaces).
- **B4 — `HybridUbiLlmConverter` (the differentiator).** UBI rates the dense head (`impressions ≥ llm_fill_threshold`, default 20); LLM-as-judge fills the long tail below the threshold; interleave `source='click'` and `source='llm'` rows in one list. This is the operating mode most adopters ship to production (SRW's UBI path uses COEC alone — no hybrid).
- **B5 — API + worker.** `POST /api/v1/judgment-lists/generate-from-ubi` → 202 `{judgment_list_id, status:"generating"}`; new `backend/workers/judgments.py:generate_judgments_from_ubi` Arq job (pull features → run converter → optional LLM fill → INSERT `judgments` with per-row `source` → write `judgment_lists.calibration`); error envelopes `UBI_NOT_ENABLED` (412), `UBI_INSUFFICIENT_DATA` (422), `UBI_QUERY_MAPPING_AMBIGUOUS` (422).
- **B6 — Agent tool + orchestrator prompt.** `generate_judgments_from_ubi(query_set_id, cluster_id, target, since, until?, converter, llm_fill_threshold?)` mirroring `generate_judgments_llm`; orchestrator prefers UBI when the cluster has `ubi_queries` (one-shot `get_schema` probe), falls back to LLM otherwise — the chat ergonomic that earns the release name (agent-first symmetry per spec §21).
- **B7 — Calibration spot-check.** Reuse MVP1's Cohen's-kappa / agreement surface between UBI-derived ratings and a 30–50-row hand-labeled sample; account for source mix.
- **B8 — Frontend.** Source picker (LLM | UBI | Hybrid) + UBI window controls on the judgment-generation modal; insufficient-data empty state on the judgment-list detail page when the converter drops pairs.
- **B9 — Docs.** New `docs/03_runbooks/ubi-judgment-generation.md` (install the plugin, configure capture, choose a converter, calibrate thresholds); tutorial Step 7 ("swap the LLM list for a UBI-derived one" + surface the metric delta).

**On-ramp UX for the no-signals majority (ship *with* B, per §4)** — owned by the dedicated [`feat_ubi_onramp/idea.md`](../00_overview/planned_features/02_mvp2/feat_ubi_onramp/idea.md) (split from `feat_ubi_judgments` 2026-05-29 so the no-signals-majority UX is first-class and dashboard-visible). The four stories below map 1:1 to its four capabilities:
- **B10 — UBI readiness probe + surfacing.** Reuse the `get_schema` probe for `ubi_queries` to classify each cluster on the readiness ladder (rung 0–3); expose the rung on cluster detail and as a small badge on cluster cards. Turn the `UBI_NOT_ENABLED` (412) condition from a bare error into a structured, actionable state the UI can render. No cluster writes — read-only detection.
- **B11 — Engine-aware "enable real user signals" nudge.** A dismissible card on the judgment-generation modal and cluster-detail page when UBI is absent (rung 0), with steps specific to the cluster's `engine_type` (OpenSearch UBI plugin / o19s ES fork / Solr `solr.UBIComponent`) and a deep-link to `ubi-judgment-generation.md`. Reuses the shipped `feat_contextual_help` idiom; never blocks the LLM path. Re-surfaces on next visit if dismissed but still unaddressed.
- **B12 — Sparse-data guidance, not a wall.** When UBI is present but below `min_impressions_threshold` (rung 1), the would-be `UBI_INSUFFICIENT_DATA` path instead recommends hybrid mode and shows current coverage ("~12% of your query set has enough signal — hybrid rates that head, LLM fills the rest"). The empty/partial state on the judgment-list detail page explains *why* pairs were dropped and what closes the gap.
- **B13 — Value-delta framing.** On UBI/hybrid list completion, surface coverage stats ("covered N queries / X% of traffic in the window") and, where a prior LLM list exists on the same query set, the metric/coverage delta — the concrete "here's what real signals bought you" moment that converts a no-UBI operator. Feeds naturally into the PR-body confidence framing (composes with the shipped `feat_pr_metric_confidence`).

> **Deferred (documented, not built):** counterfactual click models (`CcmConverter`, `DbnConverter`) — same Protocol, need more impressions to be statistically valid (rung 3 unlocks them); engine-native readers (e.g. Elastic Behavioral Analytics) feeding the same Protocol. Both are post-MVP2 / backlog.

### Workstream C — Three-engine enablement (template library + cheatsheets) · P2

**Goal:** make "tune any parameter on any engine" practical, not just possible, with a curated template library and per-engine tunable-params cheatsheets — including the new `templates/solr/` shapes.
**Source:** [`chore_template_library_expansion/idea.md`](../00_overview/planned_features/02_mvp2/chore_template_library_expansion/idea.md). **Depends on:** A (so Solr templates can be validated against a live engine). **Migration:** none. (Surfaced as a `chore_` but it ships user-visible content — `/spec-gen` should confirm whether it warrants a `feat_` rename per the naming convention.)

Story stubs:
- **C1 — Curated template library.** Ship 5–6 templates under `samples/templates/` (basic multi_match, function-score decay, bool-boosted, knn-only, hybrid RRF, phrase rescore), each with `declared_params` descriptions, a `README.md`, and a hand-tuned `default_search_space.json`; install all by default on `make up`.
- **C2 — Per-engine cheatsheets.** `docs/06_vendor_docs/{elasticsearch,opensearch}-tunable-params.md` (≈15–20 knobs each: native + unified name, ranges, "when to tune", caveats, back-links to templates). **Extend to Solr** as part of this release's three-engine framing.
- **C3 — Wizard + tutorial linkage.** Engine-aware cheatsheet deep-links from the search-space glossary; inline template `README` summary in the Step-3 picker; "where to go next" tutorial section.
- **C4 — Cross-engine render smoke tests.** Each template renders against the demo cluster on its target engine(s) and returns non-empty results — reuse the `infra_adapter_elastic` integration harness, extended to Solr.

### Workstream D — Chat polish · P2

**Goal:** two deferred chat-UX items that pair naturally and were explicitly held for MVP2.
**Migration:** one (D2 only). **Independent of the anchors.**

Story stubs:
- **D1 — Last-message preview.** [`feat_chat_last_message_preview/idea.md`](../00_overview/planned_features/02_mvp2/feat_chat_last_message_preview/idea.md): add `last_message_preview` (120-char, markdown-stripped) + `last_message_at` to `ConversationSummary` via a correlated subquery (no migration, no denormalize); render a muted preview line in `ConversationList`. Open forks (which role, markdown strip, content extraction) have recommended defaults locked in the idea.
- **D2 — Long-conversation summarization.** [`bug_chat_long_conversation_truncation/bug_fix.md`](../00_overview/planned_features/02_mvp2/bug_chat_long_conversation_truncation/idea.md): wrap the existing position-based truncation with a summarization pre-step that condenses the dropped portion into a system-prefix message (additive — preserves the tool-call-group boundary invariant). Latent bug (fires only >100 messages). Adds a `conversations.summary` JSONB column (migration, reversible) + a summarization prompt template. Three forks (sync vs async timing; budget line; trigger threshold) have recommended defaults; lock them at `/bug-fix` Default-mode entry.

### Workstream E — Search UX · Backlog→P2

**Goal:** rank-ordered full-text search when `?q=` is present.
**Source:** [`feat_fts_rank_ordering/idea.md`](../00_overview/planned_features/02_mvp2/feat_fts_rank_ordering/idea.md). **Independent.** The `tsvector` columns + GIN indexes (`0008`–`0013`) already exist; the work is ordering + cursor encoding.

Story stubs:
- **E1 — Rank-ordered ordering.** `ORDER BY ts_rank DESC, created_at DESC, id DESC` on the 6 search-enabled list endpoints when `?q=` is set; unchanged otherwise.
- **E2 — Float-safe cursor.** Pick one approach at spec time (rank-bucketed integer cursor vs transient materialized rank column) so keyset pagination survives `ts_rank` boundaries without violating the no-offset/limit rule.
- **E3 — Cursor invalidation + UI.** Invalidate in-flight cursors on `?q=` change (mirror the `?sort=` rule); add a "Sort by relevance" pill to the `<DataTable>` toolbar when `q` is active.

### Workstream F — Hardening & test debt · mixed (do not gate the anchors)

**Goal:** close correctness and coverage gaps that MVP2's new surfaces make reachable. Fold in continuously; the webhook race first.

Story stubs:
- **F1 — Webhook concurrent-merge row-lock (REAL bug; do first).** [`bug_webhook_concurrent_merge_race_timing_sensitive/idea.md`](../00_overview/planned_features/02_mvp2/bug_webhook_concurrent_merge_race_timing_sensitive/idea.md): the `config_repos.last_merged_proposal_id` update doesn't guarantee the newer-timestamp winner under concurrency; make the compare-and-update race-free in SQL (`WHERE last_updated_at < :new_timestamp` under `SELECT … FOR UPDATE`) + add a regression test that spawns a lifespan task before the concurrent webhooks. Currently masked by an env-var gate; the first MVP2 lifespan task trips it.
- **F2 — Auto-followup parent advisory lock.** [`chore_auto_followup_parent_advisory_lock/idea.md`](../00_overview/planned_features/02_mvp2/chore_auto_followup_parent_advisory_lock/idea.md): `pg_advisory_xact_lock(hashtext(parent_id))` to serialize concurrent followup-enqueue workers (layer-3 idempotency). Sequence **after** MVP2's autonomous re-trigger paths land so the lock granularity is informed by a real failure shape (its idea says the race is "reachable in MVP2"). Watch for supersession by the unified-advisory-lock Option C in the cascade-race bug.
- **F3 — Demo-seeding async-flow integration tests.** [`chore_demo_seeding_integration_tests_rewrite/idea.md`](../00_overview/planned_features/02_mvp2/chore_demo_seeding_integration_tests_rewrite/idea.md): rewrite the 10 skipped sync-contract tests for the async enqueue+poll flow (in-process Arq worker fixture + "POST then poll to terminal" helpers). Closes the coverage gap that let `bug_demo_reseed_button_silent_enqueue_failure` ship.
- **F4 — Studies-POST Arq spy fixture.** [`chore_studies_post_arq_spy_fixture/idea.md`](../00_overview/planned_features/02_mvp2/chore_studies_post_arq_spy_fixture/idea.md): a `SpyArqPool` fixture so rejection-path tests can positively assert "no job enqueued." Natural to extend to the new UBI generate endpoint (B5) and the other enqueueing POSTs.
- **F5 — Arq subprocess resume test.** [`infra_arq_subprocess_test/idea.md`](../00_overview/planned_features/02_mvp2/infra_arq_subprocess_test/idea.md): spawn a real `arq … WorkerSettings` subprocess, SIGTERM mid-loop, restart, assert trials resume — a narrow Arq-version + cron-registry regression guard. **Trigger-locked:** ship when the `arq` pin bumps, a third cron lands, or MVP3 hardening opts in. May not fire within MVP2; keep as standby.

### Workstream G — Run-depth ergonomics: quick-for-demos vs one-click-overnight · G1 = P1

**Goal:** make it *obvious and one-action* to choose between a **fast shallow run** (demos, testing, smoke-checking a search space) and a **deep overnight run that compounds automatically and produces a far better result from a single user action**. This is the "set it before I log off, wake up to results worth a PR" experience — and equally the "give me something in 60 seconds for a demo" experience — from the same screen.

**Why this is in MVP2, not deferred:** an operator dogfooding trace (2026-05-29) found 6 of 7 real studies ran `max_trials` of 12–15 — *below* Optuna TPE's ~10-trial random-search warmup ([`optimization.md`](optimization.md)). Those studies never actually engaged the Bayesian optimizer; they were effectively random search, and the digest's narrow/widen follow-ups were compensating for under-budgeting, which *felt* like mandatory manual iteration. The capability to run deep and compound overnight (`auto_followup_depth`, [shipped](../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/)) had **zero usage** — it was a hidden config key. G fixes the defaults and surfaces the autopilot so the loop delivers a great result from one execution.

**Two paths, one screen** — the create-study wizard presents a clear choice:

```
How deep should this run go?
  ( ) Quick look      ~30 trials      minutes      — demos, testing, smoke-check a search space
  (•) Standard        ~200 trials     ~tens of min — the everyday "give me a real answer"
  ( ) 🌙 Overnight     ~1000 trials + auto-compound — deepest single-action result; review in the morning
  ( ) Custom…         power users
```

Story stubs:
- **G1 — Budget presets + sub-warmup guard · P1.** [`feat_study_budget_presets/idea.md`](../00_overview/planned_features/02_mvp2/feat_study_budget_presets/idea.md): replace the bare `max_trials` input with the Quick / Standard / Overnight / Custom selector (grounded in a backend constant per the Enumerated Value Contract Discipline); warn non-blockingly when a Custom value falls below the TPE warmup floor ("at 12 trials this is essentially random search — use ≥ Standard for a result worth a PR"). No migration. **This is the single change that most directly fixes the dogfooding friction** — and the "Quick look" preset is what makes fast demo/test runs trivial.
- **G2 — One-click overnight autopilot · P2.** [`feat_overnight_autopilot/idea.md`](../00_overview/planned_features/02_mvp2/feat_overnight_autopilot/idea.md): promote the shipped `auto_followup_depth` chaining to a first-class "🌙 Overnight" path — selecting it sets a deep trial budget *and* enables autonomous compounding (narrow around the winner, re-run, repeat; self-terminates on no-lift / depth / budget). Plain-language copy makes the human-approval boundary explicit ("no production change happens without your review — you still open every PR"). Plus a **morning results summary**: a chain-view panel showing each link's best metric, cumulative lift, the best config across the whole chain, and one click to the proposal that carries it. No migration (reads existing `parent_study_id` links + existing config field).
- **G3 — Convergence indicator · P2.** [`feat_study_convergence_indicator/idea.md`](../00_overview/planned_features/02_mvp2/feat_study_convergence_indicator/idea.md): a best-so-far curve + plain verdict ("Converged" / "Still improving when it stopped" / "Too few trials to tell") on the study detail page, so the operator can *see* whether a run went deep enough — and so the proposal recommends "re-run deeper" ahead of narrow/widen when a study stopped early. No migration (reads existing `trials`).

> **The three compose:** G1 prevents under-budgeting and gives the fast demo path; G2 makes the deep path one action and unattended; G3 confirms depth was sufficient. Together they are the operator-facing answer to "quick when I'm testing, devastatingly deep when I run it overnight." All compose with the MVP2 UBI anchor — an overnight compounding chain against a fresh UBI judgment list is the strongest result RelyLoop can produce.

---

## 8. Story summary (one line each)

| WS | ID | Story | Type | Migration | Priority |
|---|---|---|---|---|---|
| A | A1 | Solr adapter skeleton + capability probe | infra | — | P1 |
| A | A2 | `render` edismax/dismax/lucene + `templates/solr/` | infra | — | P1 |
| A | A3 | `search_batch` parallel `/select` + pool | infra | — | P1 |
| A | A4 | `get_schema` + `list_targets` (Cores/Collections) | infra | — | P1 |
| A | A5 | `explain` via `debugQuery` | infra | — | P1 |
| A | A6 | Auth (`solr_basic`/`solr_apikey`) + CHECK migration | infra | **1** | P1 |
| A | A7 | LTR rescore injection (consume-only) | infra | — | P1 |
| A | A8 | Compose `solr` service + sample data + env vars | infra | — | P1 |
| A | A9 | Frontend: engine_type option + auth help + badge | feat | — | P1 |
| A | A10 | Tests (unit/integration/contract/E2E) + runbook + Path C | infra | — | P1 |
| B | B1 | `UbiReader` engine-agnostic read layer | feat | — | P1 |
| B | B2 | Feature aggregation (CTR/dwell/conversion/refinement) | feat | — | P1 |
| B | B3 | `SignalsConverter` Protocol + CTR + dwell converters | feat | — | P1 |
| B | B4 | `HybridUbiLlmConverter` (the differentiator) | feat | — | P1 |
| B | B5 | `POST …/generate-from-ubi` + worker + error envelopes | feat | — | P1 |
| B | B6 | `generate_judgments_from_ubi` agent tool + prompt | feat | — | P1 |
| B | B7 | Calibration spot-check across source mix | feat | — | P1 |
| B | B8 | Frontend: source picker + window controls + empty state | feat | — | P1 |
| B | B9 | UBI runbook + tutorial Step 7 | docs | — | P1 |
| B | B10 | UBI readiness probe + ladder surfacing (read-only) | feat | — | P1 |
| B | B11 | Engine-aware "enable signals" nudge card | feat | — | P1 |
| B | B12 | Sparse-data → hybrid recommendation (not a wall) | feat | — | P1 |
| B | B13 | Value-delta framing (coverage + LLM→UBI delta) | feat | — | P1 |
| C | C1 | Curated 5–6 template library | feat | — | P2 |
| C | C2 | Per-engine tunable-params cheatsheets (ES/OS/Solr) | docs | — | P2 |
| C | C3 | Wizard + tutorial linkage | feat | — | P2 |
| C | C4 | Cross-engine render smoke tests | infra | — | P2 |
| D | D1 | Chat last-message preview | feat | — | P2 |
| D | D2 | Long-conversation summarization | bug | **1** | P2 |
| E | E1 | Rank-ordered FTS ordering | feat | — | P2 |
| E | E2 | Float-safe cursor encoding | feat | 0–1 | P2 |
| E | E3 | Cursor invalidation + relevance pill | feat | — | P2 |
| F | F1 | Webhook merge row-lock correctness (real bug) | bug | — | P1 |
| F | F2 | Auto-followup parent advisory lock | chore | — | P2 |
| F | F3 | Demo-seeding async-flow integration tests | chore | — | P2 |
| F | F4 | Studies-POST Arq spy fixture | chore | — | P2 |
| F | F5 | Arq subprocess resume test | infra | — | Backlog/trigger |
| G | G1 | Budget presets (Quick/Standard/Overnight) + sub-warmup guard | feat | — | **P1** |
| G | G2 | One-click overnight autopilot + morning chain summary | feat | — | P2 |
| G | G3 | Study convergence indicator + "re-run deeper" nudge | feat | — | P2 |

**Migration budget:** **two** new Alembic migrations total (A6 Solr CHECK constraints; D2 `conversations.summary`) — plus possibly one for E2 depending on the cursor approach chosen at spec time. UBI (the headline judgment work) and all of Workstream G require **zero** schema change.

## 9. Non-goals (explicitly NOT in MVP2)

Per [spec §27](../00_overview/relyloop-spec.md):

- **No second observability stack.** Langfuse + ClickHouse + SigNoz + the `audit_log` table land at **MVP3** ("Observable").
- **No LangGraph / `PostgresSaver` / RFC 7807 / `Idempotency-Key` everywhere** — those are **GA v1**.
- **No multi-Git provider** (GitLab, Bitbucket) — backlog. GitHub remains the only provider.
- **No multi-tenancy** — backlog. Single-tenant through GA v1.
- **No native multi-LLM provider SDKs** (Anthropic, Bedrock, Vertex, Azure) — backlog. OpenAI-compatible endpoints keep working via `OPENAI_BASE_URL`.
- **No LTR training** — MVP2's Solr LTR is consume-only; cross-engine training is backlog.
- **No real-time signal streaming / Path B** — UBI ratings are computed batch-wise at judgment-list creation, strictly offline.
- **No cluster-side actions to enable UBI.** RelyLoop never installs the UBI plugin, never writes the `ubi_queries`/`ubi_events` indices, never modifies the operator's cluster. The on-ramp (§4) is *guidance only* — detection + engine-specific runbook links. Enabling UBI is always the operator's action on their own infrastructure.
- **No Lucidworks Fusion** — dropped outright ([`chore_drop_fusion_scope`](../00_overview/planned_features/chore_drop_fusion_scope/idea.md)).

## 10. Open questions for `/spec-gen`

Resolve these when each feature's spec is authored:

1. **(A) Solr LTR test fixture** — does the E2E load a real `MultipleAdditiveTreesModel` into Compose Solr, or assert the `rq={!ltr …}` render shape only? (A real model makes the E2E heavier but proves the rescore round-trip.)
2. **(B) `UBI_QUERY_MAPPING_AMBIGUOUS` tiebreaker** — when one UBI `user_query` string maps to multiple `query_set` entries, what's the operator-facing disambiguation contract?
3. **(B) Hybrid converter cost accounting** — does the LLM-fill tail draw from the same `openai_daily_budget_usd` line as `generate_judgments_llm`, or its own?
4. **(C) `feat_` vs `chore_` for the template library** — it ships user-visible content; confirm the rename per the naming convention.
5. **(D2) Summarization timing/budget/trigger** — accept the three recommended defaults (sync; same budget line; message-count primary + token-count safety), or revisit?
6. **(E2) Cursor strategy** — rank-bucketed integer cursor vs transient materialized rank column (drives whether E needs a migration).
7. **(B10–B11) Nudge persistence + cadence** — where is "dismissed" state stored (per-cluster row? client localStorage like other contextual-help dismissals?), and does the nudge re-surface on a schedule or only while the underlying readiness rung is unchanged?
8. **(B10) Readiness thresholds** — what impression counts define the rung 1→2→3 boundaries, and are they operator-configurable or fixed defaults for MVP2?
9. **(B13) Delta baseline** — when no prior LLM list exists on the query set, what does the value-delta surface show instead (coverage-only? a one-off LLM spot-rating for comparison? nothing)?
10. **(G1) Exact preset trial counts** — confirm Quick/Standard/Overnight numbers (~30/200/1000?) and whether the Overnight preset also bumps `parallelism` for faster wall-clock; set the sub-warmup floor (fixed constant vs derived from `n_startup_trials`).
11. **(G2) Overnight = preset + autopilot, coupled or independent?** — does selecting the "🌙 Overnight" preset auto-enable `auto_followup_depth` (and at what default depth), or are deep-budget and auto-compound separate toggles? Where does the morning summary live (study-detail chain panel, a `/studies` "ran while away" card, or both)?

## 11. Where to look next

- Live status: [`MVP2_DASHBOARD.md`](../00_overview/MVP2_DASHBOARD.md) · roadmap: [`DASHBOARD.md`](../00_overview/DASHBOARD.md)
- Product framing: [`relyloop-spec.md` §27](../00_overview/relyloop-spec.md)
- Release matrix (authoritative): [`tech-stack.md`](tech-stack.md)
- Adapter contract: [`adapters.md`](adapters.md) · data model: [`data-model.md`](data-model.md) · API conventions: [`api-conventions.md`](api-conventions.md)
- MVP1 reading guide (the sibling of this doc): [`mvp1-overview.md`](mvp1-overview.md)
