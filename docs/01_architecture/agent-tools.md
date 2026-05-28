# Agent Tools

**Status:** Adopted for MVP1 with OpenAI function-calling. The tool registry pattern persists into LangGraph (GA v1) without breaking changes.
**Source of truth for product context:** [docs/00_overview/relyloop-spec.md §19](../00_overview/relyloop-spec.md) ("Agent tools") + §21 ("Agent integration").

---

## The architectural rule

**Tools are Pydantic-defined, dispatched via the OpenAI function-calling protocol, and identical between agent-internal and externally-exposed callers.** This is the umbrella spec's "agent-first symmetry" commitment (§21): every action the agent can take is also a documented HTTP endpoint with the same Pydantic request/response contract.

## MVP1 tool inventory

The MVP1 agent ships these **20** tools in `backend/app/agent/tools/` (counted across the 6 categories below: 3 + 2 + 5 + 1 + 4 + 5 = 20). The 20th tool — `propose_search_space` — landed in [`feat_agent_propose_search_space`](../00_overview/implemented_features/) and is read-only: the orchestrator's system prompt directs the LLM to call it before `create_study` so the search-space bounds are grounded in the same heuristic that powers the create-study wizard's auto-fill.

| Category | Tool | Description | Backing endpoint / function |
|---|---|---|---|
| Cluster & schema | `list_clusters()` → `[ClusterSummary]` | List all registered clusters | `GET /api/v1/clusters` |
| | `get_cluster(cluster_id)` → `ClusterDetail` | Cluster detail with health | `GET /api/v1/clusters/{id}` |
| | `get_schema(cluster_id, target)` → `Schema` | Index schema introspection | `GET /api/v1/clusters/{id}/schema?target={target}` |
| Templates | `list_templates(engine_type?)` → `[TemplateSummary]` | List templates, optionally filtered by engine | `GET /api/v1/query-templates?engine_type={...}` |
| | `get_template(template_id)` → `TemplateDetail` | Full template body + declared_params | `GET /api/v1/query-templates/{id}` |
| Query sets & judgments | `list_query_sets()` → `[QuerySetSummary]` | List query sets | `GET /api/v1/query-sets` |
| | `create_query_set(name, queries[])` → `QuerySet` | Create a query set with initial queries | `POST /api/v1/query-sets` + bulk-add |
| | `import_queries_from_csv(query_set_id, csv_data)` → `int` | Bulk-add queries from CSV | `POST /api/v1/query-sets/{id}/queries` (CSV body) |
| | `generate_judgments_llm(query_set_id, cluster_id, target, current_template_id, rubric)` → `JudgmentList` | Kick off LLM judgment generation | `POST /api/v1/judgments/generate` |
| | `get_calibration(judgment_list_id)` → `CalibrationStats` | Read calibration stats from a judgment list | `GET /api/v1/judgment-lists/{id}` (calibration field) |
| Quick experiments | `run_query(cluster_id, target, query_dsl)` → `[Hit]` | Execute one query, return top-K | `POST /api/v1/clusters/{id}/run_query` |
| Studies | `propose_search_space(template_id, cluster_id, judgment_list_id?, prior_study_id?)` → `{search_space, grounding}` | Build a deterministic starter search space (heuristic + optional ±50% narrowing around a prior winner). Read-only — no REST equivalent; consumed only by the chat agent. | _(agent-only tool — no public REST surface; mirrors `ui/src/lib/search-space-defaults.ts` via the shared parity test)_ |
| | `create_study(...)` → `Study` | Create + start a study | `POST /api/v1/studies` |
| | `get_study(study_id)` → `StudyDetail` | Study detail with `trials_summary` | `GET /api/v1/studies/{id}` |
| | `cancel_study(study_id)` → `Study` | Cancel a queued/running study | `POST /api/v1/studies/{id}/cancel` |
| Proposals & PRs | `list_proposals(filter?)` → `[ProposalSummary]` | List proposals | `GET /api/v1/proposals?status={...}` |
| | `get_proposal(proposal_id)` → `ProposalDetail` | Proposal detail | `GET /api/v1/proposals/{id}` |
| | `create_proposal_from_study(study_id)` → `Proposal` | Create proposal manually from a study (alternative to digest auto-creation) | `POST /api/v1/proposals` (with `study_id` set) |
| | `create_proposal_manual(cluster_id, template_id, config_diff)` → `Proposal` | Create a hand-crafted proposal | `POST /api/v1/proposals` |
| | `open_pr(proposal_id)` → `Proposal` | Trigger PR creation; transitions `pending → pr_opened` | `POST /api/v1/proposals/{id}/open_pr` |

## Tool definition pattern

