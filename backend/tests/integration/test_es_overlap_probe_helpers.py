# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Helper-smoke tests for backend/tests/integration/fixtures/es_overlap_probe.py.

Lands with ``infra_study_preflight_real_engine_integration`` Story 1.2 (a-d)
+ Story 1.3 (e-f sentinels). Six tests covering the new fixture's contracts
+ the two CI-only sentinels that fail loudly if the workflow's ES service
container or local-es credentials regress.

- (a) bulk_index_indexes_doc_ids — non-empty path, ids-query proves specific
  IDs are searchable (not just _count == 3).
- (b) bulk_index_empty_doc_ids_creates_empty_index — empty-doc_ids branch
  PUTs the index, SKIPS /_bulk (verified via monkeypatched
  ``httpx.AsyncClient.post`` URL counter — caller-supplied event_hooks would
  not reach the helper's own AsyncClient), and refreshes; _count == 0.
- (c) delete_overlap_probe_index_is_idempotent — DELETE on missing index
  returns cleanly; DELETE on existing index also returns cleanly.
- (d) seed_helper_missing_local_es_credentials (parametrized over CI=true /
  CI=false) — FR-6 + AC-INFRA-6 + AC-INFRA-7's RuntimeError-in-CI branch.
- (e) overlap_probe_real_engine_sentinel — CI-only ES reachability sentinel
  (FR-8). NO @es_required — that would skip the sentinel before its
  assertion runs.
- (f) overlap_probe_real_engine_credentials_sentinel — CI-only local-es
  credentials sentinel (FR-8). NO @es_required.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
import yaml

from backend.app.core.settings import get_settings
from backend.tests.integration.fixtures.es_overlap_probe import (
    _es_base_url,
    bulk_index_overlap_probe_docs,
    delete_overlap_probe_index,
    es_required,
    seed_minimum_for_overlap_probe_real_engine,
)

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# (a) bulk_index indexes specific IDs and they're searchable
# ---------------------------------------------------------------------------


@es_required
async def test_bulk_index_indexes_doc_ids() -> None:
    """AC for FR-2 happy path: ids-query proves the exact set is searchable."""
    es_url = _es_base_url()
    target = f"overlap-probe-helper-test-{uuid.uuid4().hex}"
    doc_ids = ["a", "b", "c"]
    try:
        await bulk_index_overlap_probe_docs(es_url, target, doc_ids)

        async with httpx.AsyncClient(base_url=es_url, timeout=30.0) as client:
            resp = await client.post(
                f"/{target}/_search",
                json={"query": {"ids": {"values": doc_ids}}, "size": 10},
            )
        resp.raise_for_status()
        body = resp.json()

        assert body["hits"]["total"]["value"] == 3
        returned_ids = {h["_id"] for h in body["hits"]["hits"]}
        assert returned_ids == set(doc_ids), (
            f"expected {set(doc_ids)} to be searchable, got {returned_ids}"
        )
    finally:
        await delete_overlap_probe_index(es_url, target)


# ---------------------------------------------------------------------------
# (b) bulk_index with empty doc_ids skips /_bulk and creates an empty index
# ---------------------------------------------------------------------------


@es_required
async def test_bulk_index_empty_doc_ids_creates_empty_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-2 empty-doc_ids branch: skip /_bulk, create empty index, refresh.

    Verifies via a class-level monkeypatch on ``httpx.AsyncClient.post`` that
    no POST URL contains ``_bulk`` (caller-supplied event_hooks would not
    reach the helper's own AsyncClient — see plan Task 5(b)).
    """
    es_url = _es_base_url()
    target = f"overlap-probe-helper-test-{uuid.uuid4().hex}"

    recorded_post_urls: list[str] = []
    original_post = httpx.AsyncClient.post

    async def counting_post(self, url, *args, **kwargs):  # noqa: ANN001 — httpx signature
        recorded_post_urls.append(str(url))
        return await original_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", counting_post)

    try:
        await bulk_index_overlap_probe_docs(es_url, target, [])

        # Lift the monkeypatch before the assertion-time _count probe so this
        # validation HTTP call doesn't pollute the recorded URL list.
        monkeypatch.setattr(httpx.AsyncClient, "post", original_post)

        async with httpx.AsyncClient(base_url=es_url, timeout=30.0) as client:
            count_resp = await client.get(f"/{target}/_count")
        count_resp.raise_for_status()
        assert count_resp.json()["count"] == 0

        bulk_calls = [u for u in recorded_post_urls if "_bulk" in u]
        assert bulk_calls == [], (
            f"empty doc_ids must skip /_bulk; recorded POST URLs: {recorded_post_urls}"
        )
    finally:
        await delete_overlap_probe_index(es_url, target)


# ---------------------------------------------------------------------------
# (c) delete_overlap_probe_index is idempotent on 200 + 404
# ---------------------------------------------------------------------------


@es_required
async def test_delete_overlap_probe_index_is_idempotent() -> None:
    """200 (index exists) and 404 (index missing) both return cleanly."""
    es_url = _es_base_url()
    target = f"overlap-probe-helper-test-{uuid.uuid4().hex}"

    try:
        # 404 path — index never created.
        await delete_overlap_probe_index(es_url, target)  # must not raise

        # 200 path — create then delete.
        await bulk_index_overlap_probe_docs(es_url, target, ["x"])
        await delete_overlap_probe_index(es_url, target)  # must not raise

        # Re-running the DELETE on the now-removed index is also clean.
        await delete_overlap_probe_index(es_url, target)
    finally:
        # Plan drift caught by GPT-5.5 final review: if bulk_index_... raises
        # between PUT and the explicit DELETE assertions above, the helper-test
        # index would leak. Belt-and-suspenders cleanup ensures isolation
        # discipline matches the 5 rewritten AC tests + smoke tests (a)/(b).
        await delete_overlap_probe_index(es_url, target)


# ---------------------------------------------------------------------------
# (d) FR-6 missing local-es credentials — parametrized over CI true/false
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ci_value", "expected_exception"),
    [
        pytest.param("", pytest.skip.Exception, id="ci_false"),
        pytest.param("true", RuntimeError, id="ci_true"),
    ],
)
async def test_seed_helper_missing_local_es_credentials(
    monkeypatch: pytest.MonkeyPatch,
    ci_value: str,
    expected_exception: type[BaseException],
) -> None:
    """FR-6 + AC-INFRA-6: missing local-es key routes to skip (local) or RuntimeError (CI).

    Monkeypatches the INSTANCE __dict__ of the cached Settings — @cached_property
    writes to instance __dict__ on first access (class __dict__ is a read-only
    mappingproxy and cannot be patched). The autouse _restore_settings_mutations
    fixture in conftest.py:18-26 snapshots+restores this mutation across tests.
    """
    settings = get_settings()
    # Inject a YAML that's well-formed but lacks the `local-es:` key.
    monkeypatch.setitem(
        settings.__dict__,
        "cluster_credentials_yaml",
        "unrelated-cluster:\n  username: x\n  password: y\n",
    )

    if ci_value:
        monkeypatch.setenv("CI", ci_value)
    else:
        monkeypatch.delenv("CI", raising=False)

    with pytest.raises(expected_exception) as exc_info:
        await seed_minimum_for_overlap_probe_real_engine()

    msg = str(exc_info.value)
    # Both paths share these substrings (operator-guidance).
    assert "local-es" in msg
    assert "cluster_credentials.yaml" in msg
    assert "scripts/install.sh" in msg

    if ci_value == "true":
        # CI-loud branch must point operators at the workflow step.
        assert "workflow regression" in msg
        assert "Seed cluster credentials" in msg
        assert ".github/workflows/pr.yml" in msg


# ---------------------------------------------------------------------------
# (e) CI sentinel: ES reachability  (FR-8 — NO @es_required)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CI") != "true",
    reason="CI-only sentinel — local runs use @es_required graceful skip",
)
def test_overlap_probe_real_engine_sentinel() -> None:
    """FR-8 / AC-INFRA-7: in CI, ES MUST be reachable; otherwise fail loudly.

    Does NOT carry @es_required — that decorator would skip the sentinel
    before its assertion runs, defeating the fail-loud guarantee.
    """
    url = _es_base_url()
    assert url, (
        "CI ES sentinel: Elasticsearch is not reachable on http://localhost:9200 "
        "or http://elasticsearch:9200. The .github/workflows/pr.yml workflow's "
        "'elasticsearch:9.4.1' service container is missing or unhealthy — the 5 "
        "rewritten overlap-probe tests in test_studies_api.py will silently skip "
        "via @es_required, stripping the regression coverage this feature delivers. "
        "Check the workflow's `services.elasticsearch` block."
    )


# ---------------------------------------------------------------------------
# (f) CI sentinel: local-es credentials present  (FR-8 — NO @es_required)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CI") != "true",
    reason="CI-only sentinel — local runs use the FR-6 helper skip",
)
def test_overlap_probe_real_engine_credentials_sentinel() -> None:
    """FR-8 / AC-INFRA-7: in CI, cluster_credentials.yaml MUST contain local-es.

    Does NOT carry @es_required — same reason as sentinel (e); credentials
    are a separate failure axis from ES reachability.
    """
    yaml_str = get_settings().cluster_credentials_yaml
    assert yaml_str, (
        "CI credentials sentinel: cluster_credentials_yaml is not mounted. "
        "The .github/workflows/pr.yml 'Seed cluster credentials' step that writes "
        "./secrets/cluster_credentials.yaml may have been removed or broken."
    )

    parsed = yaml.safe_load(yaml_str)
    assert isinstance(parsed, dict) and "local-es" in parsed, (
        "CI credentials sentinel: cluster_credentials_yaml is mounted but does NOT "
        "contain a top-level `local-es:` entry. The .github/workflows/pr.yml "
        "'Seed cluster credentials' step's heredoc may have drifted from the "
        "local-es defaults. The 5 rewritten overlap-probe tests in test_studies_api.py "
        "would otherwise raise RuntimeError per FR-6's CI-loud-failure branch."
    )
