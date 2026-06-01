# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend.app.domain.study.convergence`` (Story 1.2).

Pure tests over a SimpleNamespace stand-in for Trial ORM rows (same
fixture style as ``test_auto_followup.py`` / ``test_confidence.py``).
The classifier has no DB or I/O surface, so fixtures stay minimal.

Coverage map (matches spec §14 + plan Story 1.2 Tasks 3-5):

- Decision-matrix branches: converged / still_improving / too_few_trials / None
- Direction-aware minimize
- ``is_baseline=True`` filtering (mixed seed with sentinel trial_number=-1)
- ``primary_metric IS NULL`` defensive filter
- Window-clamp boundary cases at N in {5, 7, 24, 49, 50, 51, 100, 200, 1000}
- Slow-drift (200 trials, gain<epsilon per window → ``converged``)
- Single-late-jump (200 flat + 1 trial gaining 0.05 → ``still_improving``)
- Noisy-tail (100 baseline + 20 noisy near a fixed best → ``converged``)
- Monotonicity invariant of ``best_so_far_curve`` in both directions
- Value-lock: ``CONVERGENCE_FLAT_EPSILON == AUTO_FOLLOWUP_LIFT_EPSILON == 0.005``
- AST/grep guard: zero stray ``0.005`` literals under ``backend/app/``
  outside the single canonical declaration line
- Determinism property: 100 invocations on the same input return equal outputs
- ``ConvergenceVerdict`` Literal membership (also feeds Story 6.1 import test)
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from backend.app.domain.study.auto_followup import AUTO_FOLLOWUP_LIFT_EPSILON
from backend.app.domain.study.convergence import (
    CONVERGENCE_FLAT_EPSILON,
    CONVERGENCE_FLAT_MIN_COMPLETE,
    CONVERGENCE_FLAT_WINDOW,
    ConvergenceVerdict,
    CurvePoint,
    classify_convergence,
)
from backend.app.eval.optuna_runtime import STUDIES_TPE_WARMUP_FLOOR

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _trial(
    *,
    num: int,
    metric: float | None,
    status: str = "complete",
    is_baseline: bool = False,
) -> SimpleNamespace:
    """Build a Trial stand-in. Only the four classifier-visible fields
    matter — status, is_baseline, primary_metric, optuna_trial_number."""
    return SimpleNamespace(
        optuna_trial_number=num,
        primary_metric=metric,
        status=status,
        is_baseline=is_baseline,
    )


def _converged_seed(n: int) -> list[SimpleNamespace]:
    """N trials whose primary_metric plateaus after the first ~30%, so the
    trailing window-flat check sees ``improvement <= epsilon``. Useful for
    the ``converged`` happy path."""
    seed: list[SimpleNamespace] = []
    for i in range(n):
        # Climb 0.0..0.5 over first 30% of trials, plateau at 0.5 thereafter.
        if i < n * 0.3:
            metric = 0.5 * (i / (n * 0.3))
        else:
            metric = 0.5
        seed.append(_trial(num=i, metric=metric))
    return seed


def _still_improving_seed(n: int) -> list[SimpleNamespace]:
    """N trials whose metric improves monotonically across the entire run
    by ``>> epsilon`` per window — the classifier should flag
    ``still_improving``."""
    return [_trial(num=i, metric=0.5 + 0.001 * i) for i in range(n)]


# ---------------------------------------------------------------------------
# Sub-MIN-trials → None
# ---------------------------------------------------------------------------


class TestSubMinTrialsReturnsNone:
    @pytest.mark.parametrize("n", [0, 1, 2, 3, 4])
    def test_below_floor_returns_none(self, n: int) -> None:
        trials = [_trial(num=i, metric=0.5) for i in range(n)]
        assert classify_convergence(trials, direction="maximize") is None

    def test_exactly_min_complete_returns_shape(self) -> None:
        trials = [_trial(num=i, metric=0.5) for i in range(CONVERGENCE_FLAT_MIN_COMPLETE)]
        shape = classify_convergence(trials, direction="maximize")
        assert shape is not None
        assert shape.total_complete_trials == CONVERGENCE_FLAT_MIN_COMPLETE