```python
# backend/app/agent/tools/studies.py
from pydantic import BaseModel
from openai.types.chat import ChatCompletionToolParam

class CancelStudyArgs(BaseModel):
    study_id: UUID
    reason: str | None = None

async def cancel_study_impl(args: CancelStudyArgs) -> Study:
    """Cancel a queued or running study. The study transitions to `cancelled` within 30s."""
    return await study_state.cancel_study(args.study_id, reason=args.reason)

CANCEL_STUDY_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "cancel_study",
        "description": cancel_study_impl.__doc__,
        "parameters": CancelStudyArgs.model_json_schema(),
    },
}
```

The tool registry at `backend/app/agent/tools/__init__.py` collects every tool's `*_TOOL` constant into a `TOOLS` list and every `*_impl` function into a `TOOL_REGISTRY: dict[str, Callable]` dispatcher.

## Tool dispatch loop (MVP1)

```python
# backend/app/agent/orchestrator.py (sketch)
from openai import AsyncOpenAI
from .tools import TOOLS, TOOL_REGISTRY

async def run_agent_turn(messages: list[dict], conversation_id: UUID) -> AsyncIterator[StreamEvent]:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    while True:
        stream = await client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            stream=True,
        )
        # Stream tokens to the client; collect tool calls if any
        tool_calls, content = await consume_stream(stream)
        if not tool_calls:
            return  # Final assistant message; conversation turn done
        # Persist the assistant turn to messages table
        # Dispatch each tool_call to TOOL_REGISTRY[tool_call.name](validated_args)
        # Append tool results as `role: tool` messages
        # Loop continues; OpenAI gets the tool results in the next call
```

The loop persists every assistant + tool message to the `messages` table per [`data-model.md`](data-model.md) so the conversation is reconstructable.

## Streaming + SSE

The agent endpoint streams tokens to the UI via SSE. Each event is a JSON-line:

```
event: token
data: {"text": "I'll cancel that study now."}

event: tool_call
data: {"name": "cancel_study", "arguments": {"study_id": "stu_..."}}

event: tool_result
data: {"name": "cancel_study", "result": {"id": "stu_...", "status": "cancelled"}}

event: done
data: {"conversation_id": "conv_..."}
```

The UI's chat surface (`feat_chat_agent`) consumes this stream via `fetch() + ReadableStream` (the user message lives in the POST body, so native `EventSource` — which is GET-only — isn't usable). See [`ui-architecture.md` §"Streaming chat"](ui-architecture.md) for the consumer pattern.

## Per-call validation

The dispatcher **MUST** validate `tool_call.arguments` against the tool's Pydantic args schema BEFORE calling the impl. Validation failures result in a `tool_result` event with an error payload that's appended to the conversation; the LLM gets a chance to retry with corrected arguments.

## Reserved for later releases

| Capability | Activates at |
|---|---|
| `propose_search_space(template_id, cluster_id, target, query_set_id, observations?)` → `SearchSpaceProposal` | MVP2 (LLM-driven hypothesis generation) |
| `validate_search_space(template_id, search_space)` → `ValidationResult` | MVP2 (paired with propose_search_space) |
| `fork_study(study_id, narrowed_search_space?, name?)` → `Study` | MVP2 (study forking with narrowed ranges) |
| `run_pairwise(cluster_id, target, query_a, query_b, query_text)` → `PairwiseResult` | MVP2 (interactive comparison) |
| `run_rank_eval(cluster_id, target, template_rendered, query_set_id, judgment_list_id, metric)` → `EvalResult` | MVP2 (one-off eval without a study) |
| `generate_judgments_from_ubi(query_set_id, cluster_id, target, since, until?, converter, llm_fill_threshold?)` → `JudgmentList` | MVP2 (with UBI judgments + Solr adapter) |
| LangGraph state-graph orchestrator (replaces plain `openai` + function calling) | GA v1 |
| Hypothesis-gen + evaluation subagents (per umbrella §15 architecture diagram) | GA v1 |
| Human-in-the-loop interrupts before `open_pr`, prod-cluster studies, judgment regen | GA v1 |
| Per-tenant tool gating (e.g., `runner` role can call `create_study`; `viewer` cannot) | MVP4 (with auth + roles) |

## Cross-references

- LLM SDK + prompt + cost handling: [`llm-orchestration.md`](llm-orchestration.md)
- API conventions + SSE conventions: [`api-conventions.md`](api-conventions.md)
- `conversations` and `messages` schemas: [`data-model.md`](data-model.md)
- Owning feature: [`feat_chat_agent/feature_spec.md`](../00_overview/planned_features/feat_chat_agent/feature_spec.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
