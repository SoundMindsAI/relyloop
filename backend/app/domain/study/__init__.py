# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Study-domain pure-Python helpers (feat_study_lifecycle Phase 2).

Subpackage for the study lifecycle's pure-logic helpers. No I/O, no async,
no DB access — see CLAUDE.md "Domain Layer" convention. Service-layer
orchestrators in ``backend.app.services`` and worker code in
``backend.workers`` compose these helpers.
"""

from backend.app.domain.study.chain_summary import (
    CHAIN_STOP_REASONS,
    ChainStopReason,
    compute_cumulative_lift,
    derive_chain_stop_reason,
    select_best_link,
)

__all__ = [
    "CHAIN_STOP_REASONS",
    "ChainStopReason",
    "compute_cumulative_lift",
    "derive_chain_stop_reason",
    "select_best_link",
]
