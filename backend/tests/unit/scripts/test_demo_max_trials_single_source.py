# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Pin the demo small-scenario ``max_trials`` budget to a single source-of-truth.

Lands with ``feat_studies_convergence_visibility`` Epic 2 Story 2.2 / FR-6 /
D-11. Both the CLI ``make seed-demo`` path (``scripts/seed_meaningful_demos.py``)
and the home-button reseed path (``backend.app.services.demo_seeding``) MUST
dispatch small-scenario studies with the same trial budget — otherwise the
two demo entry points would silently drift and the FR-6 promise (the verdict
can read ``converged`` / ``still_improving`` rather than ``too_few_trials``)
would hold for one path and fail for the other.

The plan adds the shared constant ``DEMO_SMALL_STUDY_MAX_TRIALS`` at the top
of ``scripts/seed_meaningful_demos.py``, imported by ``demo_seeding`` to
populate ``_REAL_STUDY_MAX_TRIALS``. These assertions are belt-and-suspenders
on top of the import wiring: a future refactor that re-introduces a literal
``12`` or a hard-coded ``50`` in either path fails this test loudly instead
of producing a silent skew between ``make seed-demo`` and the reseed button.

The rich-scenario constant (``_RICH_SCENARIO_MAX_TRIALS = 15``) is **out of
scope** for this guard — the rich ESCI scenario already shows real lift at 15
trials per D-9 / state.md, and its budget intentionally differs from the
small-scenario one.
"""

from __future__ import annotations

from backend.app.services.demo_seeding import (
    _REAL_STUDY_MAX_TRIALS,
    _RICH_SCENARIO_MAX_TRIALS,
)
from scripts.seed_meaningful_demos import DEMO_SMALL_STUDY_MAX_TRIALS


def test_small_scenario_max_trials_is_at_warmup_floor() -> None:
    """``DEMO_SMALL_STUDY_MAX_TRIALS`` must equal the convergence warmup floor (50).

    FR-6 / D-11: the floor is non-negotiable for AC-8 (the convergence verdict
    can only read ``converged`` / ``still_improving`` when complete trials are
    at or above ``STUDIES_TPE_WARMUP_FLOOR``). A lower value silently regresses
    every small-scenario LLM + UBI study back to ``too_few_trials`` — the
    exact degenerate state Story 2.2 is designed to fix.

    Source of the warmup floor: ``backend.app.eval.optuna_runtime`` — read
    from that canonical module rather than the re-export in
    ``convergence.py`` (which only conditionally re-exports the symbol via
    its ``__all__``).
    """
    from backend.app.eval.optuna_runtime import STUDIES_TPE_WARMUP_FLOOR

    assert DEMO_SMALL_STUDY_MAX_TRIALS == STUDIES_TPE_WARMUP_FLOOR == 50, (
        f"small-scenario max_trials drifted from warmup floor — "
        f"DEMO_SMALL_STUDY_MAX_TRIALS={DEMO_SMALL_STUDY_MAX_TRIALS}, "
        f"STUDIES_TPE_WARMUP_FLOOR={STUDIES_TPE_WARMUP_FLOOR}"
    )


def test_real_study_max_trials_imports_the_shared_constant() -> None:
    """``_REAL_STUDY_MAX_TRIALS`` must alias the shared constant, NOT a fresh literal.

    Asserts the IMPORT wiring via source inspection — a future maintainer
    who re-introduces ``_REAL_STUDY_MAX_TRIALS: Final[int] = 50`` as a
    literal would still satisfy ``==``, AND would still satisfy ``is`` for
    the value ``50`` because CPython interns small ints (GPT-5.5 cycle-1
    F5 — the original ``is`` check was unreliable for this purpose).
    Inspecting the source for the canonical alias-binding form is the
    only reliable single-source-of-truth enforcement.
    """
    import inspect

    import backend.app.services.demo_seeding as demo_seeding

    source = inspect.getsource(demo_seeding)
    canonical_binding = "_REAL_STUDY_MAX_TRIALS: Final[int] = DEMO_SMALL_STUDY_MAX_TRIALS"
    assert canonical_binding in source, (
        f"expected demo_seeding.py to bind _REAL_STUDY_MAX_TRIALS to the "
        f"imported DEMO_SMALL_STUDY_MAX_TRIALS constant; missing form: "
        f"{canonical_binding!r}. Re-introducing a literal int (e.g. "
        f"'_REAL_STUDY_MAX_TRIALS: Final[int] = 50') defeats Story 2.2's "
        f"single-source discipline — the CLI and home-button reseed paths "
        f"could then silently drift."
    )
    # Defense-in-depth: even with the source check, the runtime values must
    # match. A type-check error or a future refactor that renames the
    # constant would surface here.
    assert _REAL_STUDY_MAX_TRIALS == DEMO_SMALL_STUDY_MAX_TRIALS, (
        f"_REAL_STUDY_MAX_TRIALS={_REAL_STUDY_MAX_TRIALS} != "
        f"DEMO_SMALL_STUDY_MAX_TRIALS={DEMO_SMALL_STUDY_MAX_TRIALS}"
    )


def test_rich_scenario_budget_unchanged() -> None:
    """The rich ESCI scenario's per-study budget stays at 15 trials.

    D-11 / FR-6 explicitly scope the trial-budget bump to the SMALL scenarios
    only. Raising the rich-scenario budget would materially extend
    ``make seed-demo`` wall-clock without changing the convergence-badge
    demo value (the rich scenario already shows real lift at 15 trials).
    """
    assert _RICH_SCENARIO_MAX_TRIALS == 15, (
        f"rich-scenario max_trials must stay at 15 — "
        f"current value {_RICH_SCENARIO_MAX_TRIALS} violates D-11"
    )


def test_cli_seed_dispatches_shared_constant() -> None:
    """The CLI ``make seed-demo`` path must build the study config from the shared constant.

    Reads the ``_create_one_study`` source and asserts the literal ``12`` no
    longer appears in the study config block, and that the
    ``DEMO_SMALL_STUDY_MAX_TRIALS`` symbol is referenced in the config
    construction site. Catches the "I edited demo_seeding but forgot the CLI
    side" regression that the import wiring alone can't detect (the CLI
    builds the dict from a literal, not from an import).

    The check is scoped to the ``"max_trials":`` line inside the config dict
    rather than a whole-file grep so unrelated occurrences of ``12`` (e.g.
    inside doc strings, sample IDs, judgments) don't false-positive.
    """
    import inspect

    import scripts.seed_meaningful_demos as cli

    source = inspect.getsource(cli)
    config_block_token = '"max_trials": DEMO_SMALL_STUDY_MAX_TRIALS,'
    assert config_block_token in source, (
        f"expected CLI study config to reference DEMO_SMALL_STUDY_MAX_TRIALS; "
        f"missing token: {config_block_token!r}. The CLI seed path must use "
        f"the shared constant — a re-introduced literal int defeats Story 2.2."
    )
    # The literal 12 must not reappear inside the small-scenario study config.
    # We bound the check to the exact line shape so a stray "12" elsewhere in
    # the file (counts, IDs, doc bodies) doesn't false-positive.
    assert '"max_trials": 12,' not in source, (
        'CLI study config must not re-introduce the literal "max_trials": 12. '
        "Use DEMO_SMALL_STUDY_MAX_TRIALS instead."
    )
