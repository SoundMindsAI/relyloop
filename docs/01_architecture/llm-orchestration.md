# LLM Orchestration

**Status:** Adopted for MVP1 with the plain `openai` SDK + function calling. LangGraph orchestrator + multi-provider abstraction + Langfuse + RedisCache arrive at later releases per the canonical [`tech-stack.md` §"Canonical release matrix"](tech-stack.md).
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §15](../00_overview/product/relevance-copilot-spec.md) ("LLM orchestration & observability").

---

## MVP1 LLM stack

| Concern | MVP1 choice |
|---|---|
| LLM SDK | `openai` Python SDK (direct, no provider abstraction) |
| Function calling | OpenAI's native function-calling protocol; tools defined as Pydantic models |
| Default model | `gpt-4o-2024-08-06` (judgment generation, digest narrative); `gpt-4o-mini-2024-07-18` (chat orchestrator — cost-sensitive) |
| Conversation state | Postgres `conversations` + `messages` tables (per [`data-model.md`](data-model.md)) — simple message log, no `PostgresSaver`-style checkpointing |
| Caching | None in MVP1 (LangChain `RedisCache` arrives at MVP4 with multi-provider) |
| Prompts | Live in `prompts/` directory in the repo, versioned with code; loaded at startup, rendered with Jinja per call |
| Model version pinning | All persisted artifacts that depend on LLM behavior capture the exact model identifier as a string (`openai:gpt-4o-2024-08-06`). Floating tags (`gpt-4o`) forbidden in production code; CI rejects PRs that use them. |
| Observability | None in MVP1 (Langfuse arrives at MVP2). Structured logs via structlog capture every LLM call's prompt + response + token counts + latency at INFO. |

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
| Multi-provider `ChatModel` abstraction | MVP4 |
| LangChain `RedisCache` | MVP4 |
| Per-tenant LLM provider selection + cost rollups | MVP4 |
| LangGraph orchestrator + state graph + subagents | GA v1 |
| `PostgresSaver` for resumable conversations | GA v1 |
| Human-in-the-loop interrupts at PR-open / prod-cluster / judgment-regen | GA v1 |

## Cross-references

- Stack choices (`openai` SDK pinned in `pyproject.toml`): [`tech-stack.md`](tech-stack.md)
- `conversations` and `messages` schemas: [`data-model.md`](data-model.md)
- API conventions for chat SSE endpoints: [`api-conventions.md`](api-conventions.md)
- Owning feature specs:
  - Judgments: [`feat_llm_judgments/feature_spec.md`](../02_product/planned_features/feat_llm_judgments/feature_spec.md)
  - Digest: [`feat_digest_proposal/feature_spec.md`](../02_product/planned_features/feat_digest_proposal/feature_spec.md)
  - Chat agent: [`feat_chat_agent/feature_spec.md`](../02_product/planned_features/feat_chat_agent/feature_spec.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
