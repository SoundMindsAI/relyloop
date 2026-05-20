"""``studies.search_space`` schema + Optuna sampler mapping (Story 1.1).

Pure-domain helpers (no I/O, no async, no DB). Used at two sites:

1. ``POST /api/v1/studies`` (Story 3.3 router) validates the operator-
   supplied ``search_space`` JSON via :func:`SearchSpace.model_validate`
   at create time. Malformed inputs surface as
   :exc:`pydantic.ValidationError`; the router translates to HTTP 400
   ``INVALID_SEARCH_SPACE`` per spec §7.5.
2. The orchestrator (``backend/workers/orchestrator.py``,
   Story 2.1) wraps :func:`apply_search_space` in
   ``asyncio.to_thread`` to call ``trial.suggest_*`` for every declared
   parameter BEFORE enqueueing ``run_trial`` — preserves
   ``infra_optuna_eval`` worker contract (spec §11) which requires the
   in-flight ``FrozenTrial.params`` to be populated by the orchestrator
   side, not the worker side.

Cardinality cap (10⁶) is the spec §10 Threat 1 mitigation: a runaway
search space (e.g. 10 floats × 10 ints) would queue more trial
combinations than any reasonable budget could complete.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import optuna
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FloatParam(BaseModel):
    """Continuous float parameter.

    ``log=True`` enables log-uniform sampling
    (Optuna's ``suggest_float(..., log=True)``); requires ``low > 0``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["float"]
    low: float
    high: float
    log: bool = False

    @model_validator(mode="after")
    def _check_bounds(self) -> FloatParam:
        if self.low >= self.high:
            raise ValueError(f"float param: low ({self.low}) must be < high ({self.high})")
        if self.log and self.low <= 0:
            raise ValueError(f"log-uniform float param: low must be > 0 (got {self.low})")
        return self


class IntParam(BaseModel):
    """Integer parameter inclusive of both bounds."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["int"]
    low: int
    high: int

    @model_validator(mode="after")
    def _check_bounds(self) -> IntParam:
        if self.low > self.high:
            raise ValueError(f"int param: low ({self.low}) must be <= high ({self.high})")
        return self


class CategoricalParam(BaseModel):
    """Discrete choice parameter.

    Optuna ``suggest_categorical`` handles strings, ints, floats, and bools
    as choices.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["categorical"]
    choices: Annotated[list[str | int | float | bool], Field(min_length=1)]


ParamSpec = Annotated[
    FloatParam | IntParam | CategoricalParam,
    Field(discriminator="type"),
]
"""Discriminated union over the three supported parameter kinds. Pydantic v2
selects the concrete model based on the ``type`` field — malformed inputs
(e.g. ``type='cma_es'``) raise during ``model_validate``."""


class SearchSpace(BaseModel):
    """Pydantic model for the ``studies.search_space`` JSONB column.

    Wire format::

        {
            "params": {
                "boost_title": {"type": "float", "low": 0.1, "high": 10.0, "log": true},
                "min_should_match": {"type": "int", "low": 1, "high": 5},
                "operator": {"type": "categorical", "choices": ["and", "or"]},
            }
        }
    """

    model_config = ConfigDict(extra="forbid")

    params: dict[str, ParamSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_cardinality(self) -> SearchSpace:
        size = estimate_cardinality(self)
        if size > 1_000_000:
            raise ValueError(
                f"search-space cardinality estimate exceeds 10^6 (got "
                f"{size}); pick narrower ranges or smaller categorical sets"
            )
        return self


class InvalidSearchSpaceError(ValueError):
    """Raised when validation fails outside the Pydantic boundary.

    Pydantic itself raises ``ValidationError`` from ``model_validate``;
    callers translate that to HTTP 400 ``INVALID_SEARCH_SPACE`` at the
    router boundary. This subclass is reserved for non-Pydantic failure
    paths (none in MVP1 — kept for forward compatibility with the
    multi-objective spec at MVP2+).
    """


class UnknownSearchSpaceParamError(ValueError):
    """A search_space.params key is not declared by the selected template.

    Message format (chore_create_study_wizard_polish spec FR-2)::

        Param '{name}' is not declared by template '{template_name}'. \
Declared params: {sorted_declared_names}.

    Translated to HTTP 400 ``SEARCH_SPACE_UNKNOWN_PARAM`` at the router boundary.
    """

    def __init__(
        self,
        param_name: str,
        template_name: str,
        declared_param_names: list[str],
    ) -> None:
        """Format the spec-exact message and pass it through to ``ValueError``."""
        msg = (
            f"Param '{param_name}' is not declared by template "
            f"'{template_name}'. Declared params: {sorted(declared_param_names)}."
        )
        super().__init__(msg)


class MissingDeclaredParamError(ValueError):
    """A declared_params key is missing from the submitted search_space.params.

    Message format (chore_create_study_wizard_polish spec FR-3):
      "Template '{template_name}' declares param '{name}' but it is missing from
      the search space. Add it or remove from the template."

    Translated to HTTP 400 ``SEARCH_SPACE_MISSING_DECLARED_PARAM`` at the router
    boundary.
    """

    def __init__(self, param_name: str, template_name: str) -> None:
        """Format the spec-exact message and pass it through to ``ValueError``."""
        msg = (
            f"Template '{template_name}' declares param '{param_name}' but it "
            f"is missing from the search space. Add it or remove from the template."
        )
        super().__init__(msg)


def estimate_cardinality(space: SearchSpace) -> int:
    """Estimate the combinatorial size of the search space.

    Floats counted as 100 (a reasonable per-param sampling resolution
    that distinguishes "boost from 0.1 to 10.0" from "boost from 0.1
    to 1000.0"). Ints counted as ``high - low + 1``. Categoricals counted
    as ``len(choices)``. Product across all params.

    Returns at least 1 (an empty space would have been rejected by
    Pydantic's ``min_length=1`` on ``params``).
    """
    total = 1
    for spec in space.params.values():
        if isinstance(spec, FloatParam):
            total *= 100
        elif isinstance(spec, IntParam):
            total *= spec.high - spec.low + 1
        elif isinstance(spec, CategoricalParam):
            total *= len(spec.choices)
    return total


def validate_against_template(
    search_space: SearchSpace,
    declared_params: dict[str, str],
    template_name: str,
) -> None:
    """Verify ``search_space.params`` keys match ``declared_params`` exactly.

    Ordering when both conditions apply (chore_create_study_wizard_polish spec AC-7):

      1. Unknown-param raised first, on the lexicographically smallest offender.
      2. Missing-declared-param raised only when no unknown params remain.

    The ``template_name`` argument is required for the exception's message format
    to match the spec's exact text (FR-2 / FR-3 / AC-5 / AC-6). Pure domain
    function — no I/O, no DB, no async.

    Args:
        search_space: parsed ``SearchSpace`` (already validated by Pydantic).
        declared_params: the template's ``declared_params`` dict, mapping
            param name to type-name string (``"int"`` / ``"float"`` / ``"bool"``
            / ``"string"``). Only the keys matter here; values are ignored.
        template_name: human-readable template name for the error message.

    Raises:
        UnknownSearchSpaceParamError: a search_space key is not in declared_params.
        MissingDeclaredParamError: a declared_params key is not in search_space.
    """
    declared_names = set(declared_params)
    submitted_names = set(search_space.params)

    unknown = sorted(submitted_names - declared_names)
    if unknown:
        raise UnknownSearchSpaceParamError(
            param_name=unknown[0],
            template_name=template_name,
            declared_param_names=list(declared_names),
        )

    missing = sorted(declared_names - submitted_names)
    if missing:
        raise MissingDeclaredParamError(
            param_name=missing[0],
            template_name=template_name,
        )


def apply_search_space(trial: optuna.Trial, space: SearchSpace) -> dict[str, Any]:
    """Call ``trial.suggest_*`` for every parameter; return the suggested values.

    Invoked by the orchestrator (``backend/workers/orchestrator.py``,
    Story 2.1) inside ``asyncio.to_thread`` BEFORE enqueueing
    ``run_trial(study_id, trial.number)``. The worker reads the populated
    ``FrozenTrial.params`` from Optuna's RDB; this function is therefore
    the single place that drives Optuna's sampler suggestion semantics.

    Returns the dict of ``{param_name: suggested_value}`` for logging /
    test assertions; the canonical source of truth is Optuna's internal
    trial state once this returns.
    """
    suggested: dict[str, Any] = {}
    for name, spec in space.params.items():
        if isinstance(spec, FloatParam):
            suggested[name] = trial.suggest_float(name, spec.low, spec.high, log=spec.log)
        elif isinstance(spec, IntParam):
            suggested[name] = trial.suggest_int(name, spec.low, spec.high)
        elif isinstance(spec, CategoricalParam):
            suggested[name] = trial.suggest_categorical(name, list(spec.choices))
    return suggested
