# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Optuna study factory + sampler/pruner builders (infra_optuna_eval Story 2.1).

Pure-Python wrappers around Optuna's ``optuna.create_study``,
``RDBStorage``, ``TPESampler`` / ``RandomSampler``, and ``MedianPruner`` /
``NopPruner``. Encapsulates spec §FR-1 (RDB schema isolation via
``options=-csearch_path=optuna``) and spec §FR-2 (sampler / pruner defaults,
key-presence-vs-absence semantics, explicit-override).

URL composition is factored into the pure ``_compose_storage_url()`` helper
so unit tests can verify it without constructing a real ``RDBStorage``
(which may open a DB connection depending on the installed Optuna version
— see spec FR-1/AC-1b for the "neither timing is guaranteed" clause).

Optuna's ``RDBStorage`` is **synchronous**; callers from async contexts
(the worker, integration tests) wrap usage in ``asyncio.to_thread()`` per
the project Conventions in the implementation plan.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse

import optuna
from optuna.pruners import BasePruner, MedianPruner, NopPruner
from optuna.samplers import BaseSampler, RandomSampler, TPESampler

# ---------------------------------------------------------------------------
# Storage URL composition (pure)
# ---------------------------------------------------------------------------

_OPTUNA_SEARCH_PATH_OPTION = "options=-csearch_path=optuna"
"""Postgres connection option that pins all CREATE/SELECT to the ``optuna`` schema."""

STUDIES_TPE_WARMUP_FLOOR: int = 50
"""Trial-count floor below which ``MedianPruner`` cannot warm up (``NopPruner``
is substituted) AND the wizard's Custom-mode sub-warmup warning fires
(``feat_study_sub_warmup_guard``). The frontend mirror at
``ui/src/components/studies/create-study-modal.tsx`` carries a
``// Values must match`` comment per the Enumerated Value Contract
Discipline; the cross-side parity is asserted by
``test_studies_tpe_warmup_floor_constant_value`` in
``backend/tests/unit/eval/test_optuna_runtime.py``."""


def _compose_storage_url(database_url: str) -> str:
    """Build the URL Optuna's ``RDBStorage`` should connect with.

    Steps:

    1. Strip the ``+asyncpg`` driver prefix (Optuna uses a sync engine).
       Mirrors the conversion in ``backend/app/db/optuna_schema.py:41``.
    2. Append ``options=-csearch_path=optuna`` to the query string so
       all Optuna DDL/DML lands in the ``optuna.*`` namespace (per spec
       FR-1 + the operational invariant from
       ``docs/01_architecture/optimization.md``).

    Idempotent: if the option already appears in the URL, the URL is
    returned unchanged.
    """
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(sync_url)
    existing_query = parsed.query

    if _OPTUNA_SEARCH_PATH_OPTION in existing_query:
        return sync_url

    new_query = (
        f"{existing_query}&{_OPTUNA_SEARCH_PATH_OPTION}"
        if existing_query
        else _OPTUNA_SEARCH_PATH_OPTION
    )
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )


def build_storage(database_url: str) -> optuna.storages.RDBStorage:
    """Construct an ``RDBStorage`` against the same Postgres as the app DB.

    Whether construction opens a DB connection or defers it to first use
    is an Optuna implementation detail — spec FR-1/AC-1b explicitly does
    not constrain the trigger. Callers in async contexts MUST wrap the
    call in ``asyncio.to_thread()``.
    """
    return optuna.storages.RDBStorage(url=_compose_storage_url(database_url))


# ---------------------------------------------------------------------------
# Sampler / pruner builders (spec §FR-2 contract)
# ---------------------------------------------------------------------------


def build_sampler(config: dict[str, Any], *, seed: int | None) -> BaseSampler:
    """Build the Optuna sampler from ``studies.config``.

    Spec §FR-2:

    * ``"sampler"`` key absent → ``TPESampler(seed=seed)`` (MVP1 default).
    * ``config["sampler"] == "tpe"`` → ``TPESampler(seed=seed)``.
    * ``config["sampler"] == "random"`` → ``RandomSampler(seed=seed)``
      (baseline-comparison option per spec §3).

    Raises:
        ValueError: on any other value (CMA-ES, hyperband, etc. are reserved
        for MVP2 per spec §3 Out of scope).
    """
    sampler = config.get("sampler", "tpe")
    if sampler == "tpe":
        return TPESampler(seed=seed)
    if sampler == "random":
        return RandomSampler(seed=seed)
    raise ValueError(
        f"unsupported sampler {sampler!r}; MVP1 allows: ['tpe', 'random'] "
        f"(CMA-ES reserved for MVP2 per spec §3)"
    )


def build_pruner(config: dict[str, Any]) -> BasePruner:
    """Build the Optuna pruner from ``studies.config``.

    Spec §FR-2 two-pronged contract:

    * ``"pruner"`` key **absent** AND ``config["max_trials"] < STUDIES_TPE_WARMUP_FLOOR`` →
      ``NopPruner`` (safeguard — small studies don't get enough TPE warmup).
    * ``"pruner"`` key **absent** AND ``config["max_trials"] >= STUDIES_TPE_WARMUP_FLOOR`` →
      ``MedianPruner(n_warmup_steps=10)`` (MVP1 default).
    * ``config["pruner"] == "median"`` **explicit** → ``MedianPruner(n_warmup_steps=10)``
      regardless of ``max_trials`` (operator-override per spec FR-2 AC-6b).
    * ``config["pruner"] == "none"`` → ``NopPruner``.

    The data-contract distinction between "default-omitted" and "explicit-median"
    is the key-presence signal in ``config``. Phase 2's API layer is required NOT
    to materialize defaults into the stored row (per spec FR-2 last paragraph).

    Raises:
        ValueError: on any other ``pruner`` value, or if ``max_trials`` is
        missing AND ``pruner`` is unspecified (we need ``max_trials`` to make
        the safeguard decision).
    """
    if "pruner" in config:
        pruner = config["pruner"]
        if pruner == "median":
            return MedianPruner(n_warmup_steps=10)
        if pruner == "none":
            return NopPruner()
        raise ValueError(f"unsupported pruner {pruner!r}; MVP1 allows: ['median', 'none']")

    # Default-omitted: depends on max_trials.
    max_trials = config.get("max_trials")
    if not isinstance(max_trials, int):
        raise ValueError(
            "config.max_trials is required when pruner is unspecified "
            "(needed to apply the FR-2 small-study auto-disable safeguard); "
            f"got {type(max_trials).__name__}"
        )
    if max_trials < STUDIES_TPE_WARMUP_FLOOR:
        return NopPruner()
    return MedianPruner(n_warmup_steps=10)


# ---------------------------------------------------------------------------
# Study factory
# ---------------------------------------------------------------------------


def get_or_create_study(
    *,
    storage: optuna.storages.RDBStorage,
    optuna_study_name: str,
    direction: str,
    sampler: BaseSampler,
    pruner: BasePruner,
) -> optuna.Study:
    """Load the Optuna study by name, or create it.

    Thin wrapper over ``optuna.create_study(load_if_exists=True, ...)``.
    Synchronous — wrap callers in ``asyncio.to_thread()`` from async code.
    """
    return optuna.create_study(
        storage=storage,
        study_name=optuna_study_name,
        direction=direction,
        sampler=sampler,
        pruner=pruner,
        load_if_exists=True,
    )
