<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Smoke job — Solr stability (lever cascade)

**Owner:** `infra_solr_smoke_stability` ([`.github/workflows/pr.yml`](../../.github/workflows/pr.yml) smoke-test job + [`docker-compose.yml`](../../docker-compose.yml) solr service).
**Audience:** a maintainer staring at a red `smoke (operator-path tutorial flow)` job on a PR who needs to know whether to merge anyway, what evidence to read, and what lever to apply next.

This runbook is the sibling of [`demo-reseed-engine-tolerance.md`](./demo-reseed-engine-tolerance.md): that one covers the **backend** job's Solr posture (engine-tolerant reseed, shipped via `infra_solr_ci_readiness` Phase 1 / PR #367); this one covers the **smoke** job's Solr posture (heap cap, shipped via `infra_solr_smoke_stability`). Together they take `pr.yml` from "red on every branch" to "green on every branch."

---

## §1 Why Solr heap is capped at 256m in CI

The smoke job runs `make up` which brings up the full Compose stack including the `solr:10.0` service. On the GHA `ubuntu-24.04` runner, the Solr container's default 512m heap (plus three concurrent JVMs — Elasticsearch + OpenSearch + Solr — plus api/worker/postgres/redis/ui) was triggering Solr container crashes (`relyloop-solr-1 exited (1)`) during boot. The smoke job has caught this on every PR since Solr shipped (2026-05-31).

The cap mirrors the backend job's `ES_JAVA_OPTS: "-Xms256m -Xmx256m"` precedent at [`pr.yml:287`](../../.github/workflows/pr.yml#L287). It is **GHA-only**: the `SOLR_HEAP_SIZE` env var is set in the workflow's "Bring up the stack" step, and Compose's `solr` service reads `${SOLR_HEAP_SIZE:-512m}` ([`docker-compose.yml:274`](../../docker-compose.yml#L274)) — so local dev keeps the 512m default. **Never change the `docker-compose.yml` default** — operators rely on it.

The cap is a **hypothesis**, not a measurement: we sized it against the ES precedent + the runner's documented memory budget, not against a captured Solr-on-the-runner OOM trace. If the cap doesn't fix the crash, the captured Solr logs + `docker inspect` evidence (per §2 below) feed the lever cascade in §3.

---

## §2 When smoke goes red — the diagnostic workflow

The smoke job's failure-diagnostics step uploads a `smoke-logs.txt` artifact containing:
- Compose logs for `api worker postgres redis elasticsearch opensearch solr ui` — per-container, prefixed with the container name (`relyloop-solr-1 | …`).
- One `docker inspect` line per container with fields: `exit=<code> oom=<true|false> error=<msg> health=<status> started=<timestamp> finished=<timestamp>`.
- The api's `/healthz` response (Solr surfaces as a `subsystems.solr` field on a missing-Solr run, NOT as a job failure).

**Step-by-step diagnostic workflow:**

```bash
# 1. Find the failed run
gh run list --workflow pr.yml --branch <feature-branch> --limit 1

# 2. Download the artifact (the upload step is named "Upload failure diagnostics"
#    with artifact name "smoke-logs" per pr.yml:726)
gh run download <run_id> --name smoke-logs --dir /tmp/smoke-artifacts

# 3. Read the Solr container output
grep -E '^solr-1 \|' /tmp/smoke-artifacts/smoke-logs.txt | head -50

# 4. Read the docker inspect exit-state line for Solr
grep 'relyloop-solr-1 exit=' /tmp/smoke-artifacts/smoke-logs.txt

# 5. Classify the failure per §3 below
```

The `oom=true|false` field is the **most diagnostic signal** — it tells you whether the kernel OOM-killed the container (total-runner memory pressure) vs. Solr threw an internal OOM (JVM heap/metaspace/native).

---

## §3 The lever cascade (evidence-mapped, not symptom-mapped)

**Lever 0 (CURRENT baseline — `infra_solr_smoke_stability` data-dir-perms fix):** `mkdir -p ./data/solr && sudo chown 8983:8983 ./data/solr` runs BEFORE `make up` on the smoke job. The `solr:10.0` image runs as UID/GID 8983; on the GHA runner the bind-mount target `./data/solr` defaults to root ownership, so without the pre-create-and-chown step the container's boot script fails at "Cannot write to /var/solr as 8983:8983" and exit(1) within ~500ms. **This is what the diagnostics fold-in actually caught on PR #383's first CI run** — the heap-cap lever was applied at the same time but didn't fix this because the failure mode is filesystem, not memory. Already shipped — do NOT re-apply.

**Lever 1 (CURRENT baseline — `infra_solr_smoke_stability`):** Solr heap capped to 256m via `SOLR_HEAP_SIZE: "256m"` step-env on the smoke job's "Bring up the stack" step + `COMPOSE_PROJECT_NAME: "relyloop"` at job-level env. **Already shipped — do NOT re-apply.** Note: Lever 1 was the spec's locked default but was the WRONG lever for the actual PR #383 failure (FS-perms, not memory); Lever 0 is what fixed it. Lever 1 stays in place as defense against future JVM heap pressure.

**If Lever 1 didn't fix the crash, the smoke artifact tells you which escalation to pick.** Read the Solr logs + `oom=` field first, then choose:

### Memory-pressure escalation — JVM heap/metaspace/native OOM or kernel `oom=true`

