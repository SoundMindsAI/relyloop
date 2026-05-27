#!/usr/bin/env python3
# ruff: noqa: E501, S310, S603, S607, S608
#   E501 (line too long): scenario literals contain long product titles +
#                  news headlines + helper-text strings. Wrapping each one
#                  hurts readability more than it helps; this is a script,
#                  not library code.
#   S310 (urllib): script only hits hardcoded localhost ports — no user-
#                  controlled URL schemes.
#   S603/S607 (subprocess/partial path): we invoke `docker compose exec`
#                  with closed-set arguments; PATH-based resolution is the
#                  documented operator workflow.
#   S608 (SQL injection): the rename statement interpolates only values from
#                  the closed-set SCENARIOS literal at the top of this file;
#                  there is no untrusted input path.
"""Seed 4 meaningful demo scenarios into a RelyLoop dev instance.

Scenarios:
  1. acme-products-prod         (Elasticsearch, e-commerce) → target_filter='products*'
  2. corp-docs-search           (Elasticsearch, knowledge base) → target_filter='docs-*'
  3. news-search-staging        (OpenSearch, news/media) → target_filter='news-*'
  4. jobs-marketplace-prod      (Elasticsearch, jobs) → target_filter='job-*'

For each scenario: cluster (with target_filter scoping the dropdown to its
own index family) + ES/OS index + sample docs + query template + query set
with 5 queries + judgment list with up to 10 judgments + completed study
with trials + digest + pending proposal.

**Idempotent:** drops all existing demo state (TRUNCATE clusters CASCADE in
Postgres + DELETE matching indices on ES + OS) before reseeding. Safe to run
after integration test runs wipe the dev DB.

**Why this script exists:** integration tests share the dev Postgres and
wipe clusters via the ``clean_clusters`` fixture. The previous workflow
re-seeded via a script in ``/tmp/`` (operator-local, easy to lose). This
script lives under version control and is reachable via ``make seed-demo``.

Run from the host (NOT inside a container — uses 127.0.0.1 ports on the
host network)::

    make seed-demo                  # safe; prompts before destroying state
    make seed-demo FORCE=1          # skip the prompt (CI / automation)
    python3 scripts/seed_meaningful_demos.py --force   # equivalent

Prereqs: ``make up`` has run successfully + Alembic head includes
``0014_clusters_target_filter`` (feat_cluster_target_filter).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "http://localhost:8000/api/v1"
ES = "http://localhost:9200"
ES_AUTH = ("elastic", "changeme")
OS = "http://localhost:9201"
OS_AUTH = ("admin", "admin")

# Postgres tables wiped before reseeding. TRUNCATE clusters CASCADE handles
# the FK fanout but we list every table explicitly so the operator sees the
# blast radius on stdout.
TRUNCATE_TABLES = (
    "proposals",
    "digests",
    "trials",
    "studies",
    "judgments",
    "judgment_lists",
    "queries",
    "query_sets",
    "query_templates",
    "clusters",
)

# ES / OS user indices created by the seed (excludes engine system indices).
DEMO_ES_INDICES = ("products", "docs-articles", "job-listings")
DEMO_OS_INDICES = ("news-articles",)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _basic(auth: tuple[str, str]) -> str:
    import base64

    return "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()


def http(
    method: str,
    url: str,
    body: dict | None = None,
    auth: tuple[str, str] | None = None,
    quiet_404: bool = False,
) -> dict:
    """HTTP wrapper. Set `quiet_404=True` for expected-404 polling loops
    (e.g., waiting for a digest to land) so the loop doesn't spam the
    operator with N×30 "DIGEST_NOT_READY" stack traces."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if auth:
        headers["Authorization"] = _basic(auth)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 404 and quiet_404:
            raise
        body = e.read().decode()
        print(
            f"\n!! HTTP {e.code} on {method} {url}\n   body={body[:500]}\n   sent={json.dumps(data.decode() if data else None)[:500]}"
        )
        raise


