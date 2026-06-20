# Bug fix — chore_agent_confirmation_per_tool_binding

**Source idea:** [idea.md](./idea.md)
**Branch:** `chore/agent-confirmation-per-tool-binding`
**Type:** bug fix — medium (latent / prophylactic; security-review finding, Low/Medium severity)
**Date:** 2026-06-19

## Problem

The chat agent's confirmation gate for the 8 mutating tools uses a **substring match** on the last assistant message and treats one user "yes" as authorizing **every** mutating tool the assistant proposed in that turn. Two consequences:

1. **Substring collision** — `tool_name in assistant_lower` is bare substring containment, so an assistant turn mentioning `create_studying` (or `open_pr_workflow`) falsely satisfies the proposed-this-tool check for `create_study` / `open_pr`.
2. **Blanket multi-tool authorization** — if the assistant says "I can create a study and then open a PR for you" and the user replies "yes", the orchestrator loop iterates every collected tool call and calls `_is_authorized_mutation` per-tool with the same `(last_assistant_text, last_user_text)`. Both tools pass the substring check; the single "yes" authorizes both.

The prompt-injection-via-tool-result vector is already defended ([feature_spec.md §10 Threat 4](../../../implemented_features/2026_05_12_feat_chat_agent/feature_spec.md#L229)), so this is latent / Low-Medium, not High. The fix is the MVP2 follow-up that [confirmation.py:87](../../../../backend/app/agent/confirmation.py#L87) anticipates in its docstring ("a strict state-machine confirmation can land at MVP2 if the heuristic misfires").

## Reproduction

Two unit tests in [`backend/tests/unit/agent/test_confirmation_guard.py`](../../../../backend/tests/unit/agent/test_confirmation_guard.py) demonstrate the bugs by failing on `main` (substring match) and passing on this branch (whole-word + per-tool binding):

```bash
.venv/bin/pytest backend/tests/unit/agent/test_confirmation_guard.py \
  -k "multi_tool_turn_rejects_all or substring_collision" -v
```

- `test_unit_multi_tool_turn_rejects_all` — asserts that when one assistant turn names **two** mutating tools and the user replies "yes", `_is_authorized_mutation` returns `False` for **both** tools (today: returns `True` for both → blanket authorization).
- `test_unit_substring_collision_does_not_authorize` — asserts that an assistant turn containing `"create_studying"` does NOT satisfy the proposed-`create_study` check (today: substring contains "create_study" → false positive).

## Root cause

- **Owning layer:** API / agent orchestrator.
- **Origin:** [`backend/app/agent/orchestrator.py:127-133`](../../../../backend/app/agent/orchestrator.py#L127-L133) — `_is_authorized_mutation` does `tool_name not in assistant_lower and tool_name_spaced not in assistant_lower`, a bare substring test on **one** tool name at a time. There is no count of how many *other* mutating tool names appear in the same assistant text.
- **Propagation:** the dispatch loop at [`orchestrator.py:354`](../../../../backend/app/agent/orchestrator.py#L354) iterates every collected `tool_call` from one LLM turn and calls `_is_authorized_mutation` independently per-tool, with the same `(last_assistant_text, last_user_text)`. Each call is correct in isolation but the gate has no shared state, so a single affirmative blanket-authorizes every named tool.

## Fix design (locked decisions)

1. **Whole-word matching via `\b` anchors.** Replace `tool_name in assistant_lower` with `re.search(rf"\b{re.escape(name)}\b", lowered)` on both the underscored and spaced forms. `\b` correctly recognizes underscore as a word character, so `\bcreate_study\b` matches `create_study` but not `create_studying`. **Cites:** the existing [`is_affirmative`](../../../../backend/app/agent/confirmation.py#L84-L103) helper already uses `[a-z]+` tokenization for the same reason; this aligns the two guards. Idea preflight 2026-06-19 (Locked decision § "binding model").
2. **Exactly-one-mutating-tool-name rule (Option A).** Before calling `is_affirmative`, count how many `MUTATING_TOOL_NAMES` appear as whole words in `last_assistant_text`. If the count is ≠ 1, return `False` for all of them — the gate refuses ambiguous multi-tool turns. **Cites:** preflight 2026-06-19 (Locked decision § "Why A over the active-tracking alternative (B)"); the `confirmation.py:87` docstring's MVP2-state-machine budget caps the design at a stateless string check, ruling out active-tool tracking across turns.
3. **Reuse existing `confirmation_required` error code.** The ambiguous-multi-tool case emits the same `ToolResultEvent(error="confirmation_required")` as the existing cases; the `detail` string carries the human-readable distinction. **Cites:** preflight 2026-06-19 (Open questions § "Error code"); avoids adding new enum surface for a near-zero-frequency operator-telemetry concern that can be filed as a follow-on idea if it ever bites.
4. **Spaced form stays verbatim.** No change to how `tool_name.replace("_", " ")` is matched — natural-prose phrasings of multi-token tool names remain supported. **Cites:** preflight 2026-06-19 (Open questions § "Spaced-form match"); existing `test_unit_spaced_tool_name_pass` covers the happy path.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| Unit | `backend/tests/unit/agent/test_confirmation_guard.py::test_unit_multi_tool_turn_rejects_all` | One affirmative + two mutating tools in the assistant turn → both rejected |
| Unit | `backend/tests/unit/agent/test_confirmation_guard.py::test_unit_substring_collision_does_not_authorize` | `"create_studying"` does not match `tool_name="create_study"` |
| Unit | (existing) `test_unit_user_yes_to_unrelated_question_fails` | No tool mentioned → reject (kept green) |
| Unit | (existing) `test_unit_user_not_affirmative_fails` | Tool mentioned but reply not affirmative → reject (kept green) |
| Unit | (existing) `test_unit_both_conditions_pass` | Tool mentioned + affirmative → allow (kept green) |
| Unit | (existing) `test_unit_spaced_tool_name_pass` | Spaced form (`create study`) accepted (kept green) |
| Unit | (existing parametrize) `test_integration_confirmation_required_blocks_dispatch[*]` | All 8 mutating tools blocked without confirmation (kept green) |

## Rollout

None — code-only change to a stateless helper. No migration, no API contract change, no flag, no operator action. The orchestrator's `ToolResultEvent(error="confirmation_required", detail=…)` shape is unchanged; the model receives the same kind of feedback and re-proposes per-tool on its next turn.

## Tangential observations

- [`chore_studies_chain_recent_contract_db_skip_gate`](../chore_studies_chain_recent_contract_db_skip_gate/idea.md) — three contract tests in `test_studies_chain_recent_contract.py` lack the `_skip_if_no_pg` gate that the webhook contract suite uses; they fail loudly in any local shell without `DATABASE_URL_FILE`/`POSTGRES_PASSWORD_FILE` mounted. Captured rather than bundled because it's a different subsystem (test infra vs. agent) and the broader audit could extend to other `LifespanManager`-based contract tests.

The security-review sweep that originally surfaced this finding also surfaced the four sibling ideas linked in [`idea.md`'s "Relationship to other work"](./idea.md); those are tracked separately and out of scope here.
