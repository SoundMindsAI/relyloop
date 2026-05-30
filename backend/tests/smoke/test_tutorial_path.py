# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Smoke test orchestrating tutorial Steps 5–8 against a running stack.

Designed for CI (Story 3.2) but also runs locally against ``make up``. The test:

1. Resolves the ``local-es`` cluster by name.
2. Creates a query set + bulk-adds 5 queries (subset of ``samples/queries.csv``).
3. Calls POST ``/api/v1/judgments/generate`` (LLM-required) and polls until
   ``judgment_list.status == 'complete'`` (~30s, ~$0.01 with ``gpt-4o-mini``).
4. Creates a query template from ``samples/templates/product_search.j2``.
5. Creates a 10-trial study; polls until ``status == 'completed'`` (max 5 min).
6. Asserts at least one trial has ``primary_metric > 0`` (the doc-id alignment
   guard — proves judgments + index intersect).
7. Asserts the digest is generated AND its narrative field is non-empty
   (the LLM-required path is fully exercised).

Skipped if ``RELYLOOP_API_BASE`` doesn't return 200 on ``/healthz`` within 10s.
This is the same path the operator tutorial walks (per spec §3 + Story 4.1)
— smoke + tutorial share one operator path, no degraded variants.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.smoke

# parents[3]: backend/tests/smoke/test_tutorial_path.py
#   → backend/tests/smoke → backend/tests → backend → repo
SAMPLES = Path(__file__).resolve().parents[3] / "samples"
SMOKE_QUERY_COUNT = 5  # subset of the 50-query CSV — keeps cost ~$0.01


def _wait_healthy(client: httpx.Client, timeout: float = 30.0) -> None:
    """Wait for /healthz status:ok AND the OpenAI capability check to record `ok`.

    `/healthz status:ok` alone is insufficient — per `backend/app/api/health.py`
    docstring, OpenAI degraded states (`missing_key` / `incapable` / capability
    `untested`) are NON-blocking and do NOT downgrade the top-level status.
    So a 200/`ok` healthz can return while the fire-and-forget OpenAI capability
    check is still running, and the smoke test fires `POST /judgments/generate`
    too early, hitting 503 `LLM_PROVIDER_INCAPABLE` with
    `structured_output='untested'`. Gate on `openai_capabilities.structured_output`
    explicitly so the test waits for the check to finish before proceeding.

    Timeout bumped to 30s (was 10s) to accommodate the capability check's
    OpenAI round-trip (models endpoint + chat completion + structured-output
    probe — each adds ~1-3s).
    """
    deadline = time.time() + timeout
    last_seen: dict[str, object] = {}
    while time.time() < deadline:
        try:
            r = client.get("/healthz")
            if r.status_code == 200:
                payload = r.json()
                if payload.get("status") == "ok":
                    caps = payload.get("openai_capabilities") or {}
                    if caps.get("structured_output") == "ok":
                        return
                    last_seen = payload
        except Exception:
            pass
        time.sleep(0.5)
    pytest.skip(
        f"API not healthy + OpenAI capability OK within {timeout}s; last seen: {last_seen!r}"
    )


def _create_judgment_template(c: httpx.Client) -> str:
    """Minimal `{{ query_text }}`-only template for the judgment-generation path.

    Keeping the judge template separate from the study template lets the
    judge target broad recall (no boost params) while the study optimizes
    the parameterized template. See
    backend/tests/integration/test_judgment_generate.py for the same shape.
    """
    resp = c.post(
        "/api/v1/query-templates",
        json={
            "name": f"smoke-judge-template-{int(time.time())}-{int(time.monotonic_ns())}",
            "engine_type": "elasticsearch",
            "body": '{"query": {"match": {"title": "{{ query_text }}"}}}',
            "declared_params": {},
        },
    )
    assert resp.status_code in (200, 201), (
        f"create judge template failed: {resp.status_code} {resp.text[:300]}"
    )
    return str(resp.json()["id"])


def _create_study_template(c: httpx.Client) -> str:
    """Full multi_match template (samples/templates/product_search.j2) for the study."""
    template_body = (SAMPLES / "templates" / "product_search.j2").read_text()
    resp = c.post(
        "/api/v1/query-templates",
        json={
            "name": f"smoke-study-template-{int(time.time())}-{int(time.monotonic_ns())}",
            "engine_type": "elasticsearch",
            "body": template_body,
            "declared_params": {
                "title_boost": "float",
                "description_boost": "float",
                "bullet_points_boost": "float",
            },
        },
    )
    assert resp.status_code in (200, 201), (
        f"create study template failed: {resp.status_code} {resp.text[:300]}"
    )
    return str(resp.json()["id"])