def post(path: str, body: dict) -> dict:
    return http("POST", f"{API}{path}", body=body)


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "slug": "acme-products-prod",
        "engine_type": "elasticsearch",
        "base_url": "http://elasticsearch:9200",
        "auth_kind": "es_basic",
        "credentials_ref": "local-es",
        "environment": "prod",
        "target_filter": "products*",
        "host_base_url": ES,
        "host_auth": ES_AUTH,
        "target": "products",
        "index_mapping": {
            "mappings": {
                "properties": {
                    "title": {"type": "text"},
                    "description": {"type": "text"},
                    "brand": {"type": "keyword"},
                    "category": {"type": "keyword"},
                    "price": {"type": "float"},
                }
            }
        },
        "docs": [
            {
                "id": "p1001",
                "doc": {
                    "title": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
                    "description": "Industry-leading noise cancellation with 30-hour battery life and Hi-Res Audio support.",
                    "brand": "Sony",
                    "category": "audio",
                    "price": 399.99,
                },
            },
            {
                "id": "p1002",
                "doc": {
                    "title": "Bose QuietComfort Ultra Headphones",
                    "description": "Premium over-ear headphones with immersive spatial audio and best-in-class noise cancellation.",
                    "brand": "Bose",
                    "category": "audio",
                    "price": 429.00,
                },
            },
            {
                "id": "p2001",
                "doc": {
                    "title": "Nike Pegasus 41 Women's Road Running Shoes",
                    "description": "Responsive cushioning with Air Zoom unit, designed for daily training and long runs.",
                    "brand": "Nike",
                    "category": "footwear",
                    "price": 140.00,
                },
            },
            {
                "id": "p2002",
                "doc": {
                    "title": "Brooks Ghost 16 Women's Running Shoes",
                    "description": "Smooth, balanced cushioning for neutral runners. Updated DNA LOFT v3 midsole.",
                    "brand": "Brooks",
                    "category": "footwear",
                    "price": 145.00,
                },
            },
            {
                "id": "p3001",
                "doc": {
                    "title": "Wüsthof Classic 8-Piece Kitchen Knife Block Set",
                    "description": "Forged German stainless steel set with chef's knife, paring knife, bread knife, and steel.",
                    "brand": "Wüsthof",
                    "category": "kitchen",
                    "price": 549.00,
                },
            },
        ],
        "template_name": "multi-match-title-boost-v1",
        "template_body": json.dumps(
            {
                "query": {
                    "multi_match": {
                        "query": "{{ query_text }}",
                        "fields": [
                            "title^{{ title_boost }}",
                            "description^{{ description_boost }}",
                            "brand^2",
                        ],
                        "type": "best_fields",
                    }
                }
            }
        ),
        # Two tunable params (title_boost + description_boost) give Optuna a
        # 2-D search space — single-param sweeps were degenerate against the
        # sparse demo judgments (ranking stayed fixed regardless of the one
        # knob's value). With two boosts the optimizer can trade title-vs-
        # description weight per query type, producing visible metric variance.
        "template_declared_params": {"title_boost": "float", "description_boost": "float"},
        "query_set_name": "top-product-searches-q4-2025",
        "queries": [
            {"query_text": "wireless noise cancelling headphones"},
            {"query_text": "womens running shoes"},
            {"query_text": "kitchen knife set"},
            {"query_text": "sony headphones"},
            {"query_text": "noise cancelling over ear"},
        ],
        "judgment_list_name": "acme-products-relevance-2025-12",
        "rubric": "Rate 0=irrelevant, 1=partial, 2=relevant, 3=highly relevant by intent match (brand, product type, key feature).",
        # query_idx → doc_id → rating
        "judgments_map": [
            # q0 wireless noise cancelling: p1001=3, p1002=3, p2001=0, p2002=0, p3001=0
            (0, "p1001", 3),
            (0, "p1002", 3),
            (0, "p2001", 0),
            # q1 womens running shoes
            (1, "p2001", 3),
            (1, "p2002", 3),
            (1, "p1001", 0),
            # q2 kitchen knife set
            (2, "p3001", 3),
            (2, "p1001", 0),
            # q3 sony headphones
            (3, "p1001", 3),
            (3, "p1002", 1),
        ],
        "study_name": "tune-product-title-boost-baseline",
    },
    {
        "slug": "corp-docs-search",
        "engine_type": "elasticsearch",
        "base_url": "http://elasticsearch:9200",
        "auth_kind": "es_basic",
        "credentials_ref": "local-es",
        "environment": "prod",
        "target_filter": "docs-*",
        "host_base_url": ES,
        "host_auth": ES_AUTH,
        "target": "docs-articles",
        "index_mapping": {
            "mappings": {
                "properties": {
                    "title": {"type": "text"},
                    "body": {"type": "text"},
                    "section": {"type": "keyword"},
                }
            }
        },
        "docs": [
            {
                "id": "d101",
                "doc": {
                    "title": "How to reset your password",
                    "body": "If you have forgotten your password, click 'Forgot password' on the sign-in screen and follow the email link to reset it. The reset link expires in 30 minutes.",
                    "section": "account",
                },
            },
            {
                "id": "d102",
                "doc": {
                    "title": "Enabling two-factor authentication",
                    "body": "Two-factor authentication adds an extra layer of security. Open Settings → Security → Two-factor authentication and follow the setup wizard.",
                    "section": "account",
                },
            },
            {
                "id": "d201",
                "doc": {
                    "title": "Connecting to Slack from the integrations panel",
                    "body": "From your workspace settings, navigate to Integrations and click 'Add Slack'. Authorize the app in your Slack workspace and pick a default channel.",
                    "section": "integrations",
                },
            },
            {
                "id": "d202",
                "doc": {
                    "title": "Setting up GitHub webhooks",
                    "body": "Webhooks let GitHub notify your team channel on every push and pull request. Go to your repository settings, then Webhooks, and add the URL from the Integrations panel.",
                    "section": "integrations",
                },
            },
            {
                "id": "d301",
                "doc": {
                    "title": "Exporting your data as CSV or JSON",
                    "body": "From the workspace admin console, choose Data → Export. Select the format (CSV or JSON), the date range, and the resources to include.",
                    "section": "data",
                },
            },
        ],
        "template_name": "multi-match-phrase-v1",
        "template_body": json.dumps(
            {
                "query": {
                    "multi_match": {
                        "query": "{{ query_text }}",
                        "fields": ["title^{{ title_boost }}", "body"],
                        "type": "best_fields",
                    }
                }
            }
        ),
        "template_declared_params": {"title_boost": "float"},
        "query_set_name": "top-helpcenter-queries-dec-2025",
        "queries": [
            {"query_text": "how do I reset my password"},
            {"query_text": "enable 2fa"},
            {"query_text": "slack integration setup"},
            {"query_text": "github webhook"},
            {"query_text": "export data csv"},
        ],
        "judgment_list_name": "corp-docs-clicks-2025-12",
        "rubric": "Rate based on whether the article directly answers the user's help-center query. 0=irrelevant, 1=related, 2=relevant, 3=top answer.",
        "judgments_map": [
            (0, "d101", 3),
            (0, "d102", 1),
            (1, "d102", 3),
            (1, "d101", 1),
            (2, "d201", 3),
            (2, "d202", 1),
            (3, "d202", 3),
            (3, "d201", 0),
            (4, "d301", 3),
        ],
        "study_name": "reduce-fuzziness-helpcenter-search",
    },
    {
        "slug": "news-search-staging",
        "engine_type": "opensearch",
        "base_url": "http://opensearch:9200",
        "auth_kind": "opensearch_basic",
        "credentials_ref": "local-opensearch",
        "environment": "staging",
        "target_filter": "news-*",
        "host_base_url": OS,
        "host_auth": OS_AUTH,
        "target": "news-articles",
        "index_mapping": {
            "mappings": {
                "properties": {
                    "title": {"type": "text"},
                    "body": {"type": "text"},
                    "topic": {"type": "keyword"},
                    "published_at": {"type": "date"},
                }
            }
        },
        "docs": [
            {
                "id": "n101",
                "doc": {
                    "title": "Federal Reserve holds rates steady amid mixed inflation signals",
                    "body": "The Federal Reserve voted to maintain its benchmark interest rate, citing easing but still-elevated inflation.",
                    "topic": "economy",
                    "published_at": "2025-12-15T14:00:00Z",
                },
            },
            {
                "id": "n102",
                "doc": {
                    "title": "Tech sector layoffs slow in Q4 after a turbulent year",
                    "body": "Major technology employers reported a slowdown in workforce reductions during the fourth quarter, though hiring remains subdued.",
                    "topic": "tech",
                    "published_at": "2025-12-10T09:30:00Z",
                },
            },
            {
                "id": "n201",
                "doc": {
                    "title": "World leaders gather for climate summit in Geneva",
                    "body": "Heads of state from over 90 countries convened in Geneva to negotiate the next phase of global emissions reductions.",
                    "topic": "climate",
                    "published_at": "2025-12-18T07:00:00Z",
                },
            },
            {
                "id": "n202",
                "doc": {
                    "title": "Renewable energy installations hit record high in 2025",
                    "body": "Solar and wind installations together accounted for the majority of new electricity generation capacity in 2025.",
                    "topic": "climate",
                    "published_at": "2025-11-25T12:00:00Z",
                },
            },
            {
                "id": "n301",
                "doc": {
                    "title": "Quantum computing milestone: error correction breakthrough",
                    "body": "Researchers at a leading lab demonstrated stable error-correction protocols on a 100-qubit system.",
                    "topic": "tech",
                    "published_at": "2025-12-12T16:00:00Z",
                },
            },
        ],
        "template_name": "multi-match-recency-decay-v1",
        "template_body": json.dumps(
            {
                "query": {
                    "function_score": {
                        "query": {
                            "multi_match": {
                                "query": "{{ query_text }}",
                                "fields": ["title^{{ title_boost }}", "body"],
                            }
                        },
                        "functions": [
                            {
                                "gauss": {
                                    "published_at": {"origin": "now", "scale": "7d", "decay": 0.5}
                                }
                            }
                        ],
                        "score_mode": "multiply",
                    }
                }
            }
        ),
        "template_declared_params": {"title_boost": "float"},
        "query_set_name": "trending-news-queries-2025-12",
        "queries": [
            {"query_text": "fed interest rate decision"},
            {"query_text": "tech layoffs Q4"},
            {"query_text": "climate summit geneva"},
            {"query_text": "renewable energy 2025"},
            {"query_text": "quantum computing breakthrough"},
        ],
        "judgment_list_name": "news-editorial-2025-12",
        "rubric": "Rate articles by editorial relevance: does this article directly cover the searched event/topic? 0=off-topic, 1=tangential, 2=on-topic, 3=lead story.",
        "judgments_map": [
            (0, "n101", 3),
            (1, "n102", 3),
            (2, "n201", 3),
            (2, "n202", 1),
            (3, "n202", 3),
            (3, "n201", 2),
            (4, "n301", 3),
        ],
        "study_name": "add-7day-freshness-decay-news",
    },
    {
        "slug": "jobs-marketplace-prod",
        "engine_type": "elasticsearch",
        "base_url": "http://elasticsearch:9200",
        "auth_kind": "es_basic",
        "credentials_ref": "local-es",
        "environment": "prod",
        "target_filter": "job-*",
        "host_base_url": ES,
        "host_auth": ES_AUTH,
        "target": "job-listings",
        "index_mapping": {
            "mappings": {
                "properties": {
                    "title": {"type": "text"},
                    "company": {"type": "text"},
                    "location": {"type": "keyword"},
                    "description": {"type": "text"},
                    "posted_at": {"type": "date"},
                }
            }
        },
        "docs": [
            {
                "id": "j101",
                "doc": {
                    "title": "Senior Software Engineer, Backend Infrastructure",
                    "company": "Stripe",
                    "location": "San Francisco, CA",
                    "description": "Design and operate the core payments backend serving millions of transactions per day. Python/Go preferred.",
                    "posted_at": "2025-12-08T10:00:00Z",
                },
            },
            {
                "id": "j102",
                "doc": {
                    "title": "Staff Site Reliability Engineer",
                    "company": "Datadog",
                    "location": "New York, NY",
                    "description": "Lead reliability and observability initiatives across the platform. Strong Kubernetes and incident-response experience required.",
                    "posted_at": "2025-12-12T09:00:00Z",
                },
            },
            {
                "id": "j201",
                "doc": {
                    "title": "Product Manager, Search Quality",
                    "company": "Algolia",
                    "location": "Remote",
                    "description": "Own the search relevance roadmap. Partner with ML and engineering to drive measurable quality wins.",
                    "posted_at": "2025-12-15T11:00:00Z",
                },
            },
            {
                "id": "j202",
                "doc": {
                    "title": "Senior Product Designer, Onboarding",
                    "company": "Linear",
                    "location": "Remote",
                    "description": "Shape the first-five-minutes experience for new teams. Design-systems fluency expected.",
                    "posted_at": "2025-12-09T08:00:00Z",
                },
            },
            {
                "id": "j301",
                "doc": {
                    "title": "Machine Learning Engineer, Ranking",
                    "company": "Pinterest",
                    "location": "Seattle, WA",
                    "description": "Improve ranking models that power discovery feeds. PyTorch + large-scale training experience.",
                    "posted_at": "2025-12-14T13:00:00Z",
                },
            },
        ],
        "template_name": "function-score-recency-v1",
        "template_body": json.dumps(
            {
                "query": {
                    "function_score": {
                        "query": {
                            "multi_match": {
                                "query": "{{ query_text }}",
                                "fields": [
                                    "title^{{ title_boost }}",
                                    "company^{{ company_boost }}",
                                    "description",
                                ],
                            }
                        },
                        "functions": [
                            {"exp": {"posted_at": {"origin": "now", "scale": "30d", "decay": 0.5}}}
                        ],
                    }
                }
            }
        ),
        "template_declared_params": {"title_boost": "float", "company_boost": "float"},
        "query_set_name": "top-jobtitle-searches-q4-2025",
        "queries": [
            {"query_text": "senior software engineer backend"},
            {"query_text": "site reliability engineer"},
            {"query_text": "product manager search"},
            {"query_text": "product designer remote"},
            {"query_text": "machine learning engineer"},
        ],
        "judgment_list_name": "jobs-relevance-2025-12",
        "rubric": "Rate listings by title + skill match to the search. 0=wrong role, 1=related, 2=good match, 3=exact match.",
        "judgments_map": [
            (0, "j101", 3),
            (1, "j102", 3),
            (2, "j201", 3),
            (3, "j202", 3),
            (4, "j301", 3),
        ],
        "study_name": "tune-jobtitle-vs-company-boost",
    },
]


