# Pipeline Status — Native-first local LLM (use host Ollama; demote Docker bundle)

**Release:** mvp2

## Idea
- Status: Complete
- File: idea.md

## Spec
- Status: Approved
- Date: 2026-06-19
- File: feature_spec.md
- Cross-model review: GPT-5.5 passed (2 cycles — cycle 1: 6 findings all accepted incl. the NS-1 Linux-loopback trap; cycle 2: 3 findings accepted, 0 High → converged)
- Phases: 1 (single phase; no deferred work)

## Plan
- Status: Approved
- Date: 2026-06-19
- File: implementation_plan.md
- Cross-model review: GPT-5.5 passed (2 cycles — cycle 1: 6 findings all accepted incl. moving sentinel + FR-8 messages into the testable helper + tightening shape validation; cycle 2: 0 findings → converged)
- Stories: 4 (helper allowlist / native-detect helper + tests / install.sh + extra_hosts / docs)
- Phases covered: single phase (no deferred work)

## Implementation
- Status: Complete
- Date: 2026-06-19
- PR: #577 (squash-merged `71803791`)
- Stories: 4/4 + phase-gate GPT-5.5 fixes + Gemini temp-dir cleanup
- CI: green (2811 unit tests; parse_relyloop_llm 17 + relyloop_native_llm 29 bash cases; compose-shape extra_hosts)
- Cross-model review: GPT-5.5 each stage (spec 2, plan 2, phase-gate 1 cycle / 5 findings, 4 accepted + 1 rejected w/ counter-evidence); Gemini 1 accepted
- Operator-path: validated live against a running native Ollama (detect + warn-unpulled + wire) + FR-8 container reachability (HTTP 200)
- Single phase — no deferred work
