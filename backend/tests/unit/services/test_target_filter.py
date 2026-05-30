# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend/app/services/_target_filter.py``.

Per ``feat_index_document_browser`` Story 2.1 / spec D-13.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from backend.app.db.models import Cluster
from backend.app.services._target_filter import check_target_visible


def _fake_cluster(target_filter: str | None) -> Cluster:
    """A typing-shim Cluster — ``check_target_visible`` only reads
    ``target_filter`` so a SimpleNamespace is sufficient for the unit."""
    return cast(Cluster, SimpleNamespace(target_filter=target_filter))


def test_none_filter_allows_everything() -> None:
    cluster = _fake_cluster(None)
    assert check_target_visible(cluster, "acme-products") is True
    assert check_target_visible(cluster, "internal-secrets") is True


def test_glob_match() -> None:
    cluster = _fake_cluster("acme-*")
    assert check_target_visible(cluster, "acme-products") is True
    assert check_target_visible(cluster, "acme-orders") is True


def test_glob_no_match() -> None:
    cluster = _fake_cluster("acme-*")
    assert check_target_visible(cluster, "internal-secrets") is False
    assert check_target_visible(cluster, "Acme-products") is False  # case-sensitive


def test_exact_match() -> None:
    cluster = _fake_cluster("acme-products")
    assert check_target_visible(cluster, "acme-products") is True
    assert check_target_visible(cluster, "acme-products-v2") is False


def test_question_mark_glob() -> None:
    cluster = _fake_cluster("doc?")
    assert check_target_visible(cluster, "doc1") is True
    assert check_target_visible(cluster, "doc12") is False


def test_bracket_glob() -> None:
    cluster = _fake_cluster("acme-[abc]*")
    assert check_target_visible(cluster, "acme-alpha") is True
    assert check_target_visible(cluster, "acme-bravo") is True
    assert check_target_visible(cluster, "acme-zulu") is False


def test_anti_enumeration_via_404() -> None:
    """Filter rejects targets that exist on the cluster but don't match
    the glob. The router will translate this False into 404 TARGET_NOT_FOUND
    (not 403) to avoid enumeration."""
    cluster = _fake_cluster("public-*")
    assert check_target_visible(cluster, "private-customers") is False
