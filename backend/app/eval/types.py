"""Enumerated value types for the optimization / evaluation layer.

Source of truth for the wire values cited in
``infra_optuna_eval/feature_spec.md`` §8.4 "Enumerated value contracts".
The Literal aliases here are imported by:

* ``backend/app/eval/optuna_runtime.py`` for sampler/pruner validation.
* ``backend/workers/trials.py`` for trial-status enforcement at INSERT time.
* (Future) ``feat_study_lifecycle`` Phase 2 API layer for validating
  ``studies.config`` / ``studies.objective`` request payloads.

The ``trials.status`` allowlist is ALSO enforced at the database CHECK
level in [0003_study_lifecycle_schema](../../../migrations/versions/0003_study_lifecycle_schema.py)
(``trials_status_check``); ``TrialStatus`` mirrors that constraint for use
in async/worker code where DB introspection isn't available.

Per spec §FR-2: ``"tpe"`` is the MVP1 default sampler; ``"random"`` is the
baseline-comparison option. CMA-ES is reserved for MVP2.

Per spec §FR-2: ``"median"`` (MedianPruner with ``n_warmup_steps=10``) is
the MVP1 default pruner; ``"none"`` (NopPruner) is selectable. Pruner
auto-disables for small studies — see the explicit-vs-omitted contract
documented in ``backend/app/eval/optuna_runtime.py:build_pruner``.
"""

from __future__ import annotations

from typing import Literal

SamplerKind = Literal["tpe", "random"]
"""Optuna sampler choice. Wire values consumed by ``studies.config.sampler``."""

PrunerKind = Literal["median", "none"]
"""Optuna pruner choice. Wire values consumed by ``studies.config.pruner``."""

TrialStatus = Literal["complete", "failed", "pruned"]
"""Terminal state of a trial. Mirrors the DB CHECK constraint
``trials_status_check`` from migration 0003."""
