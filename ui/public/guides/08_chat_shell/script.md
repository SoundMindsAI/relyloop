# Chat shell

> 2-minute walkthrough — navigate the conversation surface.

The chat agent isn't just for creating studies — it's a general-purpose
introspection layer that can introspect clusters, run ad-hoc queries, and
trigger workflows via tool calls. This guide covers the conversation
**shell** (list, new, resume, banner). The message-streaming + tool-call
side of the agent ships in a follow-up guide when MVP2 lands LLM mocking
infrastructure.

## Steps

1. **Open the Chat page** via the top nav.
2. **Conversation list** shows every past chat with last-message preview
   + activity timestamp. Click a row to resume.
3. **New conversation** creates a fresh `/chat/{id}` row. The composer
   mounts immediately, ready for your first message.
4. **Secrets warning banner** appears at the top of every conversation
   detail page. **Don't paste API keys or PATs in chat** — every message
   is persisted in Postgres and re-sent to the LLM each turn. Dismissal
   is per-session; the banner reappears on reload so the hygiene rule
   stays visible.

## Reference

- API list conversations: `GET /api/v1/conversations`
- API create: `POST /api/v1/conversations` (title optional; backend auto-generates from first message if absent)
- API send message (SSE stream): `POST /api/v1/conversations/{id}/messages`
- Agent runbook: [`docs/03_runbooks/agent-debugging.md`](../03_runbooks/agent-debugging.md)
  — replay a conversation, force a tool dispatch, inspect SSE events
- Tool inventory: [`docs/01_architecture/agent-tools.md`](../01_architecture/agent-tools.md)