def test_smoke_generation_and_study_with_digest(api_base_url: str) -> None:
    with httpx.Client(base_url=api_base_url, timeout=30.0) as c:
        _wait_healthy(c)

        # Resolve local-es by name explicitly. seed-clusters registers BOTH
        # local-es and local-opensearch; only local-es has the seeded `products`
        # index, so the smoke must pin local-es regardless of return order.
        clusters = c.get("/api/v1/clusters", params={"limit": 200}).json()["data"]
        matching = [x for x in clusters if x["name"] == "local-es"]
        assert len(matching) == 1, f"expected exactly one local-es cluster, got {matching!r}"
        cluster_id = matching[0]["id"]

        # 1. Create query set + bulk-add a subset of queries.
        qs = c.post(
            "/api/v1/query-sets",
            json={
                "name": f"smoke-tutorial-queries-{int(time.time())}",
                "cluster_id": cluster_id,
                "description": "smoke test fixture",
            },
        ).json()
        with (SAMPLES / "queries.csv").open() as fh:
            all_queries = [{"query_text": row["query_text"]} for row in csv.DictReader(fh)]
        c.post(
            f"/api/v1/query-sets/{qs['id']}/queries",
            json={"queries": all_queries[:SMOKE_QUERY_COUNT]},
        )

        # 2. Generate judgments via LLM (requires OPENAI_API_KEY in CI).
        # Use a minimal `{{ query_text }}`-only template — the judgment-gen
        # worker calls render with no params, and a template with declared
        # params would trip "missing required template params". The study
        # below uses a separate, fully-parameterized template.
        judge_template_id = _create_judgment_template(c)
        study_template_id = _create_study_template(c)
        jg_resp = c.post(
            "/api/v1/judgments/generate",
            json={
                "name": f"smoke-tutorial-judgments-{int(time.time())}",
                "query_set_id": qs["id"],
                "cluster_id": cluster_id,
                "target": "products",
                "current_template_id": judge_template_id,
                "rubric": "Rate 0-3 by relevance to the query.",
            },
        )
        assert jg_resp.status_code == 202, (
            f"judgment generation rejected: {jg_resp.status_code} "
            f"{jg_resp.text[:300]} — smoke job requires OPENAI_API_KEY_TEST"
        )
        jl_id = jg_resp.json()["judgment_list_id"]

        # Poll for judgment-list completion. Median is ~30s with
        # gpt-4o-mini; tail latency can stretch past 2 minutes during
        # OpenAI capacity spikes. Budget bumped from 120s → 240s after
        # two flake hits in one development session (PRs #73 + #78,
        # both passed on re-run). 240s keeps the smoke job comfortably
        # within its 15-minute total budget.
        jl: dict[str, object] = {}
        # Use monotonic clock for duration measurement so an NTP adjustment
        # mid-test doesn't shift the deadline (per Gemini suggestion).
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            jl = c.get(f"/api/v1/judgment-lists/{jl_id}").json()
            status = jl.get("status")
            if status == "complete":
                break
            if status in ("failed", "partial_llm_failure"):
                pytest.fail(f"judgment generation terminal: {status} {jl.get('failed_reason')}")
            time.sleep(3)
        else:
            pytest.fail("judgment generation did not complete within 240s")

        # 3. Use the parameterized study template + 4. Create a 10-trial study.
        study_resp = c.post(
            "/api/v1/studies",
            json={
                "name": f"smoke-tutorial-study-{int(time.time())}",
                "cluster_id": cluster_id,
                "target": "products",
                "template_id": study_template_id,
                "query_set_id": qs["id"],
                "judgment_list_id": jl_id,
                "search_space": {
                    "params": {
                        "title_boost": {"type": "float", "low": 0.5, "high": 5.0},
                        "description_boost": {"type": "float", "low": 0.5, "high": 5.0},
                        "bullet_points_boost": {"type": "float", "low": 0.5, "high": 5.0},
                    }
                },
                "objective": {"metric": "ndcg", "k": 10},
                "config": {"max_trials": 10},
            },
        )
        assert study_resp.status_code in (200, 201, 202), (
            f"create_study failed: {study_resp.status_code} {study_resp.text[:500]}"
        )
        study = study_resp.json()
        deadline = time.time() + 5 * 60
        while time.time() < deadline:
            row = c.get(f"/api/v1/studies/{study['id']}").json()
            if row["status"] == "completed":
                break
            if row["status"] in ("failed", "cancelled"):
                pytest.fail(
                    f"study terminated unexpectedly: {row['status']} "
                    f"reason={row.get('failed_reason')}"
                )
            time.sleep(5)
        else:
            pytest.fail("study did not complete within 5 min")

        # 5. Doc-id alignment guard. Even with LLM-generated judgments, an
        # unaligned products/queries dataset would still produce primary_metric=0.
        trials = c.get(f"/api/v1/studies/{study['id']}/trials", params={"limit": 50}).json()
        winners = [t for t in trials["data"] if (t.get("primary_metric") or 0) > 0]
        assert winners, (
            "smoke test misaligned: study completed but no trial has "
            "primary_metric > 0; check that samples/products.json was seeded "
            "into 'products' index AND that the LLM judged docs that exist "
            "in the seeded index"
        )

        # 6. Digest assertion (LLM-required path) — poll briefly because the
        # digest worker runs after `complete_study` enqueues it.
        digest_resp = None
        deadline = time.time() + 90
        narrative = ""
        while time.time() < deadline:
            digest_resp = c.get(f"/api/v1/studies/{study['id']}/digest")
            if digest_resp.status_code == 200:
                narrative = (digest_resp.json().get("narrative") or "").strip()
                if narrative:
                    break
            time.sleep(3)
        assert narrative, (
            f"digest narrative empty after 90s — smoke job requires "
            f"OPENAI_API_KEY_TEST AND the digest worker must complete an "
            f"LLM call. Last response: "
            f"{digest_resp.status_code if digest_resp else 'n/a'} "
            f"{digest_resp.text[:200] if digest_resp else 'n/a'}"
        )
