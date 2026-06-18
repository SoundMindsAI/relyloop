# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ENGINE_VERSION_MATRIX shape + EngineTypeWire-key sync.

feat_engine_version_selection FR-2 / AC-10.

The matrix lives at ``backend/app/core/engine_versions.py`` as the source of
truth for valid install-time engine image tags. These tests pin the three
invariants the matrix's downstream consumers (install.sh helper, Compose
default sync, frontend mirror) depend on:

* Matrix keys equal the ``EngineTypeWire`` allowlist (no engine silently
  drops out of the matrix when added to the wire type).
* Every tuple is non-empty (the ``[0]`` access in the Compose-default-sync
  CI guard would IndexError otherwise).
* Every tuple element is a str (no accidental tuples-of-tuples or ints).
"""

from __future__ import annotations

from typing import get_args

from backend.app.api.v1.schemas import EngineTypeWire
from backend.app.core.engine_versions import ENGINE_VERSION_MATRIX


def test_matrix_keys_match_engine_type_wire() -> None:
    """Matrix keys MUST equal the EngineTypeWire allowlist verbatim.

    AC-10. Guards against a new engine being added to EngineTypeWire
    without a matching matrix entry — the install.sh helper would
    accept its version env var with no validation otherwise.
    """
    matrix_keys = set(ENGINE_VERSION_MATRIX.keys())
    wire_values = set(get_args(EngineTypeWire))
    assert matrix_keys == wire_values, (
        f"ENGINE_VERSION_MATRIX keys ({sorted(matrix_keys)}) drifted from "
        f"EngineTypeWire ({sorted(wire_values)}). Add or remove the matrix "
        f"entry in backend/app/core/engine_versions.py to match."
    )


def test_matrix_values_are_nonempty_tuples() -> None:
    """Every tuple MUST be non-empty so ``[0]`` access never IndexErrors.

    The matrix-Compose-default sync CI guard at
    scripts/ci/verify_engine_version_matrix_parity.sh reads
    ENGINE_VERSION_MATRIX[<engine>][0] to compare against docker-compose.yml.
    An empty tuple would crash the guard with a non-actionable error.
    """
    for engine, versions in ENGINE_VERSION_MATRIX.items():
        assert isinstance(versions, tuple), (
            f"ENGINE_VERSION_MATRIX[{engine!r}] is not a tuple: {versions!r}"
        )
        assert len(versions) > 0, (
            f"ENGINE_VERSION_MATRIX[{engine!r}] is empty — at least one "
            f"supported version must be listed."
        )


def test_matrix_values_are_strings() -> None:
    """Every tuple element MUST be a str.

    The install.sh helper compares operator input verbatim to each value
    via bash string equality; non-str entries would crash the bash mirror's
    serialization or be silently filtered.
    """
    for engine, versions in ENGINE_VERSION_MATRIX.items():
        for i, version in enumerate(versions):
            assert isinstance(version, str), (
                f"ENGINE_VERSION_MATRIX[{engine!r}][{i}] is not a str: "
                f"{version!r} ({type(version).__name__})"
            )
