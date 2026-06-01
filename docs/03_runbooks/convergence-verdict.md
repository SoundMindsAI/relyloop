<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Convergence verdict — interpretation and operator playbook

**Owner:** `feat_study_convergence_indicator` (`backend/app/domain/study/convergence.py` + `ui/src/components/studies/convergence-panel.tsx`).
**Audience:** the relevance engineer who wakes up to a finished study (or an overnight chain) and wants a one-glance answer to *did this actually finish learning, or did I stop it too early?*

This is the operator-facing reference for the **Convergence** panel on `/studies/[id]`, the `<convergence>` block in the digest narrative, and the per-link verdicts the overnight-autopilot chain panel surfaces (when that feature lands).

The classifier itself is a 50-line pure-domain function. Don't memorise the algorithm — memorise the three verdicts and what each one means for your next move.

---

## The three verdicts

### Converged

> The optimizer settled. More trials would not meaningfully help. Ship the recommended config, or use the digest's `narrow` follow-up to confirm the winner is locally stable.

**Trigger.** Trailing-window improvement is below the lift epsilon (`AUTO_FOLLOWUP_LIFT_EPSILON = 0.005`). Specifically: across the last `window_size` completed Optuna trials (capped at 20, never fewer than 5), the best-so-far metric moved by less than 0.005. The window-size clamp keeps short studies honest — for a 24-trial study the window is `max(5, 24 // 5) = 5`; for a 200-trial study it's the full 20.

**What it means.** The best-so-far curve has a long flat tail. The optimizer explored, found a strong region, and stopped finding meaningful improvements. The digest narrative's lead recommendation (ship / narrow / hand off) is trustworthy.

**Recommended action.** Move to the next step in your workflow — review the proposal, ship the config, or run a `narrow` follow-up to lock in the winning region. Re-running with more trials is **not** the right move.

### Still improving when it stopped

> The optimizer was still finding gains in the last `window_size` trials. The result is probably under-budgeted; re-run with a larger preset.

**Trigger.** Total complete trials ≥ TPE warmup floor (`STUDIES_TPE_WARMUP_FLOOR = 50`) AND the trailing-window improvement is **above** the lift epsilon.

**What it means.** The best-so-far curve is still climbing at the right edge. The optimizer hasn't found the local optimum yet; whatever it picked is the best so far, but more trials would very likely beat it. The digest narrative will (per Story 5.2's framing rule) lead with "re-run with a larger trial budget" and demote any `narrow` / `widen` follow-ups to secondary positions.

**Recommended action.** Re-run with the next-larger budget preset:

| Current preset | Recommended next preset | Trial budget |
|---|---|---|
| Quick (preview) | **Standard** | 200 trials |
| Standard | **Deep** | 1000 trials |
| Deep | Stay on Deep + audit the search space | — |

If you're already on Deep and still seeing this verdict, the issue is usually the search space — bounds may be too wide (use a `narrow` follow-up to focus on the winning region) or the wrong parameters may be tuned (re-examine the template's `declared_params`).

### Too few trials to tell

> The study ran below the TPE warmup floor. The optimizer never left random search; treat the result as preliminary.

**Trigger.** Total complete trials are between `CONVERGENCE_FLAT_MIN_COMPLETE` (5) and `STUDIES_TPE_WARMUP_FLOOR` (50). Below 5, the panel renders the null-state badge "Verdict pending — not enough trials yet" instead.

**What it means.** TPE's surrogate model needs ~50 warmup trials before the exploit phase kicks in. Below that, every trial is effectively random sampling — the "winner" is whichever random draw happened to score well, not a config the optimizer chose. The result might still be useful as a sanity check, but you cannot trust the winner as the best your search space can produce.

**Recommended action.** Re-run with **at least Standard** (200 trials). The digest narrative will explicitly caution with "preliminary result; re-run with a larger budget" in this case (Story 5.2's framing rule applies to both `still_improving` and `too_few_trials` for that reason).

---

## When the verdict is `null` (panel shows a neutral badge)

The aggregator returns `None` whole-object in four cases. Each produces a distinct null-state badge:

| Badge label | Status / state | What to do |
|---|---|---|
| **Verdict pending — still running** | Study status is `queued` or `running` | Come back when the study completes — the classifier never runs on in-flight studies (the trial set is still mutating). |
| **Verdict pending — not enough trials yet** | Study terminal AND `trials_summary.complete < 5` | The classifier needs at least 5 usable Optuna trials; the panel renders this fallback to avoid faking a verdict on a degenerate seed. Re-run with a larger preset. |
| **Verdict unavailable** | Study terminal AND `trials_summary.complete >= 5` BUT the API still returned `convergence: null` | A graceful-degrade path fired: the persisted `objective.direction` was an invalid string (anything other than `maximize` / `minimize`) OR the classifier raised an unexpected exception. Check the worker logs for `convergence_invalid_direction` or `convergence_classifier_exception` (both WARN-level structlog events). |

If you see "Verdict unavailable" on a study you expected to classify cleanly, run:

```bash
docker compose logs api worker 2>&1 | rg 'convergence_(invalid_direction|classifier_exception)'
```

The `study_id` in the WARN event will match the study URL.

---

## Worked minimize example

Convergence is direction-aware: it asks "did *best* stop moving?" where *best* is `max(primary_metric)` for maximize studies and `min(primary_metric)` for minimize. Concretely, for a study tuning latency (minimize):

| Trial | `primary_metric` | best-so-far | improvement vs trial −20 |
|---|---|---|---|
| 1 | 280 ms | 280 ms | — |
| 50 | 165 ms | 165 ms | — |
| 100 | 152 ms | 152 ms | — |
| 200 | 148 ms | 148 ms | 0.004 (less than 0.005 epsilon) |

Verdict: **Converged**. The best (lowest) latency stopped improving in the trailing 20 trials. The sign-flipped improvement is `(window_start − window_end) = 0.004` — below the epsilon, so the classifier flags `converged` regardless of direction.

If the same series had `148 ms` at trial 180 and `140 ms` at trial 200 instead — an 8 ms drop in the last window — the verdict would flip to `still_improving` and the digest would lead with "re-run with a larger trial budget."

---

## Troubleshooting noisy-tail mis-classification

Occasionally a study with genuine noise in the late-trial primary metric will get classified `converged` even though the eye sees the curve oscillating. The classifier compares the **best-so-far** curve (a monotonic series by construction), not the raw `primary_metric` series, so this is rarer than it sounds — but it can still happen when the late trials all land slightly worse than a much earlier peak.

If the verdict feels wrong:

1. **Open the curve panel.** The "Show convergence curve" collapsible always renders the best-so-far series, even on `converged` verdicts. A long flat tail means the verdict is right; a tail that visibly rises in the last window with the verdict saying `converged` is a bug worth filing.
2. **Compare improvement-in-window to epsilon.** The panel renders the improvement as "Improved by X in the last N trials." If `X < 0.005`, the verdict is mathematically correct — your intuition is that the curve looked steeper than it actually was.
3. **Check the trial scatter.** If the late trials are noisy near the peak (5 trials within 0.001 of the winner, 5 trials 0.05 below), the best-so-far stays at the peak and the verdict is `converged` correctly — the noise is real, but it's noise around the answer, not improvement.
4. **Filter on direction.** A `minimize` study with a wrongly-stamped `objective.direction = "maximize"` will produce an inverted curve. The panel surfaces `direction` explicitly; if it disagrees with what you configured, fix the study config and re-run.

If steps 1–4 don't explain the verdict, file a bug at [`docs/00_overview/planned_features/`](../00_overview/planned_features/) under the `bug_` prefix with the study ID, the verdict, and a screenshot of the curve.

---

## Related references

- [`feat_study_convergence_indicator/feature_spec.md`](../00_overview/implemented_features/2026_05_31_feat_study_convergence_indicator/feature_spec.md) — full FR table, decision log, AC matrix.
- [`feat_overnight_autopilot`](../00_overview/implemented_features/2026_05_31_feat_overnight_autopilot/) — the chain panel that surfaces per-link convergence verdicts (FR-7 soft contract).
- [`feat_study_sub_warmup_guard`](../00_overview/implemented_features/2026_05_29_feat_study_sub_warmup_guard/) — the create-study wizard guard that prevents under-budgeting before submit.
- [`feat_pr_metric_confidence`](../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/) — the sibling `ConfidencePanel` (note the name-collision discipline: that panel classifies *winner-trial timing*; this one classifies *metric plateau*).
- Glossary entries: `convergence_verdict`, `convergence_curve`, `convergence_window` in [`ui/src/lib/glossary.ts`](../../ui/src/lib/glossary.ts).
