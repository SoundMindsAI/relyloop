# Vendor Docs

Engine-, provider-, or vendor-specific references, adapter notes, version quirks, and integration guidance. Distilled snapshots of upstream vendor docs (with the upstream URLs noted), pinned to whatever the project uses today, plus the workflow we'd run when interacting with that vendor.

## Index

| Doc | What it covers | Used by |
|---|---|---|
| [`github-branch-protection.md`](github-branch-protection.md) | Two procedures (modern Rulesets + classic Branch Protection) for requiring CI status checks before merge to `main`; the three exact check names for the `relyloop` repo; verification + gotchas | `infra_foundation` plan §7.5 manual handoff #3; every operator who needs to update branch rules |

## Coming with later features

- `elasticsearch-9x.md` / `opensearch-2x.md` — version quirks the ElasticAdapter must work around (lands with `infra_adapter_elastic`)
- `lucidworks-fusion.md` — Fusion 5.x adapter notes (lands at MVP3 with the Fusion adapter)
- `openai-compatible-endpoints.md` — Ollama / LM Studio / vLLM / TGI behavioral differences from canonical OpenAI (lands with `chore_tutorial_polish` operator-runbook polish)
- `gitlab.md` / `bitbucket.md` — Git provider quirks (lands at MVP3 with multi-provider support)
- `anthropic.md` / `bedrock.md` / `vertex.md` — non-OpenAI provider notes (lands at MVP4 with the BaseChatModel abstraction)
