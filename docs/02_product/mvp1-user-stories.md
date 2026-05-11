# MVP1 User Stories

**Status:** Source-of-truth user-story enumeration for MVP1 ("The Loop"). Each story is referenced by ID (`US-N`) from the matching feature_spec.md in `planned_features/<folder>/`.

**Source material:**
- Umbrella spec [§6 Personas & user stories](../00_overview/product/relevance-copilot-spec.md) (lines 85–100) — system-level stories
- Umbrella spec [§27 MVP1 scope](../00_overview/product/relevance-copilot-spec.md) (lines 2286–2322) — in-scope capabilities
- Umbrella spec §8, §12, §14, §15, §16, §19, §22 — capability detail

**Scope boundary:** MVP1 only. Stories that depend on later-release capabilities (Langfuse → MVP2; Lucidworks Fusion + GitLab/Bitbucket → MVP3; multi-tenant + multi-LLM provider abstraction + SSO + API keys → MVP4; LangGraph state graph + subagents + PostgresSaver → GA v1) are explicitly out of scope and live in their respective release plans. See [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../01_architecture/tech-stack.md) for the source of truth.

---

## Personas

- **Relevance Engineer (primary user).** Runs studies, reviews digests, opens proposals. Comfortable with JSON, ES query DSL, and command-line tools. The persona MVP1 is built for.
- **GitHub reviewer (config-repo branch protection).** Per umbrella §18: there is **no "approver" role inside RelyLoop**. Approval is enforced in the config repo's branch protection / merge protection rules — CODEOWNERS (GitHub), approval rules (GitLab at MVP3), default reviewers (Bitbucket at MVP3) determine who must review what. The reviewer is whoever the config repo says it is, governed entirely outside RelyLoop.
- **Viewer.** Read-only stakeholder (PM, exec, peer engineer) who looks at the UI but doesn't run studies. *(MVP1 has no auth, so viewer/engineer distinction is conventional rather than enforced. Role enforcement arrives at MVP4 with `viewer` / `runner` / `tenant_admin` per umbrella §18.)*

**MVP1 deployment context:** single-tenant, single-install, no auth. All users see all data. Multi-tenant scoping + SSO + API keys arrive in MVP4.

---

## Stories grouped by feature

### `infra_foundation` — boot the system

- **US-1: Boot the stack locally.** *As a Relevance Engineer*, I run `make up` (which auto-generates required secret files on first run, then runs `docker compose up -d`) and within 60s have Postgres, Redis, the API backend, the worker pool, and a local ES + OpenSearch container all healthy, so I can start using RelyLoop without provisioning external infrastructure. *(Source: umbrella §25, §27; install-script details in [`docs/01_architecture/deployment.md` §"Operator workflow"](../01_architecture/deployment.md).)*
- **US-2: Verify the install with a health check.** *As a Relevance Engineer*, I curl `/healthz` and get a JSON response listing each subsystem's status (db: ok, redis: ok, openai: configured, ES: reachable), so I can diagnose setup problems before running a study. *(Source: §23, §27.)*
- **US-3: Configure secrets via mounted files.** *As a Relevance Engineer*, I copy `.env.example` to `.env`, write secret values into `./secrets/<name>` files (`./secrets/openai_key`, optionally `./secrets/github_token`), and the stack mounts them into containers via Docker secrets, so I never put credentials in env vars and never check them into git. *(Source: umbrella §25, §28; mechanism documented in [`docs/01_architecture/deployment.md` §"Secrets"](../01_architecture/deployment.md).)*

### `infra_adapter_elastic` — talk to Elasticsearch + OpenSearch

- **US-4: Register a target cluster.** *As a Relevance Engineer*, I add a cluster row (URL, auth, engine_type=`elasticsearch` or `opensearch`) and the system probes it for connectivity, so I can confirm reachability before running a study. *(Source: §8 lines 159–262, §22.)*
- **US-5: Inspect the index schema.** *As a Relevance Engineer*, I select a cluster + index target and see the field list (name, type, analyzer, doc count), so I know which fields I can boost in my template. *(Source: §8 `get_schema`, §19 `get_schema`.)*
- **US-6: Validate a query against the cluster.** *As a Relevance Engineer*, I paste a query DSL fragment into a "Test query" form and see the top-10 hits with scores, so I can debug template issues without leaving the UI. *(Source: §19 `run_query`.)*

### `infra_optuna_eval` — score trials

