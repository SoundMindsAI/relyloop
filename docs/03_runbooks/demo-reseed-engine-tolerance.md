<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Demo reseed — engine tolerance (partial completion & skips)

**Owner:** `infra_solr_ci_readiness` (`backend/app/services/demo_seeding.py` + `backend/workers/demo_reseed.py` + `scripts/seed_meaningful_demos.py`).
**Audience:** an operator (or CI) who ran a demo reseed and saw some scenarios skipped — and wants to know whether that's a problem and how to fix it.

The demo reseed seeds **6 scenarios** across three engines: four small scenarios + the rich ESCI scenario on **Elasticsearch**, one scenario on **OpenSearch** (`news-search-staging`), and one on **Apache Solr** (`acme-kb-docs-solr`). If an engine isn't running when the reseed starts, that engine's scenario(s) are **skipped** rather than crashing the whole reseed.

This runbook explains the three outcomes and what to do about each.

---

## The three outcomes

### Full completion

Every engine was reachable; all 6 scenarios seeded. The reseed status is `status="complete"` with `scenarios_skipped == []`. Nothing to do.

### Partial completion (some engines skipped)

At least one scenario didn't seed, but at least one scenario seeded successfully. This is **a legitimate success, not a failure**.

**Two distinct skip reasons** (per feat_selective_engine_startup_and_demo Story 3.2 / FR-6 / FR-9):

- **`unreachable`** — the scenario's engine container wasn't reachable at probe time (engine down, wrong port, network failure). The orchestrator's pre-existing reachability gate skips the scenario rather than aborting the whole reseed (`infra_solr_ci_readiness` FR-2).
- **`user_excluded`** — the operator's reset-modal selection (or the POST body's `engines` filter) excluded the scenario's engine_type. The orchestrator skips BEFORE the reachability probe; the engine may or may not have been reachable, but the operator's intent takes precedence.

Both reasons set `status == "complete"` with a non-empty `scenarios_skipped`. The distinction lives in the new `scenarios_skipped_reasons: dict[slug, reason]` field on `ReseedStatusResponse`.

- **Reseed status:** `status == "complete"` AND `scenarios_skipped` non-empty (e.g. `["news-search-staging", "acme-kb-docs-solr"]`) AND `scenarios_skipped_reasons` discriminates each entry (e.g. `{"news-search-staging": "user_excluded", "acme-kb-docs-solr": "unreachable"}`).
- **UI:** the dashboard "Reset to demo state" dialog renders two distinct sublines — **"You excluded: …"** for `user_excluded` slugs and **"Engine unreachable: …"** for `unreachable` slugs. Older Redis-cached payloads (from before the field landed) gracefully degrade to a single flat "Engine unreachable" line treating every slug as the pre-existing reason.
- **CLI (`make seed-demo`):** a `[skip] <slug> — <engine> unreachable at <url>` line per `unreachable` skip, plus a `=== N scenario(s) SKIPPED (engine unreachable) ===` summary section on stderr. Exit code is **0** (partial success). User-excluded skips aren't a CLI concept today — the CLI flag for engine filtering is tracked separately if it's ever needed.

**Why scenarios skip:** the orchestrator probes each scenario's engine before dispatch (`is_engine_reachable`). A down engine (container not started, wrong port) yields a logged skip instead of a `ConnectError` that would abort the entire reseed. The user-intent filter (FR-5) is layered on top — it fires BEFORE the reachability probe so the UI can communicate "you didn't pick this engine" distinctly from "we tried and it was down."

**What to do** depends on the reason:

- **`unreachable`** — if you wanted the skipped engine's scenario(s), start the engine and re-run:
  ```bash
  # Start the missing engine (example: Solr)
  docker compose up -d solr
  # Re-seed (FORCE=1 skips the wipe confirmation prompt)
  make seed-demo FORCE=1
  ```
- **`user_excluded`** — re-open the reset modal and check the engine you previously unchecked, then click Confirm. The reseed runs only on the now-selected engines.

If you didn't need that engine (e.g. you set `RELYLOOP_ENGINES=es` at startup or unchecked it deliberately in the modal), the partial state is fine — ignore the skip.

### Hard failure — all engines unreachable

If **no** engine was reachable (nothing seeded), the reseed is a **failure**, not a partial:

- **Reseed status:** `status == "failed"` + `failed_reason == "all_engines_unreachable"` + `scenarios_skipped` = every slug + `scenarios_completed == 0`.
- **CLI:** an `ERROR: all engines unreachable — start at least one engine (ES/OS/Solr) and retry` line + exit code **1**.

This is treated as a failure deliberately: a no-op reseed reported as success would cache in Arq's result window and lock out retries for ~1h (see [`bug_reseed_failure_blocks_retry_arq_singleton_dedup`](../00_overview/planned_features/02_mvp2/bug_reseed_failure_blocks_retry_arq_singleton_dedup/idea.md)). Surfacing it as `failed` keeps retries working.

**What to do:** start at least one engine and re-trigger the reseed (button or `make seed-demo`).

---

## Inspecting `scenarios_skipped`

Poll the status endpoint and read the field directly:

```bash
curl -s http://127.0.0.1:8000/api/v1/_test/demo/reseed/status | jq '{status, failed_reason, scenarios_skipped, scenarios_skipped_reasons, scenarios_completed}'
```

A `status: "complete"` with a non-empty `scenarios_skipped` is the partial-completion signal. The `scenarios_skipped_reasons` dict tells you why each entry was skipped (`user_excluded` vs `unreachable`); slugs absent from that map default to `unreachable` for backward compatibility with older cached payloads. A `status: "failed"` with `failed_reason: "all_engines_unreachable"` is the hard-failure signal — every scenario was either user-excluded OR unreachable (both count toward the all-unreachable threshold).

---

## Engine ports (for reachability debugging)

| Engine | Host port | Compose-DNS (in-container) | Reachability health path |
|---|---|---|---|
| Elasticsearch | `127.0.0.1:9200` | `elasticsearch:9200` | `GET /` (expects a `version` key) |
| OpenSearch | `127.0.0.1:9201` | `opensearch:9200` | `GET /` (expects a `version` key) |
| Apache Solr | `127.0.0.1:8983` | `solr:8983` | `GET /solr/admin/info/system` (expects `responseHeader.status==0` + `lucene`) |

The orchestrator (in-container) probes the **Compose-DNS** URLs; the CLI (on the host) probes the **host** URLs. Either way, a 2-second probe that fails to connect / resolve / return a healthy body marks the engine unreachable and skips its scenario(s).
