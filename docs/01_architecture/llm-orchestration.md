# LLM Orchestration

**Status:** Adopted for MVP1 with the plain `openai` SDK + function calling. **The SDK is pointed at any OpenAI-compatible endpoint via `OPENAI_BASE_URL`** (defaults to `https://api.openai.com/v1`; works against Ollama, LM Studio, vLLM, HuggingFace TGI for air-gapped evaluation). LangGraph orchestrator + native non-OpenAI-compatible provider SDKs (Anthropic, Bedrock, Vertex) + Langfuse + RedisCache arrive at later releases per the canonical [`tech-stack.md` §"Canonical release matrix"](tech-stack.md).
**Source of truth for product context:** [docs/00_overview/relyloop-spec.md §15](../00_overview/relyloop-spec.md) ("LLM orchestration & observability").

---

## MVP1 LLM stack

| Concern | MVP1 choice |
|---|---|
| LLM SDK | `openai` Python SDK pointed at any OpenAI-compatible endpoint via `OPENAI_BASE_URL` config (defaults to `https://api.openai.com/v1`). Same client code; the URL is the only thing that changes between hosted OpenAI and a local Ollama/LM Studio/vLLM/TGI deployment. |
| Function calling | OpenAI's native function-calling protocol; tools defined as Pydantic models. Local-LLM compatibility varies — see §"OpenAI-compatible endpoints" below. |
| Default model (api.openai.com) | `gpt-4o-2024-08-06` (judgment generation, digest narrative); `gpt-4o-mini-2024-07-18` (chat orchestrator — cost-sensitive) |
| Default model (local Ollama) | `llama3.1:70b-instruct` (recommended); `qwen2.5:32b-instruct` (smaller alternative). Model name is configurable via `OPENAI_MODEL` env override. |
| Conversation state | Postgres `conversations` + `messages` tables (per [`data-model.md`](data-model.md)) — simple message log, no `PostgresSaver`-style checkpointing |
| Caching | None in MVP1 (LangChain `RedisCache` arrives at MVP4 with multi-provider) |
| Prompts | Live in `prompts/` directory in the repo, versioned with code; loaded at startup, rendered with Jinja per call |
| Model version pinning | All persisted artifacts that depend on LLM behavior capture the exact model identifier as a string (`openai:gpt-4o-2024-08-06`). Floating tags (`gpt-4o`) forbidden in production code; CI rejects PRs that use them. |
| Observability | None in MVP1 (Langfuse arrives at MVP2). Structured logs via structlog capture every LLM call's prompt + response + token counts + latency at INFO. |

## OpenAI-compatible endpoints

MVP1 supports any HTTP endpoint that implements the OpenAI Chat Completions API. The configuration is intentionally minimal:

| Env var | Purpose | Defaults |
|---|---|---|
| `OPENAI_BASE_URL` | Endpoint root (everything before `/chat/completions`) | `https://api.openai.com/v1` |
| `OPENAI_API_KEY_FILE` | Mounted secret containing the API key | required for `api.openai.com`; can be a placeholder for local servers that don't validate the key |
| `OPENAI_MODEL` | Model name passed to the API | `gpt-4o-2024-08-06` (defaults vary by base URL — see model matrix) |
| `OPENAI_MODEL_CHAT` | Override for chat orchestrator (cost-sensitive) | `gpt-4o-mini-2024-07-18` (only honored when base_url = api.openai.com; local installs reuse `OPENAI_MODEL`) |

**Tested local-LLM tooling (MVP1):**

| Tool | Endpoint | Auth | Notes |
|---|---|---|---|
| Ollama | `http://localhost:11434/v1` | placeholder key (any string) | Native OpenAI-compatible mode since v0.1.30. Function-calling support varies by model. |
| LM Studio | `http://localhost:1234/v1` | placeholder key | OpenAI-compatible by default. Function-calling depends on the loaded model's chat template. |
| vLLM | `http://localhost:8000/v1` (your port) | API key if `--api-key` set, else placeholder | Run with `--enable-auto-tool-choice --tool-call-parser <parser>` for function-calling. |
| HuggingFace TGI | `http://localhost:8080/v1` (your port) | placeholder key | Run with `--enable-openai-api`. Function-calling support added in TGI 2.x. |

### Capability matrix (model-level)

Function-calling + structured-output quality varies wildly across local models. RelyLoop's three LLM-driven tasks have different sensitivities:

| Task | Required capability | High-quality models |
|---|---|---|
| **Judgment generation** (`feat_llm_judgments`) | Structured output (JSON object with `[{doc_id, rating, rationale}]`) | OpenAI `gpt-4o*`; Anthropic Claude (via MVP4 native SDK); Llama 3.1 70B+; Qwen 2.5 32B+; Mistral Large |
| **Digest narrative** (`feat_digest_proposal`) | Structured output (narrative + recommended_config + suggested_followups) | Same — needs reliable structured output |
| **Chat orchestrator** (`feat_chat_agent`) | Tool/function calling (multi-turn; can be lenient on quality) | All of the above; smaller models like Llama 3.1 8B work for read-only tools but fail on `create_study` (mis-formatted args) |

**Models that DON'T work well for MVP1:**
- Llama 3.1 8B and smaller — arguments often malformed; tool-call loops get stuck
- Mistral 7B and smaller — same
- Models without explicit tool-calling chat templates — fall back to prompt-engineered approximations that fail validation

### Capability check at startup

The API container performs a self-test on startup against `OPENAI_BASE_URL`:

1. **Models endpoint:** `GET {base_url}/models` — verify reachable.
2. **Chat completion:** `POST {base_url}/chat/completions` with a 1-token prompt — verify chat works.
3. **Function calling:** `POST {base_url}/chat/completions` with a single trivial tool definition (`echo(text)`) and `tool_choice="required"` — verify the response includes a parseable `tool_calls` field.
4. **Structured output:** `POST {base_url}/chat/completions` with `response_format={type: "json_schema", ...}` for a trivial Pydantic shape — verify the response parses into the schema.

Results are stored in Redis under `openai:capabilities:{base_url_hash}` (24h TTL). The success-path payload:

```json
{
  "base_url": "http://ollama:11434/v1",
  "model": "llama3.1:70b-instruct",
  "models_endpoint": "ok",
  "models_endpoint_status_code": null,
  "chat_completion": "ok",
  "function_calling": "ok",
  "structured_output": "ok",
  "tested_at": "2026-05-09T12:00:00Z"
}
```

The step-1-failure payload (e.g., bad API key returns HTTP 401 from `GET /models`):

```json
{
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-2024-08-06",
  "models_endpoint": "fail",
  "models_endpoint_status_code": 401,
  "chat_completion": "untested",
  "function_calling": "untested",
  "structured_output": "untested",
  "tested_at": "2026-05-24T10:00:00Z"
}
```