- **US-7: See nDCG@10, MAP, and P@10 for a trial.** *As a Relevance Engineer*, after a trial runs I see all three metrics computed by pytrec_eval against the configured judgment list, so I can compare trials on the metric I care about (objective) and on backups (sanity check). *(Source: §14 lines 686–755, §13 lines 676–685.)*
- **US-8: Optuna picks the next trial parameters.** *As a Relevance Engineer*, I trust that Optuna's TPE sampler is choosing the next parameter combination based on the running history (not random), so my study converges faster than a brute-force sweep would. *(Source: §13 lines 676–685.)*

### `feat_study_lifecycle` — orchestrate a study

- **US-9: Create a study.** *As a Relevance Engineer*, I create a study by selecting cluster + target + template + query set + judgment list + search space + objective + stop conditions (max_trials, time_budget_min), so I can kick off an overnight tuning run with one form. *(Source: §12 lines 648–675, §22 `/studies`.)*
- **US-10: Watch the study progress live.** *As a Relevance Engineer*, I open the study detail page and see trials completing in real time (status, params, metric value, time), so I can spot a misconfigured study early instead of waiting overnight. *(Source: §12, §22 `/studies/{id}`.)*
- **US-11: Cancel a running study.** *As a Relevance Engineer*, I hit a "Cancel" button on a running study and within 30s no new trials are scheduled and in-flight trials complete cleanly, so I can stop a clearly-broken study without restarting the worker. *(Source: §12.)*
- **US-12: Resume after restart.** *As a Relevance Engineer*, if the worker pool restarts mid-study, the study picks up where it left off (Optuna RDB persists trial history), so I don't lose 4 hours of work to a Docker hiccup. *(Source: §12, §13.)*

### `feat_llm_judgments` — generate relevance judgments

- **US-13: Generate judgments via LLM for a query set.** *(Implemented — `feat_llm_judgments`)* *As a Relevance Engineer*, I select a query set + cluster + target + rubric and the system uses OpenAI to rate each (query, doc) pair on a 0–3 scale, producing a judgment list I can use in a study, so I don't need to commission human labels for a quick eval. *(Source: §14 lines 735–756, §19 `generate_judgments_llm`.)*
- **US-14: Review LLM ratings and override.** *(Implemented — `feat_llm_judgments`)* *As a Relevance Engineer*, I open the judgment review page, see all (query, doc) ratings with the LLM's brief reason, and click to override 0→3 or 3→0 on the ones I disagree with, so I can correct LLM mistakes without re-generating the whole list. *(Source: §22 `/judgments/{id}`, top stories #5 from §6. UI lands with `feat_studies_ui`; API surface for overrides is `PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}`.)*
- **US-15: See calibration stats vs. a sample of human judgments.** *(Implemented — `feat_llm_judgments`)* *As a Relevance Engineer*, when I provide a small set of human-labeled judgments alongside the LLM-generated ones, the system computes Cohen's kappa or weighted agreement and shows it on the judgment review page, so I know whether to trust the LLM ratings before running a study against them. *(Source: §14, §19 `get_calibration`. API surface is `POST /api/v1/judgment-lists/{id}/calibration`; UI lands with `feat_studies_ui`.)*

### `feat_digest_proposal` — summarize a completed study

- **US-16: Get a digest after the study completes.** *(Implemented — `feat_digest_proposal`)* *As a Relevance Engineer*, when a study finishes I get a digest page with a narrative summary, the recommended parameter values, parameter importance bar chart, and metric delta vs. baseline, so I can decide in 60 seconds whether to open a PR. *(Source: §15 lines 762–1003, §22 `/studies/{id}` digest panel. API surface is `GET /api/v1/studies/{id}/digest`; UI lands with `feat_studies_ui`.)*
- **US-17: Create a proposal from the digest.** *(Implemented — `feat_digest_proposal`)* *As a Relevance Engineer*, I click "Create proposal" on a digest and a proposal row is created with the recommended config snapshot, so the recommendation is captured as a reviewable artifact even before I open a PR. *(Source: §16, §19 `create_proposal_from_study`. The digest worker UPDATEs the orchestrator-inserted pending `proposals` row in place with the deterministically computed `config_diff` + `metric_delta`; the manual-proposal endpoint `POST /api/v1/proposals` ships the hand-crafted flow.)*

### `feat_github_pr_worker` — open a GitHub PR with the new config

