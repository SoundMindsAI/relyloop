# Feature Specification — chore_tutorial_polish

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-30, US-31
- [docs/00_overview/product/relevance-copilot-spec.md §27](../../../00_overview/product/relevance-copilot-spec.md) — MVP1 release definition
- [docs/01_architecture/deployment.md](../../../01_architecture/deployment.md)
- [docs/01_architecture/mvp1-overview.md](../../../01_architecture/mvp1-overview.md)
- Depends on: ALL prior MVP1 features (this is the release-readiness step)

---

## 1) Purpose

- **Problem:** Even with all 11 prior features shipped, the tutorial — the single demo asset for design-partner recruitment — needs to actually work on a fresh laptop in under 30 minutes. Without a deliberate polish pass that validates the end-to-end flow on a clean VM and writes the supporting tutorial doc, MVP1 ships broken for new users.
- **Outcome:** The release tag `v0.1.0` is pushed with: a worked tutorial at `docs/08_guides/tutorial-first-study.md`, sample data (50-query set + pre-baked judgment list + sample ES index of ~1,000 docs), README polish, a containerized UI (`ui` Compose service), 80% backend coverage gate enforced in CI, smoke-test pass on a fresh Ubuntu 24.04 VM, and a 5–7 minute demo screen recording.
- **Non-goal:** No new features. No new endpoints. No schema changes. No image signing (deferred to GA v1 unless cheap). No Helm chart. No production install doc beyond the basic tutorial.

## 2) Current state audit

After all 11 prior features ship:
- The full Karpathy loop works end-to-end via the UI; chat agent works.
- README.md still describes "pre-MVP1" status.
- No tutorial doc at `docs/08_guides/tutorial-first-study.md`.
- No `samples/` directory — must be created.
- UI runs via `pnpm dev` (not yet containerized in Compose per [`deployment.md`](../../../01_architecture/deployment.md)).
- `pr.yml` enforces 80% coverage on `backend/` (per `infra_foundation` FR-4) but no smoke-test job.
- No `v0.1.0` tag.

## 3) Scope

### In scope

- **Worked tutorial** at `docs/08_guides/tutorial-first-study.md`:
  - Step 0: Prerequisites (Docker, OpenAI API key, GitHub PAT optional but recommended for the apply step)
  - Step 1: Clone + `make up`
  - Step 2: Run `scripts/seed_es.py` (or equivalent) to populate the sample ES index from `samples/products.json`
  - Step 3: In the UI, register `local-es` (or via `make seed-clusters`)
  - Step 4: Create a query set from `samples/queries.csv` (50 hand-curated queries)
  - Step 5: Generate judgments (or use pre-baked `samples/judgments.json` to skip OpenAI cost on first run)
  - Step 6: Create a query template from `samples/templates/product_search.j2`
  - Step 7: Open chat, ask the agent to tune
  - Step 8: Watch the study run; read the digest
  - Step 9: (Optional) Open the PR against `samples/sample-config-repo` (a fixture)
  - Each step has expected output (screenshots / JSON snippets) so users can verify they're on track