# ---------------------------------------------------------------------------
# Seed flow per scenario
# ---------------------------------------------------------------------------


def seed_scenario(s: dict) -> dict:
    print(f"\n=== {s['slug']} ({s['engine_type']}) ===")

    # 1. Create ES/OS index with mapping
    http("PUT", f"{s['host_base_url']}/{s['target']}", body=s["index_mapping"], auth=s["host_auth"])
    print(f"  index: {s['target']}")

    # 2. Bulk-load docs (one PUT per doc — small set, fine).
    for d in s["docs"]:
        http(
            "PUT",
            f"{s['host_base_url']}/{s['target']}/_doc/{d['id']}",
            body=d["doc"],
            auth=s["host_auth"],
        )
    # Refresh so judgments can be doc-id-mapped immediately. (ES rejects a body on _refresh.)
    http("POST", f"{s['host_base_url']}/{s['target']}/_refresh", body=None, auth=s["host_auth"])
    print(f"  docs: {len(s['docs'])}")

    # 3. Register cluster (probes the engine; will fail fast if creds are wrong).
    #    target_filter scopes GET /clusters/{id}/targets to this cluster's
    #    index family — closes the "demo limitation" where 3 ES-backed
    #    clusters share one physical engine and the dropdown cross-pollinates.
    cluster = post(
        "/clusters",
        {
            "name": s["slug"],
            "engine_type": s["engine_type"],
            "environment": s["environment"],
            "base_url": s["base_url"],
            "auth_kind": s["auth_kind"],
            "credentials_ref": s["credentials_ref"],
            "target_filter": s["target_filter"],
        },
    )
    cluster_id = cluster["id"]
    print(f"  cluster: {cluster_id}")

    # 4. Create query template
    template = post(
        "/query-templates",
        {
            "name": s["template_name"],
            "engine_type": s["engine_type"],
            "body": s["template_body"],
            "declared_params": s["template_declared_params"],
        },
    )
    template_id = template["id"]
    print(f"  template: {template_id} ({s['template_name']})")

    # 5. Create query set
    qset = post(
        "/query-sets",
        {
            "name": s["query_set_name"],
            "cluster_id": cluster_id,
        },
    )
    qset_id = qset["id"]
    print(f"  query-set: {qset_id} ({s['query_set_name']})")

    # 6. Add queries
    bulk = post(f"/query-sets/{qset_id}/queries", {"queries": s["queries"]})
    print(f"  queries added: {bulk['added']}")

    # Fetch query rows back so we have their IDs (need them for judgments)
    qrows_resp = http("GET", f"{API}/query-sets/{qset_id}/queries?limit=50")
    qrows = qrows_resp["data"]
    # Build text->id map; the bulk endpoint preserves submission order in the response
    qtext_to_id = {r["query_text"]: r["id"] for r in qrows}
    # Indexed by original submission order (sample queries are unique by text)
    qid_by_idx = [qtext_to_id[q["query_text"]] for q in s["queries"]]

    # 7. Import judgment list (judgments reference query_id + doc_id)
    judgments = [
        {"query_id": qid_by_idx[qi], "doc_id": doc_id, "rating": rating}
        for (qi, doc_id, rating) in s["judgments_map"]
    ]
    jlist = post(
        "/judgment-lists/import",
        {
            "name": s["judgment_list_name"],
            "query_set_id": qset_id,
            "cluster_id": cluster_id,
            "target": s["target"],
            "rubric": s["rubric"],
            "judgments": judgments,
        },
    )
    jlist_id = jlist["id"]
    print(f"  judgment-list: {jlist_id} ({len(judgments)} judgments)")

    # 8. Create a REAL study (no test-endpoint shortcut) and poll to completion.
    #
    # The previous version called /_test/studies/seed-completed which hardcoded
    # best_metric=0.487 + identical digest narrative across all four scenarios.
    # That broke demo credibility (a Fusion engineer immediately notices when
    # four "different" scenarios produce the exact same metric to 3 decimals).
    #
    # Real-study path: POST /api/v1/studies with a fixed Optuna seed
    # (config.seed=42) → Arq worker runs trials against the real ES backing
    # store → real metric_delta + LLM-generated digest emerge from the data.
    # Repeatable: same seed + same judgments + same docs + pinned ES version
    # = same numbers run after run.
    #
    # For acme specifically, ALSO create a second template (function_score
    # recency-decay shape) so the digest worker has a candidate it CAN suggest
    # as a swap_template followup. Whether the LLM actually picks it is up to
    # the digest prompt + the study's data — we don't fake it.
    if s["slug"] == "acme-products-prod":
        swap_template = post(
            "/query-templates",
            {
                "name": "function-score-recency-decay-v1",
                "engine_type": s["engine_type"],
                "body": json.dumps(
                    {
                        "query": {
                            "function_score": {
                                "query": {
                                    "multi_match": {
                                        "query": "{{ query_text }}",
                                        "fields": [
                                            "title^{{ title_boost }}",
                                            "description^{{ description_boost }}",
                                            "brand^2",
                                        ],
                                        "type": "best_fields",
                                    }
                                }
                            }
                        }
                    }
                ),
                "declared_params": s["template_declared_params"],
            },
        )
        print(f"  swap template: {swap_template['id']} (function-score-recency-decay-v1)")

    # Build search_space from the template's declared_params. Float params get
    # a [0.5, 5.0] log-uniform range — a sensible boost-shaped default that
    # spans both "weakened" and "amplified" extremes around the natural 1.0.
    search_space = {
        "params": {
            name: {"type": "float", "low": 0.5, "high": 5.0, "log": True}
            for name in s["template_declared_params"]
        }
    }
    study_create = post(
        "/studies",
        {
            "name": s["study_name"],
            "cluster_id": cluster_id,
            "target": s["target"],
            "template_id": template_id,
            "query_set_id": qset_id,
            "judgment_list_id": jlist_id,
            "search_space": search_space,
            "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
            "config": {
                "max_trials": 12,
                "parallelism": 2,
                "sampler": "tpe",
                "seed": 42,
            },
        },
    )
    study_id = study_create["id"]
    print(f"  study created: {study_id}, polling for completion...")
    # Poll the study until it reaches a terminal state. 3-minute ceiling per
    # study — 12 trials × 2 parallelism against a healthy local-ES should
    # finish in 30-60s; 3 min is a wide safety margin.
    deadline = time.time() + 180
    detail: dict = study_create
    while time.time() < deadline:
        detail = http("GET", f"{API}/studies/{study_id}")
        if detail["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(3)
    final_status = detail["status"]
    best_metric = detail.get("best_metric")
    print(f"  study: {study_id} ({final_status}, best_metric={best_metric})")
    if final_status != "completed":
        print("  WARNING: study did not complete; skipping digest wait")
    else:
        # Wait for the digest worker to land the digest + proposal. The worker
        # fires automatically on the completed-study transition; usually 5-15s
        # depending on LLM latency. 90s ceiling is a wide safety margin.
        #
        # The GET /studies/{id}/digest endpoint returns 404 with
        # `DIGEST_NOT_READY` (retryable) while the worker is still running;
        # any successful (HTTP 200) response means the digest landed. The
        # response shape is DigestResponse (proposals.py:293) which has no
        # "status" field — a successful return IS the ready signal.
        digest_deadline = time.time() + 90
        digest_landed = False
        while time.time() < digest_deadline:
            try:
                digest = http("GET", f"{API}/studies/{study_id}/digest", quiet_404=True)
                followups = digest.get("suggested_followups") or []
                kinds = ", ".join(f.get("kind", "?") for f in followups) or "(none)"
                print(f"  digest: {digest['id']} ({len(followups)} followups: {kinds})")
                digest_landed = True
                break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
            time.sleep(3)
        if not digest_landed:
            print("  WARNING: digest did not land within 90s")

    return {
        "slug": s["slug"],
        "cluster_id": cluster_id,
        "query_set_id": qset_id,
        "template_id": template_id,
        "judgment_list_id": jlist_id,
        "study_id": study_id,
        "study_name": s["study_name"],
    }


# ---------------------------------------------------------------------------
# Idempotency: wipe existing demo state before reseeding
# ---------------------------------------------------------------------------


def _psql(sql: str) -> None:
    """Run a SQL statement against the Compose postgres container."""
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "relyloop",
            "-d",
            "relyloop",
            "-c",
            sql,
        ],
        check=True,
        capture_output=True,
    )


