# RelyLoop Documentation

The repository now uses a numbered documentation IA so related material stays grouped and sorts predictably in file browsers.

## Sections

- `00_overview/` — project-level context, status, and umbrella specifications
- `01_architecture/` — system design, ADR-adjacent technical overviews, interfaces, and topology docs
- `02_product/` — roadmap, release plans, scope docs, and product decisions
- `03_runbooks/` — operator and maintainer procedures
- `04_security/` — threat models, policies, and security-specific guidance
- `05_quality/` — testing strategy, quality gates, and validation docs
- `06_vendor_docs/` — vendor- or engine-specific notes, adapters, and integration references
- `07_research/` — exploratory notes, comparisons, and background analysis
- `08_guides/` — task-oriented how-tos, tutorials, migration guides, and FAQs
- `09_decisions/` — ADR-style decision records

## Conventions

- Put each document in the narrowest section that matches its primary audience and purpose.
- Keep vendor-specific behavior out of architecture docs when a `06_vendor_docs/` note is more precise.
- Use `09_decisions/ADR-xxxx-title.md` for durable decisions that should survive refactors.
- Prefer short index files in a section when it starts to accumulate many documents.

## Current seed docs

- `00_overview/product/relevance-copilot-spec.md` — umbrella product + architectural spec
- `02_product/mvp1-user-stories.md` — MVP1 user stories mapped to feature folders
- `02_product/planned_features/` — per-feature spec folders, each ready for `/impl-plan-gen`