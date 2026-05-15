# feat_contextual_help — Phase 3 deferred tracking (chat + cluster registration + home onboarding)

**Date:** 2026-05-14
**Status:** Deferred — Phase 1 ([`feature_spec.md`](../2026_05_15_feat_contextual_help/feature_spec.md), shipped via PR #122 on 2026-05-15) covered create-study modal + study-detail surface only. Phase 3 picks up the three onboarding-shaped surfaces.
**Origin:** Carved out of [`feat_contextual_help/idea.md`](../2026_05_15_feat_contextual_help/idea.md) §"Proposed capabilities → Phase 3 — chat + cluster registration + home onboarding" during cycle 1 of spec-gen scope-lock (2026-05-14, idea Locked Decisions §1).
**Depends on:** Phase 1 ships (primitives + glossary file). Phase 2 may or may not have shipped — Phase 3 doesn't depend on it.

## Problem (still applicable after Phase 1)

Three surfaces affect first-run onboarding rather than mid-study workflows:

1. **Cluster registration** ([`register-cluster-modal.tsx`](../../../../ui/src/components/clusters/register-cluster-modal.tsx)) — the `auth_kind` dropdown lists four wire values (`es_apikey` / `es_basic` / `opensearch_basic` / `opensearch_sigv4`) with no per-option explanation; the `credentials_ref` field reads `./secrets/<name>` with no context for a first-time operator (the Docker-secrets mounting pattern is documented at [`docs/01_architecture/deployment.md` §"Secrets"](../../../01_architecture/deployment.md) but not surfaced in the modal).
2. **Chat composer** ([`composer.tsx`](../../../../ui/src/components/chat/composer.tsx) + chat empty state) — a new user opens `/chat`, sees a blank composer, and has no concrete example prompts to try. The security warning banner at [`chat/[id]/page.tsx:191-209`](../../../../ui/src/app/chat/[id]/page.tsx) is preserved but doesn't seed prompts.
3. **Home page first-run state** ([`page.tsx`](../../../../ui/src/app/page.tsx)) — when no clusters / no studies / no proposals exist, the count cards render `0` with no "start here" guidance. This is the only product-design-shaped item in the whole feature.

## Proposed Phase 3 capabilities (full list — pick up in MVP2 spec)

### Cluster registration modal

- Per-option `InfoTooltip` on each `auth_kind` value, attached to the `<SelectItem>` (or rendered as adjacent icons in the trigger area, TBD by the future MVP2 spec). Glossary keys: `cluster.auth_kind.{es_apikey,es_basic,opensearch_basic,opensearch_sigv4}`. Values must match [`backend/app/api/v1/schemas.py:AuthKind`](../../../../backend/app/api/v1/schemas.py).
- `HelpPopover` next to the `Credentials ref` field (key: `cluster.credentials_ref`) with a multi-paragraph explanation: what the `./secrets/<name>` path means (Docker-mounted secrets), how to create the file, and a link to [`docs/03_runbooks/cluster-registration.md`](../../../03_runbooks/cluster-registration.md) + [`docs/01_architecture/deployment.md` §"Secrets"](../../../01_architecture/deployment.md).
- `InfoTooltip` on the `Environment` field (key: `cluster.environment`) for `prod` / `staging` / `dev` per-value tooltips (values from `EnvironmentWire` in the same schemas file).
- Existing `DialogDescription` at [`register-cluster-modal.tsx:98`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) is preserved.

### Chat composer + first-run state

- A new component, rendered when the chat composer is empty and there are no prior messages, showing **3–5 example prompts as click-to-send chips**. Example prompts (subject to product review):
  - "Tell me about the prod-es cluster"
  - "Run a study optimizing NDCG@10 for the product-search index"
  - "Open a PR for the latest proposal"
  - "Why did trial 47 get pruned?"
  - "Generate judgments for the e-commerce query set"
- The example-prompt strip is rendered inline (not as a tooltip) and dismisses when the user types their first character or sends their first message.

### Home page first-run state

- A "Start here" panel rendered when **all three** of `useClusters`, `useStudies`, `useProposals` return empty arrays. The panel layout is the **only product-design-shaped item in the entire feature** — see "Open question for the future MVP2 spec" below.
- Each step in the panel is an inline link to the relevant page (`/clusters`, then `/query-sets`, then `/studies`).

## Open question for the future MVP2 spec (carried over from idea Locked Decisions)

**Design call: layout of the home-page "Start here" panel.** Three concrete options:
1. **Simple ordered list** (recommended default in the idea) — three numbered steps with inline links. Matches the existing minimal-chrome aesthetic; cheapest to ship.
2. **Stripe-style checklist** — bordered card with checkbox-style icons that "complete" as the user progresses (cluster registered → query set created → study run). More polish, requires per-step completion detection (likely already available via the same TanStack Query hooks).
3. **Empty-state illustration** — design-led with custom SVG + heading. Highest polish, requires design-partner illustration work.

The MVP2 spec for this phase **MUST** lock this decision before implementation. Default if undirected: option 1.

## Scope signals

- **Backend:** none. All copy is hardcoded glossary entries + the example-prompt list.
- **Frontend:** glossary entries (~10 new keys for cluster auth/env/credentials); edits to 3 component files (`register-cluster-modal.tsx`, `chat/composer.tsx` or a new sibling, `app/page.tsx`); one new component for the "Start here" panel + one for the example-prompts chip strip.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.
- **CLAUDE.md absolute-rules walked:** Enumerated Value Contract Discipline — auth_kind + environment values cite the canonical backend schemas file per the FR-4 pattern.

## Why this is deferred

- Phase 3 is mostly **first-run onboarding** rather than mid-workflow help — design partners who reach beyond the tutorial may not encounter these surfaces until weeks later. Phase 1's cliff is far steeper.
- The home-page "Start here" panel is the only product-design-shaped item; deferring lets design-partner feedback inform the design call (the three options above span a range of polish levels).
- Splitting Phase 3 out keeps the MVP1 spec tight and avoids forcing a design decision that benefits from real-world feedback.

## Relationship to other work

- [`feat_contextual_help/feature_spec.md`](../2026_05_15_feat_contextual_help/feature_spec.md) — Phase 1 (shipped) provides the primitives.
- [`infra_adapter_elastic` (PR #16)](../2026_05_10_infra_adapter_elastic/) — the underlying cluster registration data model and UI this phase overlays.
- [`feat_chat_agent` (PR #60)](../2026_05_12_feat_chat_agent/) — the chat surface this phase adds prompt seeding to.
- [`feat_studies_ui` (PR #50)](../2026_05_12_feat_studies_ui/) — the home page (`app/page.tsx`) this phase adds the first-run panel to.
