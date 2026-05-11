# Runbooks

Operational procedures: deployment, upgrades, restores, incident handling, recurring maintainer tasks.

## MVP1

- [`local-dev.md`](local-dev.md) — boot, restart, debug, reset the local
  Compose stack (`infra_foundation` Story 5.2)
- [`cluster-registration.md`](cluster-registration.md) — registering an
  Elasticsearch / OpenSearch cluster (`infra_adapter_elastic`)
- [`optuna-debugging.md`](optuna-debugging.md) — investigating Optuna
  trial failures (`infra_optuna_eval`)
- [`study-lifecycle-debugging.md`](study-lifecycle-debugging.md) — study
  state-machine + orchestrator playbook (`feat_study_lifecycle` Phase 2)
- [`judgment-generation-debugging.md`](judgment-generation-debugging.md) —
  LLM-as-judge worker playbook + calibration / overrides (`feat_llm_judgments`)

## Coming with later features

- `pr-worker-pat-rotation.md` — rotating the GitHub PAT (lands with `feat_github_pr_worker`)
- `webhook-replay.md` — replaying a missed GitHub webhook (lands with `feat_github_webhook`)
- `db-revision-mismatch.md` — recovering when API startup detects pending migrations (lands at MVP2 when the startup guard activates)
- `staging-deploy.md` — staging deploy procedure (lands at MVP3)
- `incident-response.md` — on-call playbook (lands at GA v1)
