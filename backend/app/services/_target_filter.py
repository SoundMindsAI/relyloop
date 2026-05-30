# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Visibility check for ``cluster.target_filter`` glob patterns.

Per ``feat_index_document_browser`` spec D-13: when ``cluster.target_filter``
is set, the endpoints enforce visibility on every target query. A target
that does not match the glob is reported as 404 ``TARGET_NOT_FOUND`` (not
403) to avoid enumeration of hidden indices.
"""

from __future__ import annotations

import fnmatch

from backend.app.db.models import Cluster


def check_target_visible(cluster: Cluster, target: str) -> bool:
    """Return True iff ``target`` matches the cluster's ``target_filter`` glob.

    A ``target_filter`` of ``None`` means no filter — all targets visible.
    """
    pattern = cluster.target_filter
    if pattern is None:
        return True
    return fnmatch.fnmatchcase(target, pattern)