def truncate_demo_state() -> None:
    """Wipe every demo-owned row from Postgres + every demo index from ES/OS.

    `TRUNCATE ... CASCADE` handles FK fanout from clusters → studies → trials,
    etc. The explicit table list is for operator-visible logging.
    """
    print("=== truncating demo state ===")
    tables = ", ".join(TRUNCATE_TABLES)
    print(f"  postgres: TRUNCATE {tables} RESTART IDENTITY CASCADE")
    _psql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE;")

    for idx in DEMO_ES_INDICES:
        print(f"  es: DELETE /{idx}")
        try:
            http("DELETE", f"{ES}/{idx}", auth=ES_AUTH)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

    for idx in DEMO_OS_INDICES:
        print(f"  os: DELETE /{idx}")
        try:
            http("DELETE", f"{OS}/{idx}", auth=OS_AUTH)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise


def apply_study_renames(results: list[dict]) -> None:
    """Apply the study-id → human-readable-name rename inline (no operator copy-paste)."""
    if not results:
        return
    print("\n=== renaming studies ===")
    for r in results:
        # study_name is from a closed set in SCENARIOS — safe to inline-escape.
        safe = r["study_name"].replace("'", "''")
        sql = f"UPDATE studies SET name = '{safe}' WHERE id = '{r['study_id']}';"
        _psql(sql)
        print(f"  {r['slug']}: {r['study_id']} → {r['study_name']}")