# ---------------------------------------------------------------------------
# Decision matrix branches
# ---------------------------------------------------------------------------


class TestDecisionMatrix:
    def test_too_few_trials_when_below_warmup_floor(self) -> None:
        # 30 flat trials, total well below the warmup floor (50). Even
        # though the tail looks flat, the warmup-floor check fires first.
        trials = [_trial(num=i, metric=0.5) for i in range(30)]
        shape = classify_convergence(trials, direction="maximize")
        assert shape is not None
        assert shape.verdict == "too_few_trials"

    def test_converged_when_window_improvement_below_epsilon(self) -> None:
        shape = classify_convergence(_converged_seed(200), direction="maximize")
        assert shape is not None
        assert shape.verdict == "converged"
        assert shape.improvement_in_window <= CONVERGENCE_FLAT_EPSILON

    def test_still_improving_when_window_improvement_above_epsilon(self) -> None:
        # 100 trials with monotonic gain of 0.001 per trial → window gain
        # over 20 trials = 0.02 > 0.005 epsilon.
        shape = classify_convergence(_still_improving_seed(100), direction="maximize")
        assert shape is not None
        assert shape.verdict == "still_improving"
        assert shape.improvement_in_window > CONVERGENCE_FLAT_EPSILON


# ---------------------------------------------------------------------------
# Minimize direction
# ---------------------------------------------------------------------------


class TestMinimizeDirection:
    def test_minimize_converged_with_decreasing_metric(self) -> None:
        # 200 trials where the metric descends 1.0 -> 0.5 over first 30%,
        # then plateaus at 0.5. For minimize, the best-so-far running-min
        # mirrors that shape.
        seed: list[SimpleNamespace] = []
        for i in range(200):
            if i < 60:
                metric = 1.0 - 0.5 * (i / 60)
            else:
                metric = 0.5
            seed.append(_trial(num=i, metric=metric))
        shape = classify_convergence(seed, direction="minimize")
        assert shape is not None
        assert shape.verdict == "converged"
        assert shape.direction == "minimize"
        # Curve must be monotonic non-increasing for minimize.
        values = [p.best_so_far for p in shape.best_so_far_curve]
        assert all(v_prev >= v_curr for v_prev, v_curr in itertools.pairwise(values))

    def test_minimize_still_improving_with_persistent_descent(self) -> None:
        # 100 trials, metric drops linearly across the entire run; for
        # minimize the running-min keeps falling fast enough that the
        # window gain (sign-flipped improvement) stays well above epsilon.
        seed = [_trial(num=i, metric=1.0 - 0.005 * i) for i in range(100)]
        shape = classify_convergence(seed, direction="minimize")
        assert shape is not None
        assert shape.verdict == "still_improving"
        assert shape.improvement_in_window > CONVERGENCE_FLAT_EPSILON


# ---------------------------------------------------------------------------
# Filter: is_baseline + primary_metric=None
# ---------------------------------------------------------------------------


