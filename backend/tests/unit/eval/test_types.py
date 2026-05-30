# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Smoke tests for backend.app.eval.types — Literal contents per spec §8.4."""

from __future__ import annotations

from typing import get_args

from backend.app.eval.types import PrunerKind, SamplerKind, TrialStatus


def test_sampler_kind_wire_values():
    """SamplerKind exposes exactly the spec §8.4 sampler values."""
    assert set(get_args(SamplerKind)) == {"tpe", "random"}


def test_pruner_kind_wire_values():
    """PrunerKind exposes exactly the spec §8.4 pruner values."""
    assert set(get_args(PrunerKind)) == {"median", "none"}


def test_trial_status_matches_db_check_constraint():
    """TrialStatus mirrors the trials_status_check allowlist from migration 0003."""
    assert set(get_args(TrialStatus)) == {"complete", "failed", "pruned"}
