---
type: bug
priority: P2
status: idea
date: 2026-05-27
---

# Bug — CEILING badge on studies list assumes objective direction is `maximize`

## Origin

Gemini Code Assist medium-severity finding on PR #283
([`feat/study-list-ceiling-badge`](https://github.com/SoundMindsAI/relyloop/pull/283)).

## Problem

The `CEILING` badge in [`studies-table.column-config.tsx:METRIC_CEILING_THRESHOLD`](../../../ui/src/components/studies/studies-table.column-config.tsx)
flags rows where `best_metric >= 0.99`. The threshold check is correct
for **maximize** objectives — NDCG, MAP, MRR, Precision, Recall — where
≥0.99 means the metric is pinned at its upper bound.

For a **minimize** objective (per the [`study.direction`](../../../ui/src/lib/glossary.ts)
glossary entry, the system advertises both directions), a value of 0.99
isn't a ceiling at all — it's a **bad score**. The badge would mislabel
a genuinely-poor study as "Pinned at metric ceiling, optimizer found
nothing special," when the truth is the opposite.

## Why deferred

> **Preflight update (2026-05-29):** reason #1 below is now **STALE** — the
> bug was elevated from latent to live and fixed in PR (see
> [`bug_fix.md`](./bug_fix.md)). `feat_study_baseline_trial` added
> `direction: Literal["maximize","minimize"] = "maximize"` to
> [`ObjectiveSpec`](../../../../backend/app/api/v1/schemas.py) (schemas.py:579)
> after this idea was written, so a `direction=minimize` study **is creatable
> via the API today** — the badge can actively mislabel it. Reasons #2 and #3
> stood (StudySummary lacked `direction`; the detail page carries the deeper
> signal) and shaped the fix (the smallest option: add `direction` to
> StudySummary + gate the badge). Original deferral reasons preserved below
> for the historical record.

Three concrete reasons the badge can stay maximize-only for now:

1. **No minimize-direction metric currently supported.** ~~The objective
   metric allowlist in [`backend/app/eval/scoring.py`](../../../backend/app/eval/scoring.py)
   is NDCG / MAP / MRR / Precision / Recall — all "higher is better".
   No minimize study can be created today via API or UI.~~ **Stale —
   see preflight update above.** The metric allowlist is still
   maximize-natured, but `objective.direction` is now a settable field,
   so a minimize study (minimizing a higher-is-better metric) is
   creatable and the badge mislabels it.
2. **`StudySummary` doesn't expose `direction`.** Gemini's suggested
   inline fix (`row.original.direction !== 'minimize'`) would be a
   TypeScript error — the list-view shape is `{id, name, cluster_id,
   status, best_metric, created_at, completed_at}`. A real fix would
   add `direction` to the backend `StudySummary` Pydantic model + regen
   types — wider scope than the badge itself.
3. **The deeper signal lives on the detail page.** The Confidence
   panel already shows per-query outcomes / runner-up gap / CI band /
   convergence regime; the list badge is just an at-a-glance hint, not
   the authoritative read.

## Proposed capabilities

When MVP introduces a minimize-direction metric (or the first user
creates a custom objective with `direction=minimize`), one of:

- **Add `direction` to `StudySummary`** (smallest fix): one new field
  in [`backend/app/api/v1/schemas.py:StudySummary`](../../../backend/app/api/v1/schemas.py),
  regen frontend types, gate the badge on `direction === 'maximize'`.
- **Invert the threshold for minimize**: badge at `best_metric <= 0.01`
  (or whatever the natural floor is) when direction is minimize. Same
  glossary entry but with flipped copy.
- **Drop the heuristic, compute server-side**: backend computes a
  `saturated: bool` flag using both `best_metric` and the metric's
  known direction, exposes it on `StudySummary`. Avoids client-side
  guessing entirely.

## Scope signals

- Backend: 1-line schema change + 1 query column to the studies-list
  endpoint.
- Frontend: gate the existing badge code + (optionally) add minimize
  copy to the glossary.
- Test: 2 unit cases on the column-config (maximize-ceiling shows
  badge; minimize-floor shows badge).

## References

- PR #283 inline comment: <https://github.com/SoundMindsAI/relyloop/pull/283#discussion_r_>
- [`study.direction` glossary entry](../../../ui/src/lib/glossary.ts)
- [`scoring.py` metric allowlist](../../../backend/app/eval/scoring.py)