class TestFilteringInvariants:
    def test_baseline_trials_are_excluded_from_curve(self) -> None:
        # 50 Optuna trials at metric=0.5, plus 1 baseline at trial_number=-1
        # with a wildly different metric. The classifier must exclude the
        # baseline sentinel from both the count AND the curve.
        seed = [_trial(num=i, metric=0.5) for i in range(50)]
        seed.append(_trial(num=-1, metric=99.0, is_baseline=True))
        shape = classify_convergence(seed, direction="maximize")
        assert shape is not None
        assert shape.total_complete_trials == 50
        # No CurvePoint should reference the baseline sentinel.
        assert all(p.trial_number != -1 for p in shape.best_so_far_curve)

    def test_null_primary_metric_rows_are_excluded(self) -> None:
        # 50 usable trials plus 5 rows whose primary_metric is None. Those
        # 5 must be filtered out — otherwise float(None) would raise.
        seed = [_trial(num=i, metric=0.5) for i in range(50)]
        seed.extend(_trial(num=100 + i, metric=None) for i in range(5))
        shape = classify_convergence(seed, direction="maximize")
        assert shape is not None
        assert shape.total_complete_trials == 50

    def test_non_complete_status_rows_are_excluded(self) -> None:
        seed = [_trial(num=i, metric=0.5) for i in range(50)]
        seed.extend(_trial(num=100 + i, metric=0.7, status="failed") for i in range(3))
        seed.extend(_trial(num=200 + i, metric=0.6, status="pruned") for i in range(3))
        shape = classify_convergence(seed, direction="maximize")
        assert shape is not None
        assert shape.total_complete_trials == 50

    def test_none_is_baseline_treated_as_non_baseline(self) -> None:
        # Gemini PR #352 regression: a trial-like object whose nullable
        # is_baseline is None must be INCLUDED (treated as non-baseline),
        # not silently dropped. The old ``is False`` check excluded these
        # because ``None is False`` evaluates to False; ``not None`` is True.
        seed = [_trial(num=i, metric=0.5, is_baseline=None) for i in range(50)]  # type: ignore[arg-type]
        shape = classify_convergence(seed, direction="maximize")
        assert shape is not None
        assert shape.total_complete_trials == 50
        # All 50 rows made it into the curve.
        assert len(shape.best_so_far_curve) == 50


# ---------------------------------------------------------------------------
# Window-clamp boundary cases (plan Story 1.2 Task 3, list of N values)
# ---------------------------------------------------------------------------


