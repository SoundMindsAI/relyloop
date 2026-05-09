# Feature Templates

Templates for the spec → plan → implement pipeline:

1. [`idea-template.md`](idea-template.md) — lightweight tracking for deferred or exploratory work
2. [`feature-spec-template.md`](feature-spec-template.md) — full feature specification (the contract between product and engineering)
3. [`implementation-plan-template.md`](implementation-plan-template.md) — story-by-story plan derived from an approved spec

## How to use

1. Copy the template into your target feature folder under [`docs/02_product/planned_features/`](../).
2. Replace every `<placeholder>`.
3. Reference the canonical architecture docs in [`docs/01_architecture/`](../../../01_architecture/) for technical decisions (stack, conventions, data model, etc.) — feature specs should cite arch docs by section, not duplicate them.
4. Keep section order unless there is a strong reason to deviate.
5. Do not delete traceability, test strategy, or documentation-update sections.

## Folder naming convention

New folders under `planned_features/` use a single-axis **work-type prefix**, mirroring Conventional Commits prefixes:

| Prefix | Use for | Example |
|---|---|---|
| `feat_` | New user-facing capability or behavior | `feat_study_lifecycle/` |
| `bug_` | Defect fix with user-visible impact | `bug_trial_metric_off_by_one/` |
| `chore_` | Refactor, rename, dead-code removal, tech debt — no user-visible behavior change | `chore_rename_cluster_to_target/` |
| `infra_` | Deployment, CI, hosting, environment, dependency upgrades | `infra_foundation/` |
| `epic_` | Multi-phase bundle containing ≥2 dependent child feature folders | `epic_observability/phase_01_langfuse/` |

**Rules:**

- One prefix per folder. If work spans types (refactor that enables a new feature), pick the one the **user** sees first — usually `feat_`.
- **Domain is conveyed by the name**, not by a second prefix. `feat_study_lifecycle/` is obviously study-management; `feat_studies_management_lifecycle_v1/` is noise.
- **Epic children use `phase_NN_` numbering** for dependency order.
- Keep the prefix short (≤6 chars) so the descriptive tail gets the character budget.
