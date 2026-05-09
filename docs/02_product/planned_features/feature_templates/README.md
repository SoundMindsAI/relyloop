# Feature Templates

> **Ported from the sibling `creator-discovery-outreach` project on 2026-05-08.** Universal renames are applied. Each template carries a `<!-- PORTING BANNER -->` HTML comment at the top with the actionable conditional-section guidance — read it before filling the template in, then strip it. CDO domain anecdotes (creators, drafts, campaigns, audit-events, `OUTREACH_EMAIL_SENT`) are kept verbatim as illustrative provenance — apply the underlying structural rule to RelyLoop's domain (relevance trials, search-configs, engines, Pull Requests).

These templates are optimized for a spec-based feature-development workflow with:

- Multi-tenant safety and explicit tenant scoping (where applicable)
- Contract-first API behavior
- Given/When/Then acceptance criteria
- Test-layer planning (unit, integration, contract, e2e)
- Documentation update obligations across `docs/01_architecture` through `docs/05_quality`
- Lean refactor planning with bounded scope and measurable guardrails

They draw on external best-practice references for:

- specification by example and single-source-of-truth examples
- testable and unambiguous acceptance criteria
- forward/backward requirements traceability
- explicit requirement strength language (`MUST`, `SHOULD`, `MAY`)

## Included templates

1. `feature-spec-template.md` — full feature specification
2. `implementation-plan-template.md` — story-by-story implementation plan
3. `idea-template.md` — lightweight tracking for deferred work, future phases, and feature ideas

## How to use

1. Copy the template into your target feature folder.
2. Replace all placeholders in angle brackets.
3. Keep section order unless there is a strong reason to deviate.
4. Do not delete traceability, test strategy, docs update, or refactor sections.
5. Keep assumptions/dependencies explicit and versioned by date.

## Folder naming convention

New folders under `planned_features/` use a single-axis **work-type prefix**. This mirrors the Conventional Commits prefixes used in `git log` (`feat:`, `fix:`, `chore:`, etc.), so the mental model carries over from commit messages to planned work.

| Prefix | Use for | Example |
|---|---|---|
| `feat_` | New user-facing capability or behavior | `feat_session_management/` |
| `bug_` | Defect fix with user-visible impact | `bug_plan_change_missing_role_check/` |
| `chore_` | Refactor, rename, dead-code removal, tech debt — no user-visible behavior change | `chore_rename_auth_events_to_audit_events/` |
| `infra_` | Deployment, CI, hosting, environment, dependency upgrades | `infra_database_security_hardening/` |
| `epic_` | Multi-phase bundle containing ≥2 dependent child feature folders | `epic_account_security/phase_01_...` |

**Rules of thumb:**

- One prefix per folder. If work spans types (refactor that enables a new feature), pick the one the **user** would see first — usually `feat_`.
- **Domain is conveyed by the name itself**, not by a second prefix. A folder called `feat_mfa_management_and_hibp/` is obviously auth/security work. Adding `feat_auth_mfa_management...` would be noise.
- **Epic children use `phase_NN_` numbering** for dependency order — see `epic_account_security/` as the reference pattern (`phase_01_session_management/`, `phase_02_...`, etc.).
- **Retroactive renames are not required.** Apply the convention to all new folders (RelyLoop adopted this taxonomy on 2026-05-08); any older `feature_*/` folders can be renamed opportunistically if touched for other reasons, but bulk rename churn is discouraged.

**Why single-axis:** two-axis (type + domain) taxonomy scales poorly. `feat_auth_security_mfa_management/` saves no real time over just reading the name. Keep the prefix short (≤6 chars) so the descriptive tail gets the character budget.

## Which example to start from

> The `examples/` directory contains specs/plans from the source `creator-discovery-outreach` project. They are kept as **structural references** — copy the section layout, the level of detail, the test-strategy breakdown — but the domain content (auth/billing/LLM-prompt customization) does not map to RelyLoop. See [`examples/README.md`](examples/README.md) for the adaptation steps.

Use the example pair that is closest to your feature's structural complexity:

- Start from `examples/example_feature-spec_workspace_health_alerts.md` +
	`examples/example_implementation-plan_workspace_health_alerts.md` when the feature is
	auth/admin/tenant-operations heavy (role gating, stateful remediation actions, audit trails).
- Start from `examples/example_feature-spec_billing_dunning_and_grace.md` +
	`examples/example_implementation-plan_billing_dunning_and_grace.md` when the feature is
	billing/lifecycle/event-driven heavy (webhooks, grace windows, reconciliation, recovery UX).
- Start from `examples/example_feature-spec_tenant_prompt_customization.md` +
	`examples/example_implementation-plan_tenant_prompt_customization.md` when the feature
	involves LLM integration, tenant-facing settings with version history, admin visibility/revert,
	safety gates, or multi-phase delivery (Phase 1 + Phase 2).

Rule of thumb:
- If your primary complexity is authorization + operator workflows, pick the workspace-health example.
- If your primary complexity is financial state transitions + external event ordering, pick the billing example.
- If your primary complexity is LLM/AI integration + tenant settings + admin oversight, pick the prompt customization example.
- If your feature spans multiple domains, start from the example closest to your primary complexity and pull
  patterns from the other examples where needed — particularly §5 RBAC matrix, §7.4 error code
  catalog, and §8 data model column detail.
