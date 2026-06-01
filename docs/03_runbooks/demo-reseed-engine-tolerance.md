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

At least one engine was unreachable at probe time, but at least one scenario seeded successfully. This is **a legitimate success, not a failure**:

- **Reseed status:** `status == "complete"` AND `scenarios_skipped` is non-empty (e.g. `["acme-kb-docs-solr"]`).
- **UI:** the dashboard "Reset to demo state" dialog shows an italic *"Partial completion — N engine(s) skipped: …"* hint under the success message, with a "Why?" link back to this runbook.
- **CLI (`make seed-demo`):** a `[skip] <slug> — <engine> unreachable at <url>` line per skip, plus a `=== N scenario(s) SKIPPED (engine unreachable) ===` summary section on stderr. Exit code is **0** (partial success).

**Why scenarios skip:** the orchestrator probes each scenario's engine before dispatch (`is_engine_reachable`). A down engine (container not started, wrong port) yields a logged skip instead of a `ConnectError` that would abort the entire reseed. This is exactly what lets the `pr.yml` backend job go green without a Solr service container — Solr is absent, so its scenario skips, and the other 5 seed.

**What to do:** if you wanted the skipped engine's scenario(s), start the engine and re-run:

```bash
# Start the missing engine (example: Solr)
docker compose up -d solr
# Re-seed (FORCE=1 skips the wipe confirmation prompt)
make seed-demo FORCE=1
```

If you didn't need that engine (e.g. you're only demoing Elasticsearch), the partial state is fine — ignore the skip.

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
curl -s http://127.0.0.1:8000/api/v1/_test/demo/reseed/status | jq '{status, failed_reason, scenarios_skipped, scenarios_completed}'
```

A `status: "complete"` with a non-empty `scenarios_skipped` is the partial-completion signal. A `status: "failed"` with `failed_reason: "all_engines_unreachable"` is the hard-failure signal.

---

## Engine ports (for reachability debugging)

| Engine | Host port | Compose-DNS (in-container) | Reachability health path |
|---|---|---|---|
| Elasticsearch | `127.0.0.1:9200` | `elasticsearch:9200` | `GET /` (expects a `version` key) |
| OpenSearch | `127.0.0.1:9201` | `opensearch:9200` | `GET /` (expects a `version` key) |
| Apache Solr | `127.0.0.1:8983` | `solr:8983` | `GET /solr/admin/info/system` (expects `responseHeader.status==0` + `lucene`) |

The orchestrator (in-container) probes the **Compose-DNS** URLs; the CLI (on the host) probes the **host** URLs. Either way, a 2-second probe that fails to connect / resolve / return a healthy body marks the engine unreachable and skips its scenario(s).