- **`samples/` directory** at repo root:
  - `samples/products.json` — ~1,000 sample products (e-commerce-ish; see open question on dataset choice)
  - `samples/queries.csv` — 50 hand-curated queries
  - `samples/judgments.json` — pre-baked judgment list (so first-run users don't pay for OpenAI judgments)
  - `samples/templates/product_search.j2` — Jinja2 template with multi_match + field_boosts + tie_breaker + fuzziness as parameters
  - `samples/sample-config-repo.tar.gz` — a tarball that the operator can extract + push to their own GitHub for the apply step (or a public test repo on `SoundMindsAI` org per `feat_github_pr_worker` open question)
  - `scripts/seed_es.py` — populates the local ES container with `samples/products.json`
- **`ui` Compose service** — containerize the Next.js app; add to `docker-compose.yml` with `depends_on: [api]` and bind to `127.0.0.1:3000`. Build the Docker image locally in the same `pr.yml` CI workflow. The `make up` script is updated to include the `ui` service.
- **README polish**:
  - Replace "Status: pre-MVP1" with "Status: alpha (MVP1, v0.1)"
  - 5-minute quickstart at the top
  - Value-proposition section
  - "What's in MVP1 / what's coming" honest list
  - Links to spec, comparison-with-Quepid stub (a one-paragraph "How RelyLoop compares to Quepid" — see open question), and CONTRIBUTING
- **`pr.yml` extension** — add a smoke-test job that:
  - Provisions a fresh Ubuntu runner
  - Runs `make up`
  - Waits up to 90s for `/healthz` to return `status: ok`
  - Runs the tutorial's first 5 steps non-interactively (registers cluster, creates query set from CSV, uses the pre-baked judgments, creates template, kicks off a study with `max_trials=10`)
  - Asserts the study completes within 5 min
  - Asserts the digest is generated
  - Tears down (`make reset`)
- **Cosign image signing** — IF cheap to add (the workflow already has GitHub OIDC); push signed images `ghcr.io/relyloop/api:0.1.0`, `ghcr.io/relyloop/ui:0.1.0`, `ghcr.io/relyloop/worker:0.1.0`. If complexity > 1 hour, defer to MVP3.
- **Demo recording** (5–7 min screencast) — record a fresh-laptop run-through; host as YouTube unlisted; link from README.
- **`v0.1.0` Git tag** + GitHub Release with notes summarizing scope + audience + feedback channels.
- **Coverage-gate verification** — confirm `pr.yml` enforces 80% backend coverage and the project passes (per `infra_foundation` FR-4).
- **Final issue sweep** — fix any P0 paper-cuts surfaced by the smoke test on a fresh VM (e.g., a port collision, a missing healthcheck retry, a confusing error message).

### Out of scope

- Helm chart, Kubernetes manifests — v1.5+.
- Production install doc with TLS / SSO — MVP3+.
- Container scanning (Trivy), Python deps audit (pip-audit), TS deps audit (npm audit) — GA v1.
- Image signing IF complex (>1h work) — GA v1 fallback.
- Multi-region / multi-cloud — never (per [`tech-stack.md`](../../../01_architecture/tech-stack.md)).
- WCAG AA / i18n — never.
- New features of any kind — MVP2+ scope.

### API convention check

N/A — release polish, no new APIs.

### Phase boundaries

Single-phase. The MVP1 deliverable: "the `v0.1.0` tag is pushed with passing CI + the smoke test, the README polished, the demo recorded, and the tutorial works on a fresh Ubuntu 24.04 VM in under 30 minutes."

## 4) Product principles and constraints

- **The smoke test on a fresh VM is the gate.** If it doesn't pass, MVP1 is not shipped. No exceptions.
- **Sample data must be public-license.** Per umbrella spec §27 line 2312 and the open scope question. No proprietary or unclear-license content.
- **Tutorial works without OpenAI on first run.** Pre-baked `samples/judgments.json` lets new users skip the OpenAI cost (and the OpenAI dependency) on their first read-through. They can regenerate judgments with their own key once they're sold.
- **Demo recording is short.** 5–7 min, not 20. Captures: clone, `make up`, register cluster, create study via chat, watch trial table, see digest, click Open PR.

### Anti-patterns

- **Do not** ship MVP1 with the tutorial flow broken on a fresh VM. The smoke-test gate exists to prevent this.
- **Do not** include any sample data with unclear license. Public-domain or permissive only (Apache, MIT, CC0).
- **Do not** require >5 min of operator time for the "I just want to see what this does" path (the pre-baked judgments make this possible).
- **Do not** add new features in this feature. New scope creates new bugs the smoke test won't catch.

## 5) Assumptions and dependencies

- **Dependency: ALL 11 prior MVP1 features** shipped and merged.
- **Sample dataset license cleared** (per open question — recommend Amazon ESCI).
- **Public test config repo** (per `feat_github_pr_worker` open question — recommend `SoundMindsAI/relyloop-test-configs` public repo) OR the tarball pattern.
- **`SoundMindsAI` GitHub org has GHCR enabled** for image publishing (per umbrella §27 line 2563 & §28).
- **YouTube account** for hosting the demo recording (or alternative host like Loom).

## 6) Actors and roles

- **Primary actor:** New Relevance Engineer (clones the repo, follows the tutorial, decides whether to bring RelyLoop to their team).
- **Secondary actor:** the Maintainer (writes the tutorial, records the demo, validates the smoke test, pushes the `v0.1.0` tag).

### Authorization

N/A.

### Audit events

N/A.

## 7) Functional requirements

### FR-1: Worked tutorial doc
- The system **MUST** ship `docs/08_guides/tutorial-first-study.md` with all 9 steps per §3.
- Each step **MUST** include: command(s) to run, expected output (text or screenshot), troubleshooting hint for the most common failure mode.
- The tutorial **MUST** be doable in under 30 min on a fresh 16GB laptop with the pre-baked judgments path (no OpenAI cost on first run).

### FR-2: Sample data + seed script
- The system **MUST** ship `samples/products.json` (~1,000 docs), `samples/queries.csv` (50 queries), `samples/judgments.json` (pre-baked LLM judgments for the 50 queries × 50 docs), `samples/templates/product_search.j2` (the canonical demo template).
- The system **MUST** ship `scripts/seed_es.py` that populates the local ES container's `products` index from `samples/products.json` idempotently.
- All sample content **MUST** be under a public license (Amazon ESCI / CC-BY-4.0 or similar; documented in `samples/LICENSE` and the README).

### FR-3: UI containerization
- The system **MUST** add a `ui` service to `docker-compose.yml`:
  - `image: relyloop/ui:latest` (built from `ui/Dockerfile`)
  - `depends_on: [api]`
  - `environment: { NEXT_PUBLIC_API_BASE_URL: http://localhost:8000 }`
  - `ports: ["127.0.0.1:3000:3000"]`
- The system **MUST** ship `ui/Dockerfile` using Node 20 + pnpm, multi-stage build (builder → runner).
- The `make up` workflow **MUST** include the `ui` service (`docker compose up -d` brings it up automatically since it's in the compose file).

### FR-4: Smoke-test CI job
- `.github/workflows/pr.yml` **MUST** include a `smoke-test` job that runs on every PR (in parallel with the existing lint/typecheck/test jobs):
  - Provisions an Ubuntu 24.04 runner (or `ubuntu-latest`)
  - Runs `make up` and waits up to 90s for `/healthz`
  - Runs the tutorial's first 5 steps non-interactively (via a Python script that exercises the API)
  - Kicks off a 10-trial study; waits up to 5 min for completion
  - Asserts a digest exists for the study
  - Tears down via `make reset`
  - Job fails if any step fails or any timeout exceeded

### FR-5: README polish
- The README **MUST**:
  - Show "Status: alpha (MVP1, v0.1.0)" at the top
  - Have a 5-minute quickstart section above the fold
  - Explain the value proposition in 2-3 sentences
  - Link to the tutorial, the umbrella spec, the architecture index, and CONTRIBUTING
  - List "What's in MVP1 / What's coming in MVP2/3/4/GA v1" in a compact table referencing [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)

### FR-6: Image publishing
- `pr.yml` (or a new `release.yml` triggered on tag push) **MUST** build + push:
  - `ghcr.io/relyloop/api:0.1.0`
  - `ghcr.io/relyloop/ui:0.1.0`
  - `ghcr.io/relyloop/worker:0.1.0` (same image as `api` per [`deployment.md`](../../../01_architecture/deployment.md), different tag for clarity)
- IF cosign signing is achievable in <1 hour effort, sign all three images via keyless OIDC. Otherwise defer to GA v1.

### FR-7: Demo recording
- A 5-7 minute screen recording **MUST** be produced showing: clone, `make up`, register cluster (or `make seed-clusters`), create study via chat agent, watch trial table fill in, see digest, click Open PR.
- The recording **MUST** be hosted (YouTube unlisted, Loom, or similar) and linked from README.

### FR-8: Tag + Release
- A `v0.1.0` Git tag **MUST** be pushed against the merge commit.
- A GitHub Release **MUST** be created with notes summarizing:
  - What's in MVP1 (capabilities)
  - Audience (technical evaluators)
  - How to install (link tutorial)
  - How to provide feedback (link GitHub Discussions / issue template)

## 8) API and data contract baseline

N/A — no new APIs.

## 9) Data model and state transitions

N/A — no schema changes.

## 10) Security, privacy, and compliance

- **Threats:**
  1. Sample data containing PII (e.g., real customer reviews). **Mitigation:** use only public datasets with explicit license.
  2. The pre-baked `samples/judgments.json` contains rationales generated by an OpenAI call on the maintainer's account. **Mitigation:** the maintainer reviews the rationales for sensitivity before committing; rationales are about generic e-commerce queries.
  3. Image publishing without signing → adopters can't verify provenance. **Mitigation:** cosign signing if achievable in <1h; otherwise warn in the README that GA v1 will introduce signed images.
- **Auditability:** N/A.

## 11) UX flows and edge cases

This feature has no in-product UI. The "UX" is the README + tutorial.

### Edge/error flows

- **`make up` fails on the fresh VM** (port conflict, insufficient memory). The smoke test catches and fails the PR; the tutorial step 1 documents the recovery (`docker compose down -v && rm -rf data && make up`).
- **OpenAI key not configured but operator skips the pre-baked judgments path.** The judgment-generate API returns `OPENAI_NOT_CONFIGURED` (per `feat_llm_judgments`); the tutorial's troubleshooting section explains this.
- **Sample dataset URL changes** (e.g., Amazon ESCI moves). Bake the dataset into the repo, not a fetch-on-build URL.

## 12) Given/When/Then acceptance criteria

### AC-1: Tutorial succeeds on fresh VM in <30 min

- Given a fresh Ubuntu 24.04 VM (16GB, 4 vCPU) with Docker installed and no prior RelyLoop containers.
- When the operator follows `docs/08_guides/tutorial-first-study.md` from clone through digest review.
- Then the operator completes all 9 steps in under 30 minutes.

### AC-2: Smoke test passes in CI

- Given a PR is opened.
- When the `smoke-test` job runs.
- Then the job completes successfully within 15 minutes (clone + image pull + boot + 10-trial study + teardown).

### AC-3: 80% backend coverage gate

- Given the merged main branch.
- When CI runs.
- Then `coverage` reports ≥80% on `backend/` and the gate passes.

### AC-4: README is informative

- Given a stranger lands on the GitHub repo.
- When they read the README in 60 seconds.
- Then they understand: what RelyLoop does, who it's for, how to try it (5-min quickstart link), what's in MVP1 vs later releases.

### AC-5: Pre-baked judgments path works without OpenAI key

- Given a fresh VM with `OPENAI_API_KEY_FILE` empty.
- When the operator follows the tutorial up to and including the study run, using the pre-baked `samples/judgments.json`.
- Then the study completes successfully (judgments are loaded from the JSON file via the API, not regenerated). The digest WILL fail (no OpenAI key for narrative); the tutorial documents this and instructs the user to skip the digest step OR set the OpenAI key for that one step.

### AC-6: Demo recording exists and is linked

- Given the `v0.1.0` tag is pushed.
- When the operator opens the README.
- Then a clickable link to a 5–7 minute demo recording is in the "What it looks like" section. The link resolves to a working video.

### AC-7: Tag + Release published

- Given the smoke test passes on the merge commit.
- When the maintainer pushes the tag.
- Then a GitHub Release exists at `github.com/SoundMindsAI/relyloop/releases/tag/v0.1.0` with the documented notes structure.

### AC-8: Images published

- Given the tag push triggers `release.yml` (or `pr.yml` extension).
- When CI runs.
- Then `ghcr.io/relyloop/{api,ui,worker}:0.1.0` are published. (Cosign signatures attached IF FR-6 cosign branch achievable.)

## 13) Non-functional requirements

- **Performance:** Smoke test completes in <15 min (image pull dominates first run; <5 min on warm runner).
- **Reliability:** Smoke test passes deterministically; flaky failures get fixed before merge (no retries-as-feature).
- **Operability:** Failed smoke test logs are scoped enough to diagnose: which step failed, what the API/worker logs said, what `/healthz` returned.

## 14) Test strategy requirements

- **Smoke test** (CI-only):
  - `tests/smoke/test_tutorial_path.py` — orchestrates the API calls that mirror the tutorial steps; asserts the study completes and the digest is generated.
- **Manual VM test:**
  - Documented procedure in `docs/03_runbooks/release-checklist.md`: spin up a fresh VM (or local clean Docker state), run the tutorial start-to-finish, time it, file any P0 issues found.
- **No new unit/integration tests** — this feature consumes the existing test surface.

## 15) Documentation update requirements

- `docs/08_guides/tutorial-first-study.md` — NEW (the tutorial).
- `docs/08_guides/README.md` — index pointing at the tutorial.
- `docs/03_runbooks/release-checklist.md` — NEW (manual VM test, tag + release procedure).
- `docs/01_architecture/deployment.md` — UPDATE: add the `ui` service to the documented Compose layout.
- `docs/02_product/mvp1-user-stories.md` — mark US-30 / US-31 as "implemented".
- Root `README.md` — major polish per FR-5.

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** N/A.
- **Operational readiness gates:**
  - Smoke test passes on the merge commit
  - 80% coverage gate green
  - Manual fresh-VM tutorial run logged in the release-checklist runbook
  - Demo recording uploaded + linked
- **Release gate:** maintainer pushes `v0.1.0` tag; GitHub Release published with notes.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (tutorial) | AC-1, AC-5 | TBD | (manual + smoke) | tutorial.md |
| FR-2 (samples) | AC-1, AC-5 | TBD | `tests/smoke/test_tutorial_path.py` | tutorial.md |
| FR-3 (UI containerization) | AC-1 | TBD | (smoke covers via `docker compose up`) | deployment.md |
| FR-4 (smoke test) | AC-2 | TBD | `tests/smoke/test_tutorial_path.py` | release-checklist.md |
| FR-5 (README polish) | AC-4 | TBD | (manual review) | README.md |
| FR-6 (image publishing) | AC-8 | TBD | (release.yml workflow) | deployment.md |
| FR-7 (demo recording) | AC-6 | TBD | (manual) | README.md |
| FR-8 (tag + release) | AC-7 | TBD | (manual) | release-checklist.md |

## 18) Definition of feature done

- [ ] AC-1 through AC-8 pass.
- [ ] Manual fresh-VM tutorial run logged in `docs/03_runbooks/release-checklist.md` with timing.
- [ ] All MVP1 user stories US-1 through US-31 marked "implemented" in `mvp1-user-stories.md`.
- [ ] `v0.1.0` GitHub Release published with notes.
- [ ] Demo recording uploaded + linked from README.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — The smoke test is the release gate, not optional — per umbrella spec §27 strategic-rationale and the project's "fail loudly" principle.
- 2026-05-09 — Pre-baked `samples/judgments.json` so first-run users don't pay OpenAI cost — adoption-funnel hygiene. Imported via `POST /api/v1/judgment-lists/import` (added to `feat_llm_judgments` FR-3b).
- 2026-05-09 — Container UI as part of MVP1 (not a post-release polish) — `make up` should bring the full stack including UI; running `pnpm dev` is a developer-mode optimization, not the user-facing path.
- 2026-05-09 — Test config repo: **public `SoundMindsAI/relyloop-test-configs`** — same repo serves both `feat_github_pr_worker` integration tests and the tutorial's apply-PR step. Public repo + dedicated test PAT scoped only to it. Operator instructions in the tutorial point at this repo for the demo apply step.
- 2026-05-09 — Sample dataset: **Amazon ESCI subset** (publicly licensed CC-BY-4.0; ~1,000 products + 50 queries subsetted from the upstream 1.5M × 1.8M dataset). Pre-existing ESCI judgments seed `samples/judgments.json` so first-run users get a working tutorial without OpenAI cost.
- 2026-05-09 — Quepid comparison stub: **skip for MVP1**; add at MVP2 once feature parity is more defined.
- 2026-05-09 — Cosign signing: **ship if achievable in <1 hour effort at implementation time**; otherwise defer to GA v1 (empirical decision, not blocking).
- 2026-05-09 — Demo recording host: **YouTube unlisted** (free, ubiquitous, embed-friendly).
