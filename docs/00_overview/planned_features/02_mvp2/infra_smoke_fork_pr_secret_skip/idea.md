# infra_smoke_fork_pr_secret_skip — smoke job hard-fails on every external-fork PR because forked PRs can't read `OPENAI_API_KEY_TEST`

**Date:** 2026-06-01
**Status:** Idea — tangential discovery while merging PR #387 (`chore_arq_pool_aclose_deprecation`)
**Tracking issue:** [#410](https://github.com/SoundMindsAI/relyloop/issues/410) (public — gives external contributors a findable "known fork limitation, not your code" explanation)
**Type:** `infra_`
**Priority:** P2 — does not block this repo's own branches (internal PRs see the secret), but every **external contributor** PR gets a permanent red ✗ on the `smoke` job for a reason unrelated to their code. Elevated by the OSS-launch posture (CHANGELOG + CITATION.cff just landed, #382): a red X on a first-time contributor's PR reads as "your change is broken" when it isn't.

## Origin

PR #387 (the `arq_pool.aclose()` deprecation fix from external contributor `Yashi248`, merged 2026-06-02 as `2e49ac99`). After updating the branch and approving the workflow run, **every code-validating job passed** (backend lint/typecheck/tests/coverage, frontend, docker buildx, license, DCO, secrets-defense) — the **only** red was `smoke (operator-path tutorial flow)`, run `26792913411`, job result `failure`.

The smoke job failed on its very first real step, **"Sanity-check OPENAI_API_KEY_TEST is populated"**, before running a single test:

```
##[error]OPENAI_API_KEY_TEST secret is empty — smoke gate requires it
         (per chore_tutorial_polish §3 + decision log M5)
##[error]Process completed with exit code 1.
```

## Problem

`.github/workflows/pr.yml` triggers on `pull_request:` ([pr.yml:43](../../../../.github/workflows/pr.yml)) — **not** `pull_request_target`. GitHub deliberately withholds repository secrets from workflows triggered by a PR opened from a **fork** (security: prevents secret exfiltration by an attacker's PR). So for any external-contributor PR:

1. `OPENAI_API_KEY_TEST: ${{ secrets.OPENAI_API_KEY_TEST }}` ([pr.yml:536](../../../../.github/workflows/pr.yml)) resolves to the empty string.
2. It is written to `./secrets/openai_key` ([pr.yml:553](../../../../.github/workflows/pr.yml)) as a zero-byte file.
3. The "Sanity-check OPENAI_API_KEY_TEST is populated" step greps for non-whitespace content and `exit 1`s with the message above ([pr.yml:565–571](../../../../.github/workflows/pr.yml)).

This is **structural**, not a code defect — it reproduces identically on every fork PR regardless of the diff. The smoke job's existing `if: ${{ vars.SKIP_HEAVY_CI != 'true' }}` ([pr.yml:492](../../../../.github/workflows/pr.yml)) is a blunt global kill-switch; it is not fork-aware, so when heavy CI is on, fork PRs always go red here.

## Proposed capability

Make the `smoke-test` job **fork-aware**: when the PR head repo is a fork (the runner therefore has no secret), skip the smoke job gracefully with an explicit notice instead of hard-failing. Candidate shapes (pick at spec time):

- **A — Job-level `if` guard (preferred).** Add a fork condition to the existing `if:` so the whole job is skipped on fork PRs:
  `if: ${{ vars.SKIP_HEAVY_CI != 'true' && github.event.pull_request.head.repo.full_name == github.repository }}`.
  A skipped job shows neutral (not red). Pair with a tiny always-green "smoke (skipped — fork PR, no secrets)" notice job so the status is self-explanatory to the contributor.
- **B — In-step soft skip.** Change the sanity-check step to detect the empty secret on a fork and `echo "::notice::"` + early-`exit 0` (with a guard that it ONLY soft-skips for forks, never for the upstream repo where an empty secret is a real misconfiguration).
- **C — `pull_request_target`.** Rejected by default — runs in the base-repo context with secret access against untrusted fork code; a known RCE-class footgun. Out of scope unless paired with a vetted checkout-and-sandbox pattern.

Whichever is chosen, the upstream-repo path MUST keep failing loudly on a genuinely empty secret (the original M5 intent) — the soft-skip applies **only** to the fork case.

## Scope signals

- **CI / infra:** one YAML job in `pr.yml` (`if:` guard + optional notice job). No backend/frontend/migration changes.
- **Test coupling:** none — no application code touched.
- **Decision surface:** which approach (A/B/C), and whether to add the always-green notice job so a skipped status is legible to contributors. One forcing decision: confirm the soft-skip is fork-gated and never weakens the upstream empty-secret guard.

## Why deferred (not fixed inline)

Surfaced at PR #387 merge time; that PR was an external contributor's two-line deprecation fix and the right call was to merge it (the failure was provably environmental — see the adjudication comment on #387). Editing `pr.yml`'s smoke job inside #387 would have mixed an unrelated CI-policy change into a contributor's narrow diff, and the contributor can't even test a secrets-dependent workflow change from their fork. Belongs in its own maintainer-owned infra PR.

## Relationship to other work

- **[`infra_smoke_reseed_runtime_budget`](../infra_smoke_reseed_runtime_budget/idea.md)** — the **sibling "smoke job stays red" issue**, but an **independent** failure mode. That one is about the Playwright demo-ubi reseed blowing the 25-min wall-clock budget once Solr boots; this one is about fork PRs lacking the secret. They fail at different steps and neither fix resolves the other: even with the runtime budget fixed, a fork PR still dies at the secret sanity-check; even with the secret present, an internal PR can still hit the runtime cap. Both must ship for `smoke` to be green on **every** PR. Coordinate so the two `pr.yml` edits don't collide.
- **[`chore_arq_pool_aclose_deprecation`](../chore_arq_pool_aclose_deprecation/idea.md)** — the shipped fix (PR #387, `2e49ac99`) whose CI run surfaced this. That work is done; this is the CI-policy gap its first external-contributor run exposed.
