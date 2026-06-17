# Selective Engine Provisioning — Startup + Reset-to-Demo

**Date:** 2026-06-17
**Status:** Idea — user request (operator wants to pick which engines/versions to load, both at first boot and on demo reseed, to cut startup time)
**Priority:** P2 — high-value DX, not blocking; the stack works today by loading all three engines
**Origin:** User request (2026-06-17): on the `/` "Reset to demo state" button, let the operator pick which engines (Solr / OpenSearch / Elasticsearch) and which version (latest of the last 2 major releases) to load, with streaming status; and fold the same selection into the initial startup so unselected engines never get pulled — "dramatically reduce the amount of time it takes to initially start up RelyLoop."
**Depends on:** None hard. Builds on the existing demo-reseed flow ([`backend/app/api/v1/_test.py`](../../../../../backend/app/api/v1/_test.py), [`backend/app/services/demo_seeding.py`](../../../../../backend/app/services/demo_seeding.py), [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx)) and the Compose engine services ([`docker-compose.yml`](../../../../../docker-compose.yml)).

## Problem

Today `make up` ([`scripts/install.sh`](../../../../../scripts/install.sh) → `docker compose up -d --wait`) **always** pulls and boots all three engines — `elasticsearch:9.4.1`, `opensearchproject/opensearch:3.6.0`, `solr:10.0` ([`docker-compose.yml`](../../../../../docker-compose.yml) — no Compose `profiles:`, so every service is in the default set). For an operator evaluating RelyLoop against a single engine, two of the three image pulls (~hundreds of MB each) + two JVM boots + two healthcheck waits are pure cost. Startup is ~60–90s today and a large fraction of that is the unselected engines.

Likewise, the "Reset to demo state" button reseeds **all** reachable engines (5 demo scenarios spanning ES/OS/Solr). It already *skips* unreachable engines gracefully (`is_engine_reachable` → `scenarios_skipped`), but the operator can't *choose* to seed only one — and there's no way to pick an engine **version**.

The operator wants one selection concept that (a) at startup decides which engine images get pulled/run, and (b) on demo reseed decides which running engines get seeded — with live streaming status during the reseed.

## Key architectural finding (read before scoping)

**Engine *version* selection belongs to the startup/Compose layer, not the reseed layer.** The reseed seeds data into engine containers that are *already running*; the RelyLoop API/worker run inside their own containers and deliberately have no Docker socket / no authority to pull images or restart Compose services. So:

- The **version picker** can only meaningfully act at install/`make up` time, by parameterizing the image tag (e.g. `ES_IMAGE_TAG`) and re-provisioning. Engine versions are currently **hardcoded** in `docker-compose.yml` with no env override (only `BASE_REGISTRY`, `ES_HEAP_SIZE`, `SOLR_HEAP_SIZE` are parameterized).
- The **reset-to-demo version picker**, if offered, can only reflect/choose among versions that are *currently provisioned*. It must NOT try to switch engine versions from the browser (would require giving a container Docker control — a non-goal). The clean UX is: reset-to-demo picks *engines* (among those running); version changes route the operator to re-run `make up` with the new selection.

This means the user's two asks are **layered, not parallel**: startup = what's provisioned (engine + version); reset-to-demo = which of the provisioned/running engines to (re)seed.

## Proposed capabilities

### A. Startup engine + version selection (the foundational piece)

- Make each engine service **optional** via Compose `profiles:` (e.g. profiles `es`, `os`, `solr`) so `docker compose up` with a selected profile set never pulls or starts the unselected engines.
- Parameterize each engine image tag via env var with the current pin as default — `ES_IMAGE_TAG`, `OS_IMAGE_TAG`, `SOLR_IMAGE_TAG` — so the selected version flows from `.env` into Compose.
- `scripts/install.sh` gains an engine/version selection step that writes the chosen profiles + tags to `.env` (and a non-interactive flag/env form for CI and scripted installs, e.g. `RELYLOOP_ENGINES=es,solr` / `RELYLOOP_ES_VERSION=...`). Default (no selection) preserves today's behavior: all three at the pinned versions.
- Demo auto-seed (`seed_meaningful_demos.py --if-empty`) already skips unreachable engines, so it naturally seeds only the provisioned subset — verify this holds.