class TestWindowClampBoundaries:
    @pytest.mark.parametrize("n", [5, 7, 24, 49, 50, 51, 100, 200, 1000])
    def test_window_size_clamps_correctly(self, n: int) -> None:
        # window_size = min(CONVERGENCE_FLAT_WINDOW, max(5, n // 5))
        expected_window = min(CONVERGENCE_FLAT_WINDOW, max(5, n // 5))
        shape = classify_convergence(_converged_seed(n), direction="maximize")
        assert shape is not None
        assert shape.window_size == expected_window
        # The window-end indexing requires window_size <= total — assert it
        # never overshoots.
        assert shape.window_size <= shape.total_complete_trials
        assert shape.window_size >= 5


# ---------------------------------------------------------------------------
# Specific behavior cases from plan Tasks 3
# ---------------------------------------------------------------------------


class TestPathologicalShapes:
    def test_slow_drift_below_epsilon_flags_converged(self) -> None:
        # 200 trials, the curve gains 0.004 per window-step (under epsilon
        # of 0.005). Should classify as ``converged``.
        # Build a metric series whose 20-trial window-gain is just under
        # epsilon: metric increases by 0.004/20 = 0.0002 per trial.
        seed = [_trial(num=i, metric=0.5 + 0.0002 * i) for i in range(200)]
        shape = classify_convergence(seed, direction="maximize")
        assert shape is not None
        # Window of 20 trials → gain = 0.0002 * 19 = 0.0038 < 0.005.
        assert shape.improvement_in_window < CONVERGENCE_FLAT_EPSILON
        assert shape.verdict == "converged"

    def test_single_late_jump_flags_still_improving(self) -> None:
        # 200 flat trials at metric=0.5, then 1 trial at metric=0.55. The
        # late jump of 0.05 well exceeds epsilon, so the verdict is
        # ``still_improving``. Total = 201 ≥ warmup floor.
        seed = [_trial(num=i, metric=0.5) for i in range(200)]
        seed.append(_trial(num=200, metric=0.55))
        shape = classify_convergence(seed, direction="maximize")
        assert shape is not None
        assert shape.improvement_in_window == pytest.approx(0.05, abs=1e-9)
        assert shape.verdict == "still_improving"

    def test_noisy_tail_near_fixed_best_flags_converged(self) -> None:
        # 100 trials climbing to best=0.8, then 20 noisy trials oscillating
        # *below* 0.8 (so best-so-far stays at 0.8 — no new high). Total
        # 120 trials, window-end == window-start == 0.8, improvement == 0.
        seed: list[SimpleNamespace] = []
        for i in range(100):
            seed.append(_trial(num=i, metric=0.5 + 0.003 * i))
        # 20 noisy trials, none beats 0.8.
        for i in range(20):
            seed.append(_trial(num=100 + i, metric=0.78 + 0.01 * ((i % 3) - 1)))
        shape = classify_convergence(seed, direction="maximize")
        assert shape is not None
        assert shape.improvement_in_window == pytest.approx(0.0, abs=1e-9)
        assert shape.verdict == "converged"


# ---------------------------------------------------------------------------
# Monotonicity invariant
# ---------------------------------------------------------------------------


class TestMonotonicityInvariant:
    def test_maximize_curve_is_non_decreasing(self) -> None:
        # Mix of climbing + descending + plateauing trials. Best-so-far
        # under maximize must never decrease.
        import random

        rng = random.Random(0)
        seed = [_trial(num=i, metric=rng.uniform(0.0, 1.0)) for i in range(100)]
        shape = classify_convergence(seed, direction="maximize")
        assert shape is not None
        values = [p.best_so_far for p in shape.best_so_far_curve]
        assert all(v_prev <= v_curr for v_prev, v_curr in itertools.pairwise(values))

    def test_minimize_curve_is_non_increasing(self) -> None:
        import random

        rng = random.Random(0)
        seed = [_trial(num=i, metric=rng.uniform(0.0, 1.0)) for i in range(100)]
        shape = classify_convergence(seed, direction="minimize")
        assert shape is not None
        values = [p.best_so_far for p in shape.best_so_far_curve]
        assert all(v_prev >= v_curr for v_prev, v_curr in itertools.pairwise(values))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_yields_equal_output_100x(self) -> None:
        seed = _converged_seed(100)
        baseline = classify_convergence(seed, direction="maximize")
        assert baseline is not None
        for _ in range(100):
            other = classify_convergence(seed, direction="maximize")
            assert other is not None
            assert other.model_dump() == baseline.model_dump()


# ---------------------------------------------------------------------------
# Value-lock + Literal membership
# ---------------------------------------------------------------------------


class TestEpsilonValueLock:
    """Cross-module value-lock per spec FR-2 / AC-17 (uses ``==`` per D-6)."""

    def test_convergence_epsilon_matches_auto_followup_constant(self) -> None:
        assert CONVERGENCE_FLAT_EPSILON == AUTO_FOLLOWUP_LIFT_EPSILON

    def test_both_epsilons_equal_canonical_value(self) -> None:
        assert AUTO_FOLLOWUP_LIFT_EPSILON == 0.005
        assert CONVERGENCE_FLAT_EPSILON == 0.005

    def test_emitted_shape_epsilon_field_matches_constant(self) -> None:
        shape = classify_convergence(_converged_seed(100), direction="maximize")
        assert shape is not None
        assert shape.epsilon == CONVERGENCE_FLAT_EPSILON

    def test_warmup_floor_field_matches_constant(self) -> None:
        shape = classify_convergence(_converged_seed(100), direction="maximize")
        assert shape is not None
        assert shape.warmup_floor == STUDIES_TPE_WARMUP_FLOOR


class TestConvergenceVerdictLiteral:
    """Story 6.1's autopilot soft-contract test piggy-backs on this — the
    autopilot PR imports ``ConvergenceVerdict`` from this module and asserts
    the same Literal membership in its own CI lane."""

    def test_literal_members_are_exactly_the_three_verdicts(self) -> None:
        assert get_args(ConvergenceVerdict) == (
            "converged",
            "still_improving",
            "too_few_trials",
        )

    def test_convergence_verdict_is_importable_from_module(self) -> None:
        # Symbol-import smoke test — covers Story 6.1's "verify export"
        # task without depending on Story 6.1's own test file.
        from backend.app.domain.study.convergence import (  # noqa: PLC0415
            ConvergenceVerdict as Reimported,
        )

        assert Reimported is ConvergenceVerdict


# ---------------------------------------------------------------------------
# AST/grep guard: zero stray bare 0.005 literals under backend/app/
# ---------------------------------------------------------------------------


def _backend_app_root() -> Path:
    """Resolve ``backend/app`` from the test file location, walking up to
    the repo root and then descending. Robust to working-directory drift
    in CI / pre-commit / sibling-worktree runs."""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "backend" / "app"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("Could not locate backend/app/ relative to test file")


_LIFT_EPSILON_KEYWORDS = ("lift", "epsilon", "improvement")


def _is_lift_epsilon_context(node: ast.AST, parent: ast.AST | None) -> bool:
    """Return True iff a bare ``0.005`` float literal occurs in a context
    that resembles a lift/convergence epsilon — i.e., it's the default of
    a kwarg/field named like one, or it's compared (==) against such a
    name. Plain numeric usages elsewhere (timing constants, ratios, etc.)
    don't trip the guard."""
    if not isinstance(node, ast.Constant) or node.value != 0.005:
        return False
    # AnnAssign / Assign / dataclass-field default → check the LHS name.
    if isinstance(parent, ast.AnnAssign) and isinstance(parent.target, ast.Name):
        name = parent.target.id.lower()
        return any(kw in name for kw in _LIFT_EPSILON_KEYWORDS)
    if (
        isinstance(parent, ast.Assign)
        and parent.targets
        and isinstance(parent.targets[0], ast.Name)
    ):
        name = parent.targets[0].id.lower()
        return any(kw in name for kw in _LIFT_EPSILON_KEYWORDS)
    # Function kwarg default: parent is the function def, check whether
    # *any* kwarg default at this node maps to a kwarg name with the
    # keyword.  Handled by the dedicated walker below.
    return False


class TestNoStrayLiftEpsilonLiterals:
    """AST/grep guard (spec FR-2 / D-6): scan every ``*.py`` under
    ``backend/app/`` and fail if any module other than the canonical
    declaration line in ``auto_followup.py`` contains a bare ``0.005``
    literal in a lift/epsilon-shaped context. Prevents future re-inlining
    drift after the Story 1.1 hoist.

    The ``auto_followup.py`` declaration line (``AUTO_FOLLOWUP_LIFT_EPSILON
    = 0.005``) is the single allowed site. Everything else must reference
    the named constant.
    """

    def test_zero_stray_literals_under_backend_app(self) -> None:
        backend_app = _backend_app_root()
        canonical = backend_app / "domain" / "study" / "auto_followup.py"
        assert canonical.is_file(), "Canonical declaration site must exist"

        offenders: list[str] = []

        for path in sorted(backend_app.rglob("*.py")):
            try:
                source = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                # Module-level annotated assignment: ``NAME: float = 0.005``.
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    value = node.value
                    if (
                        isinstance(value, ast.Constant)
                        and value.value == 0.005
                        and any(kw in node.target.id.lower() for kw in _LIFT_EPSILON_KEYWORDS)
                    ):
                        if path == canonical and node.target.id == "AUTO_FOLLOWUP_LIFT_EPSILON":
                            continue
                        offenders.append(
                            f"{path}:{node.lineno} — module-level {node.target.id} = 0.005"
                        )
                # Plain assignment.
                if isinstance(node, ast.Assign):
                    value = node.value
                    if isinstance(value, ast.Constant) and value.value == 0.005:
                        for tgt in node.targets:
                            if isinstance(tgt, ast.Name) and any(
                                kw in tgt.id.lower() for kw in _LIFT_EPSILON_KEYWORDS
                            ):
                                offenders.append(f"{path}:{node.lineno} — assign {tgt.id} = 0.005")
                # Function definition: scan kwargs for ``epsilon`` /
                # ``lift_threshold`` / etc. with default 0.005.
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = node.args
                    # Map kwarg defaults to their kwarg names.
                    kwonly_defaults = list(args.kw_defaults)
                    for arg, default in zip(args.kwonlyargs, kwonly_defaults, strict=True):
                        if (
                            isinstance(default, ast.Constant)
                            and default.value == 0.005
                            and any(kw in arg.arg.lower() for kw in _LIFT_EPSILON_KEYWORDS)
                        ):
                            offenders.append(
                                f"{path}:{node.lineno} — {node.name}(*, {arg.arg}=0.005)"
                            )
                    # Positional defaults (less common, but possible).
                    positional = args.args
                    positional_defaults = args.defaults
                    pad = [None] * (len(positional) - len(positional_defaults))
                    for arg, default in zip(
                        positional, pad + list(positional_defaults), strict=True
                    ):
                        if default is None:
                            continue
                        if (
                            isinstance(default, ast.Constant)
                            and default.value == 0.005
                            and any(kw in arg.arg.lower() for kw in _LIFT_EPSILON_KEYWORDS)
                        ):
                            offenders.append(f"{path}:{node.lineno} — {node.name}({arg.arg}=0.005)")

        assert offenders == [], (
            "Stray 0.005 lift/epsilon literal(s) found outside the canonical "
            "AUTO_FOLLOWUP_LIFT_EPSILON declaration:\n  " + "\n  ".join(offenders)
        )


# ---------------------------------------------------------------------------
# Shape sanity (sub-fields, types)
# ---------------------------------------------------------------------------


class TestShapeContract:
    def test_shape_contains_all_required_subfields(self) -> None:
        shape = classify_convergence(_converged_seed(100), direction="maximize")
        assert shape is not None
        # Every field set, no None leak.
        assert shape.verdict in get_args(ConvergenceVerdict)
        assert shape.direction in ("maximize", "minimize")
        assert isinstance(shape.window_size, int)
        assert isinstance(shape.epsilon, float)
        assert isinstance(shape.warmup_floor, int)
        assert isinstance(shape.total_complete_trials, int)
        assert isinstance(shape.improvement_in_window, float)
        assert isinstance(shape.best_so_far_curve, list)
        assert len(shape.best_so_far_curve) == shape.total_complete_trials
        for point in shape.best_so_far_curve:
            assert isinstance(point, CurvePoint)
            assert isinstance(point.trial_number, int)
            assert isinstance(point.best_so_far, float)

    def test_unsorted_input_is_sorted_by_optuna_trial_number(self) -> None:
        # Same trials, scrambled order. Classifier must sort.
        import random

        seed = _converged_seed(100)
        scrambled = list(seed)
        rng = random.Random(0)
        rng.shuffle(scrambled)
        shape = classify_convergence(scrambled, direction="maximize")
        assert shape is not None
        trial_numbers = [p.trial_number for p in shape.best_so_far_curve]
        assert trial_numbers == sorted(trial_numbers)


# ---------------------------------------------------------------------------
# Test-discovery sanity: unused symbol import guards
# ---------------------------------------------------------------------------


def test_all_classes_have_at_least_one_test() -> None:
    # Defensive: surface accidental no-op test classes in this file. Each
    # ``Test*`` class must define at least one method named ``test_*``.
    import inspect

    module = inspect.getmodule(test_all_classes_have_at_least_one_test)
    assert module is not None
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if not name.startswith("Test"):
            continue
        if obj.__module__ != module.__name__:
            continue
        methods = [m for m in dir(obj) if m.startswith("test_")]
        assert methods, f"{name} has no test_* methods"


# Quiet ruff F401 if pytest is unused on a build where the parametrize
# decorator path isn't hit — pytest is always imported because we use it.
_PYTEST_SENTINEL = pytest

# Reference the typing helper so static linters don't drop the import on
# a future trim of the test classes.
_ANY_SENTINEL = Any
