# Study convergence indicator — "did this study actually finish learning, or did I stop it too early?"

**Date:** 2026-05-29
**Status:** Idea — surfaced from an operator dogfooding review (2026-05-29). The feedback half of the "overnight autopilot ergonomics" theme.
**Priority:** P2 — valuable feedback loop, but lower-leverage than fixing the defaults. Best landed alongside [`feat_study_sub_warmup_guard`](../../../implemented_features/2026_05_29_feat_study_sub_warmup_guard/feature_spec.md).
**Origin:** Same dogfooding trace that found 6 of 7 studies ran 12–15 trials (well under the TPE ~10-trial warmup). The operator had no on-screen signal that those studies stopped before the optimizer converged — so "should I have run more trials?" was unanswerable from the UI, and the digest's narrow/widen follow-ups filled the void as the apparent next step.
**Depends on:** MVP1 study lifecycle + trials persistence (shipped). Independent of the MVP2 anchors. The `trials` table already stores per-trial metric + `optuna_trial_number`, which is all the raw material a convergence view needs.

## Problem

After a study completes, the UI shows the best metric and a trials table, but **nothing tells the operator whether the metric had plateaued or was still climbing when the study stopped.** This is the difference between "this is a real answer" and "I stopped the optimizer mid-climb." Concretely:

- A study that ran 12 trials and whose best-so-far metric was still improving at trial 11 is almost certainly under-budgeted — more trials would help. The operator should re-run with a larger budget, not accept a narrow/widen follow-up.
- A study whose best-so-far metric flattened 200 trials ago genuinely converged — a follow-up that *narrows* might find a little more, but the big win is banked.

Today these two cases look identical in the UI. The operator can't distinguish "the optimizer is done" from "the optimizer was just getting started," so they can't tell whether the friction they feel (needing follow-ups) is real or self-inflicted. This is the feedback gap that makes [`feat_study_sub_warmup_guard`](../../../implemented_features/2026_05_29_feat_study_sub_warmup_guard/feature_spec.md) hard to reason about without — presets prevent under-budgeting, this indicator *confirms* the budget was enough.

## Proposed capabilities

### Best-so-far convergence curve on the study detail page

Plot best-metric-so-far against `optuna_trial_number` (a monotonic non-decreasing curve for a maximize study). The shape tells the story at a glance: still-rising tail = under-budgeted; long flat tail = converged. The raw data is already in the `trials` table; this is a read-side aggregation + a Recharts line (the UI already uses Recharts for parameter-importance and trial-scatter).

### A plain-language convergence verdict

A small badge / one-liner derived from the curve, e.g.:

- **"Converged"** — best metric flat for the last N trials (no improvement beyond epsilon).
- **"Still improving when it stopped"** — best metric improved within the last N trials → suggest re-running with a larger budget.
- **"Too few trials to tell"** — ran below the TPE warmup floor → the result is effectively random search; re-run with ≥ Standard budget.

The verdict is the operator-facing payoff — it answers "was this enough?" without making them read a chart. Pure-domain logic over the trial series (testable without fixtures).

### Wire the verdict into the digest / proposal framing

When the verdict is "still improving" or "too few trials," the proposal surfaces "re-run with a larger budget" as the recommended next step *ahead of* the narrow/widen follow-ups — correcting the misattribution where an under-budgeted study's follow-ups look like the intended workflow.

## Scope signals

- **Backend:** small. A pure-domain convergence classifier over the ordered trial-metric series + a read-side endpoint/field to expose best-so-far series + verdict. No migration (reads existing `trials`).
- **Frontend:** moderate. One Recharts line on the study detail page + a verdict badge. Reuses existing chart infrastructure.
- **Migration:** none.
- **Config:** none (epsilon + "last N trials" window are constants, possibly shared with the auto-followup lift epsilon for consistency).
- **Audit events:** N/A (pre-`audit_log`).

## Why deferred / not inline

It's a genuine new analysis surface (a classifier + a chart + digest wiring), not a one-liner, and it's most useful *with* the budget presets — alone it diagnoses a problem the presets are meant to prevent. Sequencing it next to presets means the operator both avoids under-budgeting and can verify they did.

## Relationship to other work

- **Sibling theme:** [`feat_study_sub_warmup_guard`](../../../implemented_features/2026_05_29_feat_study_sub_warmup_guard/feature_spec.md) (prevents under-budgeting; this confirms it worked) and [`feat_overnight_autopilot`](../feat_overnight_autopilot/idea.md) (each chain link gets a convergence verdict, so the morning summary can flag "link 2 was still improving — the chain may have stopped one budget short").
- **Composes with the shipped** [`feat_pr_metric_confidence`](../../../implemented_features/2026_05_21_feat_pr_metric_confidence/) — convergence is a natural input to the PR-body confidence framing ("converged after 340 trials" is a stronger claim than "best of 12").
- **Reuses** the parameter-importance + trial-scatter Recharts surfaces from [`feat_digest_proposal`](../../../implemented_features/2026_05_11_feat_digest_proposal/).

## Open questions for /spec-gen

1. **Convergence definition** — trailing-window-flat vs slope-of-best-so-far vs Optuna's own improvement signal — pick one defensible classifier.
   **Recommended default:** **Trailing-window-flat.** A study is "Converged" when `best_metric_so_far` has improved by < `CONVERGENCE_EPSILON` over the last `CONVERGENCE_WINDOW` completed trials. Reuse the existing auto-followup lift epsilon (`0.005` / 0.5% — `backend/workers/auto_followup.py`) so the digest's "re-run vs follow-up" recommendation lines up with what the chaining engine would also decide. Default `CONVERGENCE_WINDOW = 20` (clamped to `max(5, total_trials // 5)` so very short studies don't trigger false "converged" on a 4-trial flat tail). Below the TPE warmup floor (50 trials per `STUDIES_TPE_WARMUP_FLOOR`), classify as "Too few trials to tell" regardless of window state. Avoids tying the verdict to Optuna's internal `_is_converged` signal (drift risk + black-box).
2. **Whether the "re-run with larger budget" recommendation is owned here or in `feat_study_sub_warmup_guard`'s digest note** (avoid double-ownership).
   **Recommended default:** **This feature owns the post-run recommendation.** `feat_study_sub_warmup_guard` (shipped) is preventive — its inline warning gates the create-study modal at submit-time. This feature is corrective — when a study finishes "Still improving" or "Too few trials," the verdict surfaces "re-run with X-budget" copy. The two flows don't overlap (one fires before submit, one fires after completion) so double-ownership doesn't arise.
3. **Whether the convergence curve is always shown or only when the verdict is non-trivial.**
   **Recommended default:** **Verdict badge always shown; curve always available but the panel is collapsed-by-default for "Converged" verdicts and expanded-by-default for "Still improving" / "Too few trials" verdicts.** For converged studies the curve is corroborating evidence, not the primary signal — but it must be reachable in one click so operators can verify the verdict didn't mis-classify a noisy tail.
