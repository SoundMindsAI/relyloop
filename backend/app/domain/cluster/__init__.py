# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Pure domain logic for the cluster aggregate.

Currently holds :mod:`backend.app.domain.cluster.url_policy` — the pure
IP/hostname classification used by the SSRF guard (the async resolve-and-check
orchestrator lives in the service layer, ``backend/app/services/cluster_url_policy.py``).
"""
