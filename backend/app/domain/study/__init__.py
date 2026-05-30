# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Study-domain pure-Python helpers (feat_study_lifecycle Phase 2).

Subpackage for the study lifecycle's pure-logic helpers. No I/O, no async,
no DB access — see CLAUDE.md "Domain Layer" convention. Service-layer
orchestrators in ``backend.app.services`` and worker code in
``backend.workers`` compose these helpers.
"""