**Cascade on step-1 failure.** When `models_endpoint == "fail"`, steps 2–4 are skipped and reported as `"untested"` (probing chat / function-calling / structured-output is meaningless against an unreachable endpoint). `/healthz` surfaces this combination as `subsystems.openai: "incapable"` + `openai_capabilities.models_endpoint: "fail"` + 3× `"untested"`. The `models_endpoint_status_code` field tells the operator *why* step 1 failed: `401 → bad key`, `403 → quota/billing`, `429 → rate-limited`, `5xx → upstream outage`, `null → network unreachable (DNS / timeout / connection-refused)`. The OpenAI response body is intentionally never captured — bodies can quote the bearer token back, so only the integer status code is stored (CLAUDE.md Absolute Rule #10). Detailed failure context (URL, error text) stays in the api container's WARN log per [`backend/app/llm/capability_check.py:67-80`](../../backend/app/llm/capability_check.py).

The corresponding `/healthz` `openai_capabilities` block carries five required fields — `models_endpoint_status_code` is required-but-nullable (the JSON key is always present with explicit `null` when not applicable). Success-path projection:

```json
"openai_capabilities": {
  "models_endpoint": "ok",
  "models_endpoint_status_code": null,
  "chat": "ok",
  "function_calling": "ok",
  "structured_output": "ok"
}
```

Failure-path projection (e.g., bad key — surfaces `subsystems.openai: "incapable"` upstream):

```json
"openai_capabilities": {
  "models_endpoint": "fail",
  "models_endpoint_status_code": 401,
  "chat": "untested",
  "function_calling": "untested",
  "structured_output": "untested"
}
```

**Repo-secret vs operator `.env` divergence.** The `OPENAI_API_KEY_TEST` value populated in GitHub Actions' repo secret may not match any individual operator's `./secrets/openai_key` file. If CI's smoke gate reports `models_endpoint: "fail"` + `models_endpoint_status_code: 401`, the next step is to rotate the repo secret with a known-good key. Per CLAUDE.md operator-environment handoff, repo secrets are operator-only — Claude cannot modify them. The smoke job's diagnostic surface for this case is the `smoke-logs.txt` artifact built at [`.github/workflows/pr.yml:444-445`](../../.github/workflows/pr.yml) (the `Wait for /healthz` step's failure-step curl at `pr.yml:364` does NOT fire on openai-incapable because the wait loop succeeds — overall `status: ok`).

The application reads capabilities at request time and:
- **Chat orchestrator** runs with whatever's available; degrades gracefully when tool-calling fails (refuses to dispatch tools, asks user to use UI instead)
- **Judgment generation** refuses to start (returns `LLM_PROVIDER_INCAPABLE`) if `structured_output != "ok"` — the task can't work without it
- **Digest narrative** falls back to a simpler prompt (no structured output, narrative-only) if `structured_output != "ok"`; the digest is degraded but usable

This pattern lets operators evaluate local-LLM tools incrementally — a degraded local install can still demo the trial loop + UI even if some LLM features aren't available.

## Function-calling pattern (MVP1)

OpenAI tools are defined once via Pydantic models; the same definitions power the agent's tool registry, the OpenAPI schema (FastAPI), and the type-checked Python signatures for direct callers.

```python
from openai import AsyncOpenAI
from pydantic import BaseModel

class CreateStudyRequest(BaseModel):
    name: str
    cluster_id: UUID
    target: str
    template_id: UUID
    query_set_id: UUID
    judgment_list_id: UUID
    search_space: SearchSpace
    objective: Objective
    config: StudyConfig

# OpenAI function-calling JSON schema is auto-derived from the Pydantic model.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_study",
            "description": "Create and start a new optimization study against a cluster, query set, and judgment list.",
            "parameters": CreateStudyRequest.model_json_schema(),
        },
    },
    # ... other tools
]

client = AsyncOpenAI(api_key=settings.openai_api_key)

response = await client.chat.completions.create(
    model="gpt-4o-mini-2024-07-18",
    messages=conversation_messages,
    tools=TOOLS,
    tool_choice="auto",
)
```

The tool-dispatch loop lives in `backend/agent/orchestrator.py`: receive a user message, call OpenAI with tools, dispatch any returned tool calls to local functions, loop until the model returns a non-tool response.

### Propose-then-create chain (feat_agent_propose_search_space)

The agent's `create_study` tool requires a fully-formed `SearchSpace` at call time. Rather than letting the LLM invent bounds from training-data intuition, the orchestrator's system prompt directs the LLM to call `propose_search_space(template_id, cluster_id, prior_study_id?)` first — a read-only tool that returns a deterministic, code-generated search space drawn from the same TS+Python parity-locked heuristic that powers the create-study wizard's auto-fill ([`ui/src/lib/search-space-defaults.ts`](../../ui/src/lib/search-space-defaults.ts) + [`backend/app/domain/study/search_space_defaults.py`](../../backend/app/domain/study/search_space_defaults.py)). The LLM passes `result.search_space` verbatim into `create_study`'s `search_space` argument and cites the `grounding` fields (template name, narrowed param names, cap-aware fallback names) in its chat reply.

Adherence is observed offline via paired structlog INFO events tagged with `ToolContext.conversation_id`:

- `agent.search_space_proposed` — emitted from `propose_search_space_impl` on every successful invocation. Fields: `conversation_id`, `template_id`, `cluster_id`, `judgment_list_id`, `prior_study_id`, `param_names`, `cardinality`, `narrowed_param_names`.
- `agent.create_study.invoked` — emitted from `create_study_impl` after search-space validation, before FK resolution. Fields: `conversation_id`, `study_id_pending` (pre-INSERT UUIDv7), `template_id`, `cluster_id`, `search_space_param_names`, `search_space_cardinality`.

Correlating the two streams by `conversation_id` measures the chain adherence ratio without per-call state tracking. See [`docs/03_runbooks/agent-debugging.md`](../03_runbooks/agent-debugging.md) for the operator-facing grep recipe.

## Per-task LLM calls (MVP1)

| Task | Owning feature | Pattern | Model | Notes |
|---|---|---|---|---|
| Chat orchestration | `feat_chat_agent` | Streaming chat completion + function calling | `gpt-4o-mini-2024-07-18` | Conversation state in `messages` table; SSE to UI |
| Judgment generation | `feat_llm_judgments` | Structured-output completion (one call per (query, top-K-docs) batch) | `gpt-4o-2024-08-06` | Per-doc rating with rationale; rubric prompt loaded from `prompts/judgment_generation.user.jinja` |
| Digest narrative | `feat_digest_proposal` | Single completion at study end | `gpt-4o-2024-08-06` | Prompt loaded from `prompts/digest_narrative.user.jinja`; output is markdown narrative + structured JSON for parameter importance |

## Prompt directory layout

```
prompts/
  judgment_generation.system.md
  judgment_generation.user.jinja
  judgment_generation.rubric_v1.md         # rubric versioned in name
  digest_narrative.system.md
  digest_narrative.user.jinja
  orchestrator.system.md
  # MVP2+: search_space_proposal, hypothesis_subagent, evaluation_subagent
```

**Versioning:** prompts are part of the repo. The `prompt_version` (short git SHA of `prompts/` at call time) is a column on `judgments` / `digests` / `proposals` for lineage — but **only populated from MVP2 forward** when the lineage columns activate per [`data-model.md`](data-model.md). MVP1 captures `model_version` only (in `judgments.rater_ref`, `digests.generated_by`).

## Cost & error handling

- **Token limits.** Each call respects per-task `max_tokens` (4096 default for completions; 1024 for tool calls). Exceeding the limit truncates output cleanly; the worker logs at WARN.
- **Rate limits.** OpenAI raises `RateLimitError`; the worker retries with exponential backoff (3 attempts, max 30s total) before failing the task.
- **Model unavailable.** OpenAI returns 503; same retry policy.
- **Cost guardrail.** `OPENAI_DAILY_BUDGET_USD` (default `$10`) is checked at every call against a Postgres rolling-24h sum of `tokens_used * unit_cost`. Exceeding the budget returns `OPENAI_BUDGET_EXCEEDED` to the caller. Disabled by setting `OPENAI_DAILY_BUDGET_USD=0`.

## What's NOT in MVP1

- **LangGraph orchestrator** + state graph + `PostgresSaver` for resumable conversations — GA v1.
- **Multi-provider `BaseChatModel` abstraction** (Anthropic, Bedrock, Azure OpenAI, Vertex, Ollama, vLLM) — MVP4.
- **LangChain `RedisCache`** — MVP4 (with multi-provider).
- **Langfuse self-hosted observability** — MVP2 ("Observable" theme). Captures rendered prompts, responses, token counts, costs, latency, full chain hierarchies.
- **Eval datasets in Langfuse** (`judgment_generation_eval`, `digest_quality_eval`, etc.) — MVP2.
- **Human-in-the-loop interrupts** at PR open / prod-cluster studies / judgment regeneration — GA v1 (with LangGraph interrupts).
- **`propose_search_space` LLM tool** — uncertain MVP1 scope (deferred decision in `feat_chat_agent` open questions). If MVP1, simple structured-output completion; if deferred, MVP2.

## Reserved for later releases

| Capability | Activates at |
|---|---|
| Langfuse self-hosted (LLM observability) | MVP2 |
| Lineage columns (`langfuse_trace_id`, `prompt_version`, `input_hash`) on `judgments` / `digests` / `proposals` | MVP2 |
| Eval datasets + nightly eval runs | MVP2 |
| Native non-OpenAI-compatible provider SDKs (Anthropic, AWS Bedrock, Google Vertex AI) via LangChain `BaseChatModel` | MVP4 |
| LangChain `RedisCache` | MVP4 |
| Per-tenant LLM provider selection + cost rollups | MVP4 |
| LangGraph orchestrator + state graph + subagents | GA v1 |
| `PostgresSaver` for resumable conversations | GA v1 |
| Human-in-the-loop interrupts at PR-open / prod-cluster / judgment-regen | GA v1 |

**Already in MVP1 (don't defer):** OpenAI-compatible endpoints — Ollama, LM Studio, vLLM, HuggingFace TGI all work via `OPENAI_BASE_URL` from day 1. The MVP4 LangChain abstraction adds NATIVE SDKs for providers that don't expose an OpenAI-compatible API (Anthropic Claude direct, AWS Bedrock, Google Vertex). It does NOT add new local-LLM support — that's already here.

## Cross-references

- Stack choices (`openai` SDK pinned in `pyproject.toml`): [`tech-stack.md`](tech-stack.md)
- `conversations` and `messages` schemas: [`data-model.md`](data-model.md)
- API conventions for chat SSE endpoints: [`api-conventions.md`](api-conventions.md)
- Owning feature specs:
  - Judgments: [`feat_llm_judgments/feature_spec.md`](../00_overview/planned_features/feat_llm_judgments/feature_spec.md)
  - Digest: [`feat_digest_proposal/feature_spec.md`](../00_overview/planned_features/feat_digest_proposal/feature_spec.md)
  - Chat agent: [`feat_chat_agent/feature_spec.md`](../00_overview/planned_features/feat_chat_agent/feature_spec.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