### B. Reset-to-demo engine selection

- The reset button opens a selection modal: checkboxes for the engines **currently running** (probe via the existing reachability snapshot or a small "what's provisioned" capability), defaulting to all running.
- `POST /api/v1/_test/demo/reseed` accepts an optional `engines: ["elasticsearch","opensearch","solr"]` filter; the orchestrator (`reseed_demo_state`) seeds only the selected, intersected with reachable. Unselected → reported in `scenarios_skipped` (reuse the existing partial-completion path — `status="complete"` with skips is NOT a failure, per CLAUDE.md).
- **The engine filter is a UX layer on top of an already-engine-aware mechanism.** The reachability+skip path at [`demo_seeding.py:1578`](../../../../../backend/app/services/demo_seeding.py#L1578) already skips scenarios when their engine container is down. The `engines` filter adds a *user-intent* distinction the UI can communicate: "you didn't pick this engine" vs "we tried and it was unreachable." Recommend a small enum on `scenarios_skipped` entries (e.g. `reason: "user_excluded" | "unreachable"`) so the toast/log can render the two cases differently.
- Version display in the modal: Solr has `probe_capabilities` returning a version today, but **ES/OS have no version-report path** (the `is_engine_reachable` probe just hits `/` and checks for a `version` key without surfacing it). Showing a per-engine version in the modal is therefore net-new for 2 of 3 engines. Decide at spec time whether to show version at all here or keep this purely an engine picker (recommended: engine-only — defer version display until a unified capability/version endpoint is warranted).

### C. Streaming status for reseed

- The reseed already streams incremental progress today — but via **Redis polling** (`GET /api/v1/_test/demo/reseed/status` every 2s, rendering `current_step` + a deduped step log). Decide whether "streaming status updates" is satisfied by the existing poll loop (cheapest) or warrants migrating to true SSE.
- True SSE infra already exists for the chat agent (`StreamingResponse` + `text/event-stream`, `to_sse_frame()` in [`backend/app/agent/events.py`](../../../../../backend/app/agent/events.py)) and could be reused. **Recommendation:** keep the existing poll for v1 (it already delivers step-by-step status) and only add SSE if the latency/granularity is judged insufficient — call this out as an open fork rather than assuming the rewrite.

### D. Version source-of-truth matrix (shared by A + B)

- "Latest of the last 2 major releases" requires a **curated** per-engine version matrix (auto-discovering from Docker Hub at runtime is network-dependent and fragile, and would break the corp-network/air-gapped install posture). Maintain a backend constant (enum / `frozenset` / typed matrix) listing the offered tags per engine, updated by maintainers.
- This constant is the **single allowlist** the frontend version/engine dropdowns must be grounded in (per CLAUDE.md "Enumerated Value Contract Discipline" — the `<select>` values MUST cite the backend source, and DataTable/form-select lint guards apply). Do NOT let the UI list versions from memory.

## Scope signals

- **Backend:** `reseed_demo_state` + the reseed POST schema gain an `engines` filter (validated against an engine enum). New (or extended) capability endpoint to report which engines are provisioned/running + their versions. New curated version-matrix constant + its enum-discipline export to `ui/src/lib/enums.ts`. ES/OS have **no** version-floor/version-report logic today (only Solr does via `probe_capabilities`) — adding version reporting for ES/OS is net-new.
- **Frontend:** Selection modal on the reset-to-demo button (engine checkboxes, optional read-only version display) grounded in the backend allowlist; pass `engines` to the reseed call; keep/extend the existing status renderer. Regenerate `ui/openapi.json` + `types.ts`.
- **Infra / Compose:** `profiles:` on the three engine services; parameterized image tags; `install.sh` selection step + non-interactive flags; update `.env.example` + the local-dev / corp-install runbooks.
- **CI:** The backend lane's ES + OS service containers are declared **directly in [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml)** (lines 439 / 455), not via the Compose engine services — so Compose `profiles:` defaults will **not** affect backend CI. The **smoke job** does use Compose ([pr.yml:848](../../../../../.github/workflows/pr.yml#L848), [:887](../../../../../.github/workflows/pr.yml#L887)) and must explicitly opt into all three engine profiles (e.g. `COMPOSE_PROFILES=es,os,solr make up` in the smoke job) so it preserves three-engine coverage even when the operator default flips to a subset. Coordinate with [`infra_pr_yml_split_integration_by_service`](../infra_pr_yml_split_integration_by_service/idea.md) — that idea's per-engine shard topology becomes more interesting if the operator can run RelyLoop with a single engine.
- **Migration:** None expected (no schema change — selection is config + request-param, not persisted state).
- **Config:** New env vars — `ES_IMAGE_TAG` / `OS_IMAGE_TAG` / `SOLR_IMAGE_TAG`, an engine-selection var (e.g. `RELYLOOP_ENGINES` / `COMPOSE_PROFILES`), and the non-interactive version overrides.
- **Audit events:** N/A (pre-MVP3; `_test` reseed is not an audited business mutation).

## Open forks to resolve at spec time

1. **Streaming mechanism (C):** keep the existing 2s Redis poll, or migrate reseed status to SSE? (Recommend: keep poll for v1.)
2. **Version picker in reset-to-demo (B):** show running version read-only, or omit version from the reset modal entirely and make version a startup-only concept? (Recommend: engine-only in the reset modal; version lives at startup.)
3. **Interactive vs flag-driven install selection (A):** does `install.sh` prompt interactively, or only accept env/flags (interactive prompts complicate CI and scripted installs)? (Recommend: flags/env primary, optional interactive prompt when a TTY is present.)
4. **Version-matrix maintenance (D):** how is "last 2 major releases" kept current — manual maintainer bump, or a scripted check? (Recommend: manual curated constant for v1.)
5. **CI impact:** confirm `profiles:` defaults don't break `pr.yml` (which spins ES+OS service containers directly, not via the engine Compose services) or the smoke job (which does use Compose).

## Why P2 / not yet prioritized

The stack works today — all three engines load and the reseed already tolerates unreachable engines, so nothing is broken. This is a developer-experience + startup-latency optimization with real value for single-engine evaluators, but it's not unblocking a felt incident. It also has meaningful cross-layer surface (Compose + install.sh + backend + frontend + CI) and several design forks, so it warrants a real spec rather than an inline fix. Filed in `02_mvp2/` as the current active release (could reasonably move to `04_ga/` as install/deployment polish if MVP2 fills up).

## Relationship to other work

- Extends the demo-reseed engine-tolerance work (`infra_solr_ci_readiness` Phase 1, PR #367) — that made reseed *skip* unreachable engines; this lets the operator *choose* engines up front.
- Touches the same Compose engine-service definitions as the corp-network install series (`chore_corp_install_dx_improvements` and siblings, PRs #517–#529) — coordinate `.env.example` + runbook edits.
- **Coordinate with [`infra_pr_yml_split_integration_by_service`](../infra_pr_yml_split_integration_by_service/idea.md)** (deferred sibling, spun out 2026-06-16): that idea proposes per-engine integration-test shards in `pr.yml`. If this idea ships first, the sibling's shard topology can lean on the same `COMPOSE_PROFILES`-driven engine selection. Neither blocks the other; both touch the CI engine-service surface.
- The version-matrix/enum-discipline piece aligns with the existing source-of-truth lint guards (`data-table-column-discipline`, `form-select-discipline`).
</content>
</invoke>
