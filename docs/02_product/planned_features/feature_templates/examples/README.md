# Examples — Reference Only

These six example spec/plan pairs were ported from the `creator-discovery-outreach` (CDO) project on 2026-05-08. They are kept as **structural references** for RelyLoop authors:

- The section depth and ordering
- How Given/When/Then acceptance criteria are written
- How RBAC matrices, error code catalogs, and audit-event matrices are populated
- How a multi-phase feature is split between Phase 1 (ship now) and Phase 2 (deferred idea.md)
- How test-strategy sections are broken across unit/integration/contract/e2e

**Do not** treat their domain content as RelyLoop precedent. The features they describe (tenant Stripe billing dunning, workspace health alerts, tenant-customizable LLM prompt with admin oversight) come from a different product and reference subsystems (audit-events, multi-tenant role gating, admin impersonation) that RelyLoop does not yet have.

## When to read which

| Example | Domain shape | Worth reading for |
|---|---|---|
| `example_feature-spec_workspace_health_alerts.md` + `example_implementation-plan_workspace_health_alerts.md` | Auth/admin/tenant-ops heavy: role gating, stateful remediation, audit trails | RBAC matrices, role gating in Given/When/Then, audit-event population |
| `example_feature-spec_billing_dunning_and_grace.md` + `example_implementation-plan_billing_dunning_and_grace.md` | Billing/lifecycle/event-driven: webhooks, grace windows, reconciliation, recovery UX | Webhook contract testing, state-machine modeling, idempotency |
| `example_feature-spec_tenant_prompt_customization.md` + `example_implementation-plan_tenant_prompt_customization.md` | LLM integration + tenant settings + admin visibility/revert + safety gates + multi-phase | Phase boundary documentation, LLM safety gates, tenant-overridable settings with admin ceilings, version-history modeling |

The `tenant_prompt_customization` pair is the largest (~50 KB spec, ~70 KB plan) and the most architecturally complex. It's the closest structural analogue to a RelyLoop "agent prompts a search-config change, admin approves" flow even though the surface details differ — worth a once-over for any RelyLoop spec involving LLM-driven mutations with human gating.

## Adapting an example to RelyLoop

If you want to start a RelyLoop spec by copying an example (rather than starting from `feature-spec-template.md`):

1. Copy the example into your feature folder.
2. Strip every reference to: tenants/workspaces (RelyLoop is single-tenant for MVP1–3), audit-events architecture, admin impersonation, Stripe webhooks, drafts/creators/campaigns/outreach.
3. Re-anchor every cited path against the RelyLoop codebase (most won't exist; replace with proposals or remove).
4. Substitute domain nouns: `tenant → workspace/project/none`, `creator → trial-target`, `draft → search-config proposal`, etc.
5. Re-do the audit-event matrix as `"N/A — RelyLoop has no audit-events subsystem yet."`

In practice it is usually faster to start from `feature-spec-template.md` and use the examples only for reference.