**Trigger evidence:**
- The `relyloop-solr-1 ... oom=true` line is present in the docker inspect output (kernel OOM-killer fired), OR
- The Solr Compose logs contain a JVM OOM trace: `java.lang.OutOfMemoryError: Java heap space` / `... Metaspace` / `... Direct buffer memory` / `... unable to create native thread`.

**Why:** Lever 1 already capped Solr heap. If the failure is still memory-related, the root cause is **total-runner pressure** — the smoke Compose stack runs THREE JVM services concurrently (Solr + Elasticsearch + OpenSearch). The backend job caps ES heap (`ES_JAVA_OPTS: -Xms256m -Xmx256m` at [`pr.yml:287`](../../.github/workflows/pr.yml#L287)) but **that env applies to GHA service containers, NOT to the smoke job's Compose stack**. So in smoke, ES and OpenSearch run at their Compose defaults. They need caps too.

**Edit shape:** add `ES_JAVA_OPTS` to the smoke job's `make up` step env (Compose's `elasticsearch` service consumes it), and add a `${OPENSEARCH_JAVA_OPTS:-...}` slot to `docker-compose.yml`'s `opensearch` service + set the env in the smoke step. Multi-file scope. File a new spec — this is not a one-line edit.

### Lever 2 — healthcheck-timing escalation

**Trigger evidence:**
- The Solr Compose logs show successful boot (look for `Started SolrJetty` or `o.e.j.s.Server: Started` near the end of the `relyloop-solr-1 |` lines), AND
- The `docker inspect` line for `relyloop-solr-1` shows `health=unhealthy` or `health=starting` with `started=<early-timestamp> finished=<later-timestamp>`.

**Why:** Solr 10 + the `ltr` module's first-load on a cold runner can take longer than the current healthcheck tolerance window. Solr's effective tolerance is `start_period: 30s` + `interval: 10s` × `retries: 6` with `timeout: 5s` per [`docker-compose.yml:280-285`](../../docker-compose.yml#L280-L285) — up to ~95s total before "unhealthy," depending on Docker's probe scheduling. **Do not use a flat 30s cutoff** — read the inspect line's `started` / `finished` timestamps and compare to the Solr log timing.

**Edit shape:** add a CI-only override mechanism for the Solr healthcheck `start_period` (the exact YAML shape — env-var interpolation in healthcheck values, a docker-compose override file, or a step-level wait-timeout flag — should be locked in the Lever-2 follow-up spec; verify Compose's interpolation support in healthcheck blocks at follow-up time, don't presume now). Must preserve the local-dev default of 30s.

### Lever 3 — smoke-tolerance of Solr-down

**Trigger evidence:**
- Solr is genuinely unavailable (any combination of crash modes from above, OR a transient runner issue), AND
- The smoke path genuinely doesn't depend on Solr.

**Why this needs an audit, not just a grep:** the smoke path depends on Solr **transitively** in several places:
- The api's `/healthz` probes Solr as a subsystem (currently treats missing-Solr as a `subsystems.solr` field, not a job failure — verified in the spec's §2 current state audit).
- Seed/migrate steps (`make seed-clusters`, `make seed-es`) may or may not touch Solr depending on the demo fixtures of the day.
- The tutorial-path smoke pytest (`backend/tests/smoke/test_tutorial_path.py`) is grep-clean for `solr` today, but the tutorial walkthrough flow it exercises could indirectly require Solr if future tutorial changes add it.
- Compose `depends_on` blocks may gate other services on Solr being up.

A single-file grep ("the smoke test doesn't import solr, so we're fine") is **insufficient** — do the full audit before picking Lever 3.

**Edit shape:** change the smoke job's success criteria to tolerate `subsystems.solr: down` in `/healthz`, AND adjust any tutorial-path assertions that implicitly assume Solr availability, AND audit `make seed-*` for Solr dependencies. Multi-file scope, full spec.

---

## §4 Why each lever is GHA-only

Local dev (`make up` on an operator's machine) runs without the CI-only env vars:
- `SOLR_HEAP_SIZE` unset → Compose default 512m applies (preserves operator memory headroom).
- `COMPOSE_PROJECT_NAME` unset → Compose derives from working directory (typically `relyloop`).
- Any future Lever-2 healthcheck override → same pattern (CI-only env, Compose default preserved).

**Never change `docker-compose.yml` defaults to "fix CI"** — that's the wrong scope. The smoke job's runner constraints are not the operator laptop's constraints. Use the env-override-slot pattern (`${VAR:-default}`) to keep the two paths independent.

---

## Related

- [Demo reseed engine tolerance](./demo-reseed-engine-tolerance.md) — backend-job sibling runbook (Phase 1 / PR #367).
- [`infra_solr_smoke_stability` feature spec](../00_overview/implemented_features/2026_06_01_infra_solr_smoke_stability/feature_spec.md) — the design decisions D-1 through D-6 (heap cap rationale, single-PR delivery vs two-PR sequencing, red-merge allowed under D-6, etc.). _(Path moves to `implemented_features/` after merge per the impl-execute finalization step.)_
- [`.github/workflows/pr.yml`](../../.github/workflows/pr.yml) — the smoke-test job (~line 487-740).
- [`docker-compose.yml`](../../docker-compose.yml) — the solr service (~line 271-285).