- **US-18: Open a PR from a proposal.** *(Implemented — `feat_github_pr_worker`)* *As a Relevance Engineer*, I click "Open PR" on a proposal and within 60s a GitHub PR appears against the configured config repo, with the `*.params.json` diff, a structured commit message (study ID, metric delta, top params), and a PR body containing the parameter importance chart + top-10 trials table + metric comparison, so my approver has everything they need in the PR itself. *(Source: §16 lines 1003–1150, top stories #1 from §6. API surface: `POST /api/v1/proposals/{id}/open_pr` enqueues the `open_pr` worker — see [`docs/03_runbooks/pr-open-debugging.md`](../03_runbooks/pr-open-debugging.md) for the operator playbook. UI lands with `feat_proposals_ui`.)*
- **US-19: PR diff is small and only touches `*.params.json`.** *(Implemented — `feat_github_pr_worker`)* *As whoever the config repo's branch protection routes the PR to (a CODEOWNER / GitHub reviewer / merge-rights holder)*, when I review the PR the diff is purely scalar parameter changes (not template structure), so I can review and merge in 2 minutes without engineer judgment on template safety. RelyLoop has no "approver" role of its own — the routing comes from the config repo's branch protection per umbrella §18. *(Source: umbrella §16, §18. The worker only edits `{template_name}.params.json` under `cluster.config_path` and commits the parameter-importance PNG to `.relyloop/digest-charts/`; it never touches template structure, mappings, or analyzer settings — enforced by `validate_config_path` + path-containment check.)*

### `feat_github_webhook` — track PR state

- **US-20: See the PR state in the proposal UI.** *As a Relevance Engineer*, the proposal page shows the PR's current state (pr_opened → pr_merged → deployed), updated within 30s of a state change in GitHub, so I don't have to switch to GitHub to know whether my proposal landed. *(Source: §16 lines 1123–1150, §22 `/proposals/{id}`.)*
- **US-21: PR state survives webhook misses.** *As a Relevance Engineer*, even if a webhook delivery fails, a polling job reconciles PR state every 15 minutes, so the UI doesn't get permanently stuck on `pr_opened` for a PR that's already merged. *(Source: §16.)*

### `feat_studies_ui` — manage studies in the browser

- **US-22: List my studies with filters.** *(Implemented — `feat_studies_ui`)* *As a Relevance Engineer*, I see a list of all studies filterable by status (queued, running, completed, cancelled), cluster, and date, so I can find the study I ran last Tuesday without searching by ID. *(Source: §22 `/studies`.)*
- **US-23: See the trials table for a study.** *(Implemented — `feat_studies_ui`)* *As a Relevance Engineer*, on the study detail page I see all trials with their parameters, metric, and runtime, sortable by metric so the best trial is at the top, so I can investigate why a particular parameter combo won. *(Source: §22 `/studies/{id}`.)*
- **US-24: View a parameter importance chart.** *(Implemented — `feat_studies_ui`)* *As a Relevance Engineer*, the digest panel shows a bar chart (rendered with recharts) of parameter importance computed by `optuna.importance`, so I can see at a glance which parameters drove the win. *(Source: §15, §22.)*

### `feat_chat_agent` — natural-language access to the loop

- **US-25: Tune a template via chat.** *As a Relevance Engineer*, I type "tune our product-name template against `qs_modelnums` overnight on staging-products-es" into the chat, and the agent creates a study with reasonable defaults (search space, objective, max_trials, time_budget) and confirms before kicking off, so I don't have to fill out the create-study form for routine runs. *(Source: §6 top story #1, §15 lines 762–872, §19, §21 lines 1391–1601.)*
- **US-26: Ask "how is my study doing?".** *As a Relevance Engineer*, mid-study I ask the agent for status and get a short summary (trials completed, current best metric, ETA, any errors), so I don't need to navigate to the studies page just to check progress. *(Source: §19 `get_study`, §21.)*
- **US-27: Tool calls are visible and explainable.** *As a Relevance Engineer*, when the agent calls a tool (e.g., `create_study`, `run_query`) I see the tool name + arguments + result in an expandable panel in the chat, so I can audit what the agent actually did and learn the API by example. *(Source: §15, §22 `/chat/{conversation_id}`.)*

### `feat_proposals_ui` — review and apply tuned configs

- **US-28: List proposals with PR state.** *As a Relevance Engineer*, I see a proposals list filterable by status (pending, pr_opened, pr_merged, rejected) and cluster, so I can check at a glance which tuned configs are awaiting review. *(Source: §22 `/proposals`.)*
- **US-29: See the config diff in the proposal detail.** *As a Relevance Engineer*, on the proposal detail page I see a side-by-side diff of the proposed `*.params.json` changes vs. current, plus the metric delta, plus a link to the originating study, so I can review the recommendation before clicking "Open PR". *(Source: §22 `/proposals/{id}`, §16.)*

### `chore_tutorial_polish` — onboarding quality

- **US-30: Complete the tutorial in under 30 minutes on a fresh laptop.** *As a Relevance Engineer (new user)*, I follow the tutorial in `docs/08_guides/tutorial-first-study.md` from `git clone` through "PR opened in GitHub" in under 30 minutes on a 16GB laptop, so I form a positive first impression and decide to bring RelyLoop to my team. *(Source: §27 lines 2310, 2312, 2322 — "Demonstrates the value prop", "design partners".)*
- **US-31: Sample data lets me skip my own setup.** *As a Relevance Engineer (new user)*, the tutorial includes a 50-query set + pre-baked judgment list + sample ES index of ~1,000 products, so I can run the loop end-to-end without having to provide my own data. *(Source: §27 line 2312.)*

### Cross-cutting — LLM provider flexibility

- **US-32: Air-gapped evaluation against a local LLM.** *As a privacy-conscious Relevance Engineer (or one without an OpenAI account)*, I configure RelyLoop to use a local LLM via Ollama / LM Studio / vLLM / HuggingFace TGI by setting `OPENAI_BASE_URL` and `OPENAI_MODEL` in `.env` before `make up`. The startup capability check probes my local endpoint and surfaces in `/healthz` whether chat / function-calling / structured-output all work. Features that need capabilities my local model doesn't support either gate themselves with `LLM_PROVIDER_INCAPABLE` (judgment generation needs structured output) or degrade gracefully (chat agent runs without tool dispatch; digest falls back to narrative-only). The tutorial in `chore_tutorial_polish` documents both the hosted-OpenAI and local-LLM paths side-by-side. *(Source: per [`docs/01_architecture/llm-orchestration.md` §"OpenAI-compatible endpoints"](../01_architecture/llm-orchestration.md). Cross-cuts `infra_foundation` (capability check), `feat_llm_judgments` (gate), `feat_digest_proposal` (degrade), `feat_chat_agent` (degrade), `chore_tutorial_polish` (documentation).)*

---

## Story → feature mapping

| Story | Feature folder | Source umbrella section |
|---|---|---|
| US-1, US-2, US-3 | `infra_foundation` | §25, §27 |
| US-4, US-5, US-6 | `infra_adapter_elastic` | §8, §19 |
| US-7, US-8 | `infra_optuna_eval` | §13, §14 |
| US-9, US-10, US-11, US-12 | `feat_study_lifecycle` | §12, §22 |
| US-13, US-14, US-15 | `feat_llm_judgments` | §14, §19, §22 |
| US-16, US-17 | `feat_digest_proposal` | §15, §16, §19 |
| US-18, US-19 | `feat_github_pr_worker` | §16 |
| US-20, US-21 | `feat_github_webhook` | §16 |
| US-22, US-23, US-24 | `feat_studies_ui` | §22, §15 |
| US-25, US-26, US-27 | `feat_chat_agent` | §15, §19, §21, §22 |
| US-28, US-29 | `feat_proposals_ui` | §22, §16 |
| US-30, US-31 | `chore_tutorial_polish` | §27 |
| US-32 (cross-cutting) | `infra_foundation` (FR-7), `feat_llm_judgments`, `feat_digest_proposal`, `feat_chat_agent`, `chore_tutorial_polish` | umbrella §15 + new arch §"OpenAI-compatible endpoints" |

**Coverage check:** every umbrella §27 in-scope item maps to at least one US-N. Every US-N maps to exactly one feature folder (with cross-feature dependencies expressed via the dependency table in the plan, not via story duplication).

---

## Out of scope for MVP1 (deferred to later releases)

For visibility — these capabilities appear in the umbrella spec but are explicitly NOT MVP1 user stories:

- **Langfuse / SigNoz observability dashboards** → MVP2 (per §27 line 2308).
- **Multi-LLM provider abstraction** (Anthropic, Bedrock, Ollama, vLLM) → MVP4 (per §27 line 2297).
- **GitLab / Bitbucket** as Git providers → MVP3 (per §27 line 2298).
- **Lucidworks Fusion** as an engine adapter → MVP3 (per umbrella §27 — "Production Stacks").
- **Multi-tenant** (`tenants` table, `tenant_id` scoping) → MVP4 (per §27 lines 2299–2300).
- **LangGraph state graph + subagents + `PostgresSaver`** → GA v1 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../01_architecture/tech-stack.md). MVP1 uses plain `openai` SDK + function calling.
- **Auth / RBAC** (`viewer` / `runner` / `tenant_admin` / `platform_admin` role enforcement; SSO via reverse proxy; bearer API keys) → MVP4 per umbrella §18.
- **Forking studies with narrowed search-space ranges** (top story #4 from §6) → MVP2.
- **Pairwise quick-experiment tool** (`run_pairwise`) → MVP2 nice-to-have, not required for MVP1 loop.
- **Slack notifications on PR open** (top story #3 from §6) → MVP2.
- **30-day proposal dashboard for Viewer** (top story #6 from §6) → MVP2.
- **Validation re-run on prod after staging win** (top story #2 from §6) → MVP2.
