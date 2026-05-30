# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Pure-domain logic (no I/O, no DB, no async).

Lives outside the adapter / service / router layers so unit tests can
exercise it deterministically without fixtures. Subdirectories group by
concern:

* ``query/`` — query rendering helpers (Jinja → JSON), parameter
  validation. Lands with infra_adapter_elastic Story 2.4.
* ``study/`` — study state machine (lands with feat_study_lifecycle).

Per CLAUDE.md "Domain Layer", every module here is synchronous and
deterministic. Side effects belong in ``services/``.
"""
