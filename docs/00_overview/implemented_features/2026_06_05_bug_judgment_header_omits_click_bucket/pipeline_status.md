# Pipeline Status — Judgment-list header renders the `click` (UBI) source bucket

## Idea
- Status: Complete
- File: idea.md

## Spec
- Status: Approved
- Date: 2026-06-02
- File: feature_spec.md
- Cross-model review: GPT-5.5 passed (2 cycles, 4 findings — all Low, all accepted; 4 spurious tampered-prompt findings rejected)
- Phases: 1 total, 1 covered by spec (single-phase)

## Plan
- Status: Approved
- Date: 2026-06-02
- File: implementation_plan.md
- Cross-model review: GPT-5.5 passed (1 cycle, 0 findings)
- Stories: 2 total across 1 epic
- Phases covered: 1 of 1 (single-phase)

## Implementation
- Status: Complete (PR #470, squash-merged `66d1873`, 2026-06-05)
- Release: mvp2
- Note: Frontend-only, no migration. The judgment-list detail header now renders the `click` (UBI) bucket as a third slash-joined term (`source_breakdown.click`), relabeled `LLM / Human / Clicks`, with a source-of-truth comment + an `InfoTooltip` reusing the existing `judgment.source.click` glossary key (FR-4 implemented). 9 vitest cases (3 existing chip + 6 new) + a real-backend E2E assertion in `ubi-source-filter.spec.ts`. Gemini: 1 accepted (locale-robust E2E digit-parse), 1 rejected (the `click` field is non-optional in the TS type + atomic Compose deploy — guard would mask a contract violation). All 19 CI checks green.
