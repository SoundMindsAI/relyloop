# Dashboard one-liner overrides

This directory holds sidecar override files for the MVP1/MVP2 dashboard generator at [`scripts/build_mvp1_dashboard.py`](../../../scripts/build_mvp1_dashboard.py).

## Purpose

The dashboard generator pulls each feature's one-liner description from its `feature_spec.md`'s `## 1) Purpose` block (the `Outcome` bullet, falling back to `Problem`). For **implemented features**, that `feature_spec.md` is frozen historical — it describes what shipped at the time and must not be back-edited (per the convention in CLAUDE.md + the spec author's "historical artifacts — leave alone" rule).

That works fine until a **later feature** changes the behavior the historical row described. Example: `infra_ir_measures_migration` (2026-05-23) swapped the IR-evaluation engine in `backend/app/eval/scoring.py`. The frozen `infra_optuna_eval` spec's Outcome line still names the prior engine (correctly — that's what shipped). But the current-state dashboard's row for `infra_optuna_eval` now mis-describes what its code does today.

This directory is the resolution: drop a `<feature_slug>.md` file here with the current-state one-liner. The generator looks here first, falls back to the spec.

## Conventions

- **Filename:** `<feature_slug>.md`, where `<feature_slug>` is the implemented-feature folder name **without** the `<YYYY_MM_DD>_` date prefix. E.g., for `docs/00_overview/implemented_features/2026_05_10_infra_optuna_eval/`, the override file is `infra_optuna_eval.md`.
- **Contents:** one plain-text or markdown line. Anything past the first sentence (the generator splits on `. ` / `! ` / `? `) is dropped from the dashboard cell.
- **Voice:** current-state. Don't describe history — that's what `state.md` is for.
- **No back-references to the migration that triggered the override.** Future readers shouldn't have to know which feature created the override.

## Adding an override

1. Identify the implemented feature whose row is stale.
2. Write a one-line current-state description.
3. Save as `<feature_slug>.md` in this directory.
4. Run `python scripts/build_mvp1_dashboard.py` and verify the row in `docs/00_overview/MVP1_DASHBOARD.md` picks up the new text.
5. Commit both the override file AND the regenerated dashboard.

## Existing overrides

See the directory listing. Each override file's commit-time history explains which subsequent feature invalidated the original row.