def confirm_wipe() -> bool:
    print("This will WIPE the dev Postgres demo state (clusters, studies,")
    print("query sets, query templates, judgment lists, judgments, trials,")
    print("digests, proposals) AND the corresponding ES/OS indices.")
    print()
    print("Use --force or `make seed-demo FORCE=1` to skip this prompt.")
    print()
    resp = input("Continue? [y/N] ").strip().lower()
    return resp in ("y", "yes")


# SQL used by count_existing_clusters() to decide whether `--if-empty`
# should auto-seed. MUST filter out soft-deleted rows (`deleted_at IS NULL`)
# so a single E2E test that soft-deletes its cluster fixtures doesn't
# permanently false-skip the auto-seed on every subsequent `make up`.
# Aligned with the public API's view: `/api/v1/clusters` returns only live
# rows, so the auto-seed gate must use the same definition of "exists".
# See bug_seed_demo_if_empty_counts_soft_deleted.
_COUNT_LIVE_CLUSTERS_SQL = "SELECT COUNT(*) FROM clusters WHERE deleted_at IS NULL;"


def count_existing_clusters(*, max_attempts: int = 30, backoff_s: float = 1.0) -> int | None:
    """Return the count of LIVE rows in the ``clusters`` table (i.e. with
    ``deleted_at IS NULL``), or ``None`` if the table can't be reached after
    ``max_attempts`` retries. Used by ``--if-empty`` to decide whether to seed.

    Bounded retry handles two transient races on a fresh ``make up``:
      * postgres container is healthy but psql connections briefly refuse
        immediately after start.
      * The ``relyloop-migrate-1`` one-shot service is still applying
        alembic migrations, so the ``clusters`` table doesn't exist yet
        (psql exits non-zero with ``relation "clusters" does not exist``).

    The default 30 attempts × 1s = 30s ceiling comfortably exceeds the
    typical fresh-stack migration window (~5-10s on a warm uv cache).
    GPT-5.5 PR #182 review finding #2 fix — without the retry, an empty
    fresh stack would emit "skipping (postgres not reachable)" and leave
    the operator on an empty stack with no auto-seed.

    Direct SQL via the existing ``_psql`` plumbing keeps this in lockstep
    with how the rest of the script reaches the DB; no extra deps needed.
    """
    last_err: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-U",
                    "relyloop",
                    "-d",
                    "relyloop",
                    "-tA",  # -t: tuples only, -A: unaligned
                    "-c",
                    _COUNT_LIVE_CLUSTERS_SQL,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return int(result.stdout.strip())
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            last_err = stderr or repr(exc)
            # The two failure modes we want to retry past: (a) connection
            # refused / role missing while postgres warms up, (b) "relation
            # 'clusters' does not exist" while migrate is still running.
            # Other failures (auth misconfig, dropped DB) won't recover from
            # waiting, but the bounded ceiling + non-fatal return ensures
            # we exit cleanly anyway.
            if attempt < max_attempts:
                time.sleep(backoff_s)
                continue
            print(
                f"seed-demo: clusters count probe failed after {max_attempts} "
                f"attempts; last error: {last_err}",
                file=sys.stderr,
            )
            return None
        except ValueError:
            # stdout wasn't an integer — psql succeeded but returned garbage;
            # treat as unrecoverable.
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--force",
        action="store_true",
        help="Skip the destructive-action prompt (use in automation / CI).",
    )
    ap.add_argument(
        "--if-empty",
        action="store_true",
        help=(
            "Only seed when the ``clusters`` table is empty. Used by "
            "``scripts/install.sh`` to auto-populate meaningful demo data on "
            "fresh stacks without clobbering an operator's existing state. "
            "Exits 0 with a notice when clusters already exist; exits 0 "
            "(non-fatal) when the DB isn't reachable yet."
        ),
    )
    args = ap.parse_args()

    if args.if_empty:
        existing = count_existing_clusters()
        if existing is None:
            # DB unreachable / schema not yet present / postgres still
            # starting. Don't fail `make up`; the operator can always run
            # `make seed-demo FORCE=1` manually after the stack stabilizes.
            print("seed-demo: skipping — postgres not reachable yet.")
            return 0
        if existing > 0:
            print(
                f"seed-demo: skipping — {existing} cluster(s) already exist. "
                "Use `make seed-demo FORCE=1` to wipe + reseed.",
            )
            return 0
        # Fresh stack: fall through with implicit force (TRUNCATE on an empty
        # table is a no-op, so the destructive prompt would just confuse the
        # `make up` first-run experience).
        print("seed-demo: stack is empty — auto-seeding meaningful demo data…")
        args.force = True

    if not args.force and not confirm_wipe():
        print("aborted.")
        return 1

    truncate_demo_state()

    results = []
    for s in SCENARIOS:
        try:
            results.append(seed_scenario(s))
        except Exception as exc:
            print(f"\n!! scenario {s['slug']} FAILED: {exc!r}")
            # GPT-5.5 PR #182 review finding #1 fix — partial-seed self-heal.
            # In --if-empty mode (auto-seed from `make up`), a mid-seed
            # failure would leave the `clusters` table non-empty, which
            # would make every subsequent `make up` skip the seed and
            # leave the operator on a broken half-seeded stack. Roll back
            # any rows we inserted so the next `make up` retries cleanly.
            # In explicit `make seed-demo` mode, leave the partial state
            # in place so the operator can inspect what landed before
            # re-running with --force.
            if args.if_empty:
                print(
                    "seed-demo: --if-empty mode — rolling back partial state "
                    "so the next `make up` can retry cleanly…",
                    file=sys.stderr,
                )
                try:
                    truncate_demo_state()
                except Exception as cleanup_exc:
                    print(
                        f"seed-demo: rollback also failed: {cleanup_exc!r}. "
                        "Run `make seed-demo FORCE=1` manually to recover.",
                        file=sys.stderr,
                    )
            return 1

    apply_study_renames(results)

    print("\n=== seed complete ===")
    for r in results:
        print(f"  {r['slug']}: study={r['study_id']} ({r['study_name']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
