# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Domain Literals for the LLM-vs-UBI study comparison surface.

These are the canonical discriminators for the comparison feature
(feat_ubi_llm_study_comparison). They live in the domain layer so the
service orchestrator (``services.study_comparison``) can classify and
validate without importing up into the API wire models, and the API
response schemas re-import them — one source of truth, correct
dependency direction (API → domain, never service → API).
"""

from __future__ import annotations

from typing import Literal

CompareKind = Literal["llm", "ubi"]
"""How a study's judgment list was generated: LLM-as-judge or UBI signals."""

CompareWarningCode = Literal["CROSS_CLUSTER", "TARGET_MISMATCH", "OBJECTIVE_MISMATCH"]
"""Non-fatal mismatch codes surfaced when pairing two studies for comparison."""
