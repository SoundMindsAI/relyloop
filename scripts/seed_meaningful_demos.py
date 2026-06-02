#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# ruff: noqa: E501, S101, S310, S603, S607, S608
#   E501 (line too long): scenario literals contain long product titles +
#                  news headlines + helper-text strings. Wrapping each one
#                  hurts readability more than it helps; this is a script,
#                  not library code.
#   S101 (assert): the module-level FR-8 invariant after SCENARIOS is a
#                  load-time guard — failing it MUST stop the seed before
#                  it writes the wrong demo data. assert is the right
#                  primitive; Story 2.1 covers the assertion in
#                  backend/tests/unit/scripts/test_scenarios_ubi_config.py.
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
import asyncio
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, cast

# Repo paths — used by the rich-data scenario (seed_rich_scenario below).
REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "samples"

API = "http://localhost:8000/api/v1"
ES = "http://localhost:9200"
ES_AUTH = ("elastic", "changeme")
OS = "http://localhost:9201"
OS_AUTH = ("admin", "admin")

# infra_adapter_solr Story A13: local Solr container.
# The local Compose Solr runs security-disabled (no security.json — same
# posture as the local ES/OpenSearch services). It accepts unauthenticated
# admin + query calls, so the BasicAuth tuple below is nominal: a
# security-disabled Solr simply ignores the Authorization header. The
# well-known "solr"/"solr" dev default matches install.sh's
# cluster_credentials.yaml entry.
SOLR = "http://localhost:8983"
SOLR_AUTH = ("solr", "solr")

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
# `acme-products-rich` is the 1000-doc ESCI index used by seed_rich_scenario.
# `ubi_queries` + `ubi_events` are added (Story 2.2 / FR-6) so the home-button
# reseed and `make seed-demo` both DELETE them at cleanup start before the
# synthetic UBI generator (FR-3) recreates them with the canonical mapping.
DEMO_ES_INDICES = (
    "products",
    "docs-articles",
    "job-listings",
    "acme-products-rich",
    "ubi_queries",
    "ubi_events",
)
DEMO_OS_INDICES = ("news-articles",)

# infra_adapter_solr Story A13: Solr-side demo collections. The reseed
# orchestrator drops + recreates these alongside the ES/OS indices so
# repeated reseeds stay clean. ubi_queries + ubi_events are shared with the
# ES side conceptually but live in Solr as separate physical collections.
DEMO_SOLR_COLLECTIONS = (
    "acme-kb-docs",
    "ubi_queries",
    "ubi_events",
)

# Rich-scenario tunables. Five queries × top-K LLM judgments per query keeps
# the LLM-judgment-generation step under ~60s and ~$0.05 with gpt-4o-mini.
RICH_SCENARIO_QUERY_COUNT = 5

# feat_studies_convergence_visibility Epic 2 Story 2.2 / FR-6 / D-11.
# Small-scenario per-study trial budget. Single-sourced here and imported by
# ``backend.app.services.demo_seeding`` (the home-button reseed path) so both
# the CLI ``make seed-demo`` and the home-button reseed dispatch the same
# 50-trial budget. Pinned at the convergence-classifier's
# ``STUDIES_TPE_WARMUP_FLOOR`` (50) — the minimum count at which the verdict
# can read ``converged`` / ``still_improving`` rather than ``too_few_trials``.
# The rich-scenario budget stays at 15 (see _RICH_SCENARIO_MAX_TRIALS in
# demo_seeding.py) — the rich ESCI scenario already shows real lift at 15
# trials and a higher budget materially extends the demo-seed wall-clock
# (D-9).
DEMO_SMALL_STUDY_MAX_TRIALS: Final[int] = 50


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


def _days_ago_iso(days: float) -> str:
    """Return an ISO-8601 UTC timestamp ``days`` before module-load time.

    Used by the news-search-staging + jobs-marketplace-prod scenarios so the
    freshness-decay function_score wrappers (``gauss``/``exp`` with
    ``origin: now``) see relevant decay factors at headroom-test time and at
    operator-seed time. If we hardcode an ISO string, the decay multiplier
    converges to zero a few weeks after the date and the harness scores
    every doc at zero — masking the data-design quality the test guards.

    **Determinism trade-off** (GPT-5.5 cycle-1 F3 — accepted as comment):
    these timestamps are NOT fixed at module load — they shift by one day
    each calendar day relative to the engine's ``origin: now``. The
    RELATIVE distance between best-answer docs (closer to ``now``) and
    decoy docs (further from ``now``) is preserved, so the ranking
    monotonicity is stable. The headroom-test bounds carry comfortable
    margins (≥ +0.23 lift across the 5 scenarios per the Story 2.1
    enrichment run), so the small per-day freshness-decay shift does
    not flap the binary headroom outcome. The trade is intentional:
    relative dates keep the operator-facing ``make seed-demo`` output
    plausible (news with a stale 2025 date would read as broken to an
    evaluator running the demo in 2027) and the harness test is
    deterministic over short time windows. If a future flake surfaces,
    the fix is a fixed-anchor strategy (e.g., monkey-patching ``now`` in
    the freshness function or freezing the test clock).
    """
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


SCENARIOS: list[dict[str, Any]] = [
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
            # Data-design recipe (see test_demo_scenarios_headroom.py for the
            # FR-5 bounds the harness asserts):
            #
            # - Each query has a "decoy" doc whose TITLE is essentially the
            #   query string verbatim (5-7 tokens, ~90%+ are query tokens) and
            #   whose description is a one-line shipping-style blurb with
            #   ZERO query terms. Short title + dense match = very high BM25.
            #
            # - The "best answer" doc has a GENERIC marketing title with NO
            #   query terms; its long-ish description mentions each query term
            #   exactly ONCE inside a wall of marketing copy. Long field +
            #   sparse match = low BM25 per field.
            #
            # - To prevent cross-query contamination, each best-answer
            #   description's query-vocab is DISTINCT — no best-answer doc
            #   contains another query's query terms (e.g. p1001 doesn't
            #   mention "ear" / "sony" / "running", and p5001 doesn't mention
            #   "headphones"). This keeps each query's qrels honest.
            #
            # - With BM25 best_fields and equal-midpoint baseline (B1=B2=1.58),
            #   the decoy's short-title-dense-match outscores the best-answer's
            #   long-description-sparse-match → decoy ranks #1 → low NDCG@10
            #   (~0.45). When title_boost drops to 0.5 and description_boost
            #   rises to 5.0, the 10x weight shift flips the order →
            #   best-answer ranks #1 → NDCG@10 climbs ~0.30.
            # === q0 "wireless noise cancelling headphones" ===
            # BEST ANSWER (rating=3): generic title, query terms each appear ONCE in a ~90-word description.
            {
                "id": "p1001",
                "doc": {
                    "title": "Sony WH-1000XM5 Premium Travel Companion",
                    "description": "Reference-grade audio fidelity with plush memory foam pads, thirty hour battery life, and adaptive ambient mode for travelers. The flagship model in the WH series. Bluetooth multipoint pairing lets the device switch between a laptop and a phone session without re-pairing. Active noise cancelling uses eight microphones plus a dedicated processor. Includes a rigid molded case, USB-C cable, and inflight airplane adapter. The wireless connection holds at thirty feet line of sight from the source. These headphones suit long commutes and home listening alike.",
                    "brand": "Sony",
                    "category": "audio",
                    "price": 399.99,
                },
            },
            # DECOY (rating=1): title is essentially the query.
            {
                "id": "p1002",
                "doc": {
                    "title": "Wireless Noise Cancelling Headphones Pouch",
                    "description": "Black fabric carry pouch. Microfiber lining. Drawstring closure. Sold separately.",
                    "brand": "Generic",
                    "category": "accessory",
                    "price": 19.00,
                },
            },
            # DISTRACTOR (rated 0) — additional title-match that competes at baseline.
            {
                "id": "p1005",
                "doc": {
                    "title": "Wireless Noise Cancelling Headphones Sticker Pack",
                    "description": "Vinyl die-cut stickers. Pack of ten. Variety of designs for laptops.",
                    "brand": "Generic",
                    "category": "accessory",
                    "price": 7.00,
                },
            },
            # OKAY (rating=2)
            {
                "id": "p1003",
                "doc": {
                    "title": "Bose QuietComfort Ultra Audio Set",
                    "description": "Premium audio model with active sound dampening technology built in. Long battery life and adaptive ambient profile for travel commutes. Pairs with iOS and Android phones via the included companion app. Foldable hinges save space in the included carry case.",
                    "brand": "Bose",
                    "category": "audio",
                    "price": 429.00,
                },
            },
            # WRONG (rating=0)
            {
                "id": "p1004",
                "doc": {
                    "title": "USB-C Charging Pad Aluminum Base",
                    "description": "Fifteen watt fast charging pad for phones and earbuds. Aluminum heat-sink base. Includes USB-C cable but no wall adapter. LED indicator lights when a device aligns properly.",
                    "brand": "Anker",
                    "category": "accessory",
                    "price": 29.00,
                },
            },
            # === q1 "womens running shoes" ===
            # BEST ANSWER (rating=3)
            {
                "id": "p2001",
                "doc": {
                    "title": "Nike Pegasus 41 Performance Trainer",
                    "description": "Daily trainer designed for womens distance work. The Pegasus 41 builds on twenty years of the Pegasus story with a redesigned upper, a refined Air Zoom unit, and a workhorse fit. The forefoot uses ReactX foam for energy return; the heel collar is gusseted to lock the foot in place. These running flats hold up across road and packed gravel surfaces. Heel-to-toe drop is ten millimeters. Sized for the female foot last specifically; ladies sizing chart runs US five through US twelve. Suitable shoes for tempo days or recovery jogs.",
                    "brand": "Nike",
                    "category": "footwear",
                    "price": 140.00,
                },
            },
            # DECOY (rating=1)
            {
                "id": "p2002",
                "doc": {
                    "title": "Womens Running Shoes Display Box",
                    "description": "Retail merchandise display stand. Holds one pair. Cardboard construction.",
                    "brand": "Generic",
                    "category": "accessory",
                    "price": 12.00,
                },
            },
            # DISTRACTOR (rated 0) — title-match competitor.
            {
                "id": "p2005",
                "doc": {
                    "title": "Womens Running Shoes Care Spray",
                    "description": "Deodorizing spray. Eight ounce bottle. Lavender scent. Use weekly after activity.",
                    "brand": "Generic",
                    "category": "accessory",
                    "price": 9.00,
                },
            },
            # OKAY (rating=2)
            {
                "id": "p2003",
                "doc": {
                    "title": "Brooks Ghost 16 Performance Pair",
                    "description": "Womens running trainer with neutral cushioning and a smooth transition. DNA LOFT v3 midsole offers softer underfoot feel without sacrificing rebound. Engineered air mesh upper for breathability. Suitable for daily training and recovery work.",
                    "brand": "Brooks",
                    "category": "footwear",
                    "price": 145.00,
                },
            },
            # WRONG (rating=0)
            {
                "id": "p2004",
                "doc": {
                    "title": "Mens Hiking Boots Heavy Duty",
                    "description": "Waterproof full grain leather mens hiking boots for backcountry trails. Vibram outsole, gusseted tongue, ankle cuff.",
                    "brand": "Merrell",
                    "category": "footwear",
                    "price": 180.00,
                },
            },
            # === q2 "kitchen knife set" ===
            # BEST ANSWER (rating=3)
            {
                "id": "p3001",
                "doc": {
                    "title": "Wüsthof Classic 8-Piece Chef Collection",
                    "description": "Forged in Solingen Germany from a single piece of high carbon stainless steel. The collection includes an eight inch chef blade, a six inch utility blade, a three point five inch paring blade, an eight inch serrated bread blade, a pair of culinary shears, a honing rod, and a six-slot wooden block. A registration card for the lifetime warranty is included. Triple riveted polymer handles offer secure grip even when wet. Each kitchen blade is sharpened to a fourteen degree edge. This is the complete chef set, ready for gifting; the knife block fits standard countertops.",
                    "brand": "Wüsthof",
                    "category": "kitchen",
                    "price": 549.00,
                },
            },
            # DECOY (rating=1)
            {
                "id": "p3002",
                "doc": {
                    "title": "Kitchen Knife Set Magnetic Strip",
                    "description": "Wall-mount magnetic strip. Sold separately. Stainless backplate.",
                    "brand": "IKEA",
                    "category": "accessory",
                    "price": 14.00,
                },
            },
            # DISTRACTOR (rated 0) — title-match competitor.
            {
                "id": "p3004",
                "doc": {
                    "title": "Kitchen Knife Set Drawer Insert Tray",
                    "description": "Bamboo organizer tray for drawer storage. Holds twelve blades upright. Sold separately.",
                    "brand": "Generic",
                    "category": "accessory",
                    "price": 22.00,
                },
            },
            # OKAY (rating=2)
            {
                "id": "p3003",
                "doc": {
                    "title": "Henckels Forged Cutlery Block Bundle",
                    "description": "Affordable kitchen blade set with shears, sharpener, and storage block. Stainless steel blades. Six pieces total. Suitable for everyday home use. Hand washing recommended for blade longevity.",
                    "brand": "Henckels",
                    "category": "kitchen",
                    "price": 199.00,
                },
            },
            # === q3 "sony headphones" — brand field is fixed at ^2 ===
            # BEST ANSWER (rating=3): brand=Sony, title has NO "sony" or "headphones"; description mentions them once each.
            {
                "id": "p4001",
                "doc": {
                    "title": "WH-1000XM5 Flagship Premium Audio Device",
                    "description": "The flagship sony model in the WH lineup. Audio engineers ranked this device best-in-class for active sound dampening in three independent reviews. Owners report all-day comfort, multipoint pairing, and an in-app equalizer with custom listening profiles. Compatible accessories include the rigid carrying case, a three point five millimeter audio cable for wired use, and an inflight adapter. The companion app pushes firmware updates over the air directly. A class-leading thirty hour battery sustains long flights. Premium spec headphones at a flagship price point.",
                    "brand": "Sony",
                    "category": "audio",
                    "price": 399.99,
                },
            },
            # DECOY (rating=1): title is the query, description is short.
            {
                "id": "p4002",
                "doc": {
                    "title": "Sony Headphones Replacement Earpads",
                    "description": "Aftermarket replacement pads. Foam and leatherette construction. Two-pad pack.",
                    "brand": "Geekria",
                    "category": "accessory",
                    "price": 18.00,
                },
            },
            # DISTRACTOR (rated 0) — title-match competitor.
            {
                "id": "p4004",
                "doc": {
                    "title": "Sony Headphones Travel Wall Mount",
                    "description": "Aluminum wall mount. Adhesive backing. Fits most full-size cans.",
                    "brand": "Mountain",
                    "category": "accessory",
                    "price": 12.00,
                },
            },
            # WRONG (rating=0)
            {
                "id": "p4003",
                "doc": {
                    "title": "Apple AirPods Pro Carrying Case",
                    "description": "Silicone case for the Apple AirPods Pro charging case. Tether loop attaches to a backpack zipper. Available in five colors.",
                    "brand": "Apple",
                    "category": "accessory",
                    "price": 9.00,
                },
            },
            # === q4 "noise cancelling over ear" ===
            # BEST ANSWER (rating=3)
            {
                "id": "p5001",
                "doc": {
                    "title": "Bose QuietComfort Ultra Premium Audio Cans",
                    "description": "Premium audio cushions seal out cabin and street sound. The cancelling profile adapts as you move from a quiet office to a busy commuter train; over fit cup geometry distributes pressure around the temple area for fatigue-free wear during eight hour flights. Three preset cancelling levels plus a custom level configurable in the companion app. A wired fallback listening mode is available when the battery is depleted. Travel pouch included. The microphone array supports clear call quality with noise suppression on the outbound voice path. Includes a USB-C cable for charging.",
                    "brand": "Bose",
                    "category": "audio",
                    "price": 429.00,
                },
            },
            # DECOY (rating=1)
            {
                "id": "p5002",
                "doc": {
                    "title": "Noise Cancelling Over Ear Pad Replacement",
                    "description": "Aftermarket memory foam pad pair.",
                    "brand": "Geekria",
                    "category": "accessory",
                    "price": 16.00,
                },
            },
            # DISTRACTOR (rated 0) — title-match competitor.
            {
                "id": "p5004",
                "doc": {
                    "title": "Noise Cancelling Over Ear Cleaning Kit",
                    "description": "Microfiber cloth, brush, gentle alcohol-free solution. Pack of three.",
                    "brand": "Generic",
                    "category": "accessory",
                    "price": 11.00,
                },
            },
            # WRONG (rating=0)
            {
                "id": "p5003",
                "doc": {
                    "title": "In-Ear Sport Earbuds Waterproof",
                    "description": "Compact in-ear sport earbuds with secure-fit hooks. IPX7 rated. Six hour battery in the buds, twenty four total with the charging case. Available in black, white, lime, and red. USB-C charging.",
                    "brand": "JBL",
                    "category": "audio",
                    "price": 79.00,
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
        # query_idx → doc_id → rating. Each query spans >=3 distinct rating
        # values across {0,1,2,3} so the qrels expose real ranking headroom
        # (Story 2.3 shape invariant). The pXXX5 / pXXX4 docs are
        # title-match "distractors" rated 0 — they crowd out the best-answer
        # at the equal-baseline midpoint, which is what gives the title-vs-
        # description boost knob a real signal to optimize against.
        "judgments_map": [
            # q0 "wireless noise cancelling headphones"
            (0, "p1001", 3),  # best — query in description
            (0, "p1002", 1),  # decoy — query densely in title
            (0, "p1003", 2),  # okay
            (0, "p1004", 0),  # wrong
            (0, "p1005", 0),  # distractor — title-match accessory
            # q1 "womens running shoes"
            (1, "p2001", 3),
            (1, "p2002", 1),
            (1, "p2003", 2),
            (1, "p2004", 0),
            (1, "p2005", 0),  # distractor — title-match accessory
            # q2 "kitchen knife set"
            (2, "p3001", 3),
            (2, "p3002", 1),
            (2, "p3003", 2),
            (2, "p2004", 0),
            (2, "p3004", 0),  # distractor — title-match accessory
            # q3 "sony headphones"
            (3, "p4001", 3),
            (3, "p4002", 1),
            (3, "p1001", 2),  # also a sony headphone
            (3, "p4003", 0),
            (3, "p4004", 0),  # distractor — title-match accessory
            # q4 "noise cancelling over ear"
            (4, "p5001", 3),
            (4, "p5002", 1),
            (4, "p1003", 2),  # bose nc over-ear
            (4, "p5003", 0),
            (4, "p5004", 0),  # distractor — title-match accessory
        ],
        "study_name": "tune-product-title-boost-baseline",
        # UBI demo config (FR-8 / D-2). Synthetic UBI is seeded for this
        # scenario by the reseed orchestrator so the rung classifier reports
        # rung_3 and the CTR-threshold converter has signal to grade against.
        # ubi_target_rung values match `UbiReadinessRung` at
        # backend/app/services/ubi_readiness.py; ubi_converter values match
        # `UbiConverterKind` at backend/app/api/v1/schemas.py:846.
        "ubi_target_rung": "rung_3",
        "ubi_converter": "ctr_threshold",
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
        # Data-design recipe (same as acme-products-prod above; see that
        # docstring for the full rationale). corp-docs only exposes
        # title_boost, so the lever is "title weight vs fixed body weight."
        # Decoys put the operator-question phrasing in the title; best
        # answers carry the actual instructions in the body and a generic
        # topical title.
        "docs": [
            # === q0 "how do I reset my password" ===
            # BEST ANSWER (rating=3): topic-only title, instructions in body.
            {
                "id": "d101",
                "doc": {
                    "title": "Account Recovery Workflow Reference",
                    "body": "Operators who need to reset their forgotten password can do so through the self-serve recovery surface. From the sign-in screen, click the 'Forgot password' link and an email arrives within thirty seconds containing a single-use recovery link. Follow the link in the email and supply a new credential meeting the eight-character minimum. The link expires after thirty minutes for security; request a new email if the first one lapses. Operators on enterprise plans must additionally re-authenticate via SSO after the credential is updated. After successful update, all existing sessions are signed out as a precaution and the operator must sign in again on each device.",
                    "section": "account",
                },
            },
            # DECOY (rating=1): title is the query, body is short.
            {
                "id": "d102",
                "doc": {
                    "title": "How To Reset My Password Sticker",
                    "body": "Adhesive label sheet for laptops. Pack of ten.",
                    "section": "swag",
                },
            },
            # OKAY (rating=2)
            {
                "id": "d103",
                "doc": {
                    "title": "Changing Your Password On A Trusted Device",
                    "body": "After signing in, open Settings → Account → Credentials. Enter the current password once and the new one twice. The change takes effect immediately on the current device; other devices sign out within two minutes.",
                    "section": "account",
                },
            },
            # DISTRACTOR (rated 0) — title-match accessory.
            {
                "id": "d104",
                "doc": {
                    "title": "How Do I Reset My Password Coffee Mug",
                    "body": "Ceramic mug, 12 oz. Dishwasher safe. Black exterior, white lettering.",
                    "section": "swag",
                },
            },
            # === q1 "enable 2fa" ===
            # BEST ANSWER (rating=3)
            {
                "id": "d201",
                "doc": {
                    "title": "Multi-Factor Security Setup Reference",
                    "body": "Operators on any plan can enable 2fa from the security settings surface. Open Settings, then choose Security, then the Multi-Factor section. Choose either an authenticator app such as Authy or a hardware key over the FIDO2 protocol. Scan the displayed QR code with the chosen app and enter the six-digit confirmation code. Backup recovery codes are generated automatically; print or save them to an offline password manager. Once confirmed, the operator must supply both the password and a fresh authenticator code at every sign-in attempt.",
                    "section": "account",
                },
            },
            # DECOY (rating=1)
            {
                "id": "d202",
                "doc": {
                    "title": "Enable 2fa Quick-Reference Card",
                    "body": "Printed pocket card for new hires. Six-pack laminated.",
                    "section": "swag",
                },
            },
            # OKAY (rating=2)
            {
                "id": "d203",
                "doc": {
                    "title": "Hardware Security Key Pairing Guide",
                    "body": "Pair a YubiKey or Titan key with the workspace by selecting Add Security Key in Settings. Plug in the key when prompted and touch it. Once paired the key acts as a second authentication factor; you can enable 2fa enforcement at the workspace level afterwards.",
                    "section": "account",
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "d204",
                "doc": {
                    "title": "Enable 2fa Hoodie Black Embroidered",
                    "body": "Cotton blend hoodie. Sizes S through XXL.",
                    "section": "swag",
                },
            },
            # === q2 "slack integration setup" ===
            # BEST ANSWER (rating=3)
            {
                "id": "d301",
                "doc": {
                    "title": "Channel Notification Wiring Reference",
                    "body": "From the workspace settings surface, navigate to the Integrations area and choose Add. Select Slack from the catalogue list and authorize the app in your target workspace using the OAuth flow. Pick a default channel for system messages and an alternate channel for noisy event types. The setup completes within ten seconds; verify by triggering a test event from the same surface. Each operator's outbound messages from this workspace land in the chosen channel with the operator's display name attached.",
                    "section": "integrations",
                },
            },
            # DECOY (rating=1)
            {
                "id": "d302",
                "doc": {
                    "title": "Slack Integration Setup Sticker",
                    "body": "Vinyl die-cut sticker. Three-color print.",
                    "section": "swag",
                },
            },
            # OKAY (rating=2)
            {
                "id": "d303",
                "doc": {
                    "title": "Cross-Workspace Bot Permission Model",
                    "body": "When the Slack app is authorized, the bot is added to the chosen channel with limited scopes. Expand scopes by re-running the integration setup and selecting additional event types.",
                    "section": "integrations",
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "d304",
                "doc": {
                    "title": "Slack Integration Setup T-Shirt",
                    "body": "Soft-cotton tee. Available in black or navy.",
                    "section": "swag",
                },
            },
            # === q3 "github webhook" ===
            # BEST ANSWER (rating=3)
            {
                "id": "d401",
                "doc": {
                    "title": "Repository Event Notification Wiring",
                    "body": "Repository-level event notifications let your team channel receive a message on every push and pull request. Go to the repository settings on github, then open the Webhook area, click Add. Paste the URL provided by the integrations panel and choose the events of interest. The webhook signature secret is generated automatically and stored encrypted; rotate it from the same surface every quarter. Inbound github events arrive within two seconds of the upstream push under normal load.",
                    "section": "integrations",
                },
            },
            # DECOY (rating=1)
            {
                "id": "d402",
                "doc": {
                    "title": "Github Webhook Conference Lanyard",
                    "body": "Polyester lanyard. Quick-release clip.",
                    "section": "swag",
                },
            },
            # OKAY (rating=2)
            {
                "id": "d403",
                "doc": {
                    "title": "Verifying Inbound Signed Payloads",
                    "body": "Each inbound delivery from github carries an HMAC signature header. Compute the same HMAC on the receiver side using the shared secret and compare. Reject mismatched payloads. The same pattern applies to the webhook receiver for other providers.",
                    "section": "integrations",
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "d404",
                "doc": {
                    "title": "Github Webhook Mug Ceramic",
                    "body": "Coffee mug. Twelve ounce. Hand wash recommended.",
                    "section": "swag",
                },
            },
            # === q4 "export data csv" ===
            # BEST ANSWER (rating=3)
            {
                "id": "d501",
                "doc": {
                    "title": "Workspace Information Outbound Transfer",
                    "body": "From the admin console, choose the Data area and then Export. Select the desired format (csv or json), the date range you care about, and the resource families to include. The export runs asynchronously and the operator receives an email when the file is ready, typically within five minutes. Large workspaces can request a multipart export with one file per resource family; the data is delivered to a signed download URL valid for forty-eight hours. csv files use UTF-8 encoding with comma delimiters and embedded-quote escaping.",
                    "section": "data",
                },
            },
            # DECOY (rating=1)
            {
                "id": "d502",
                "doc": {
                    "title": "Export Data Csv Quick-Reference Magnet",
                    "body": "Refrigerator magnet. Three-inch round.",
                    "section": "swag",
                },
            },
            # OKAY (rating=2)
            {
                "id": "d503",
                "doc": {
                    "title": "Scheduled Outbound Information Transfers",
                    "body": "Set up a recurring weekly outbound transfer from the admin console. Choose the resources, the format, and the delivery destination (email or S3 bucket). Each run produces a fresh file with the same schema as the on-demand export.",
                    "section": "data",
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "d504",
                "doc": {
                    "title": "Export Data Csv Conference Tote Bag",
                    "body": "Canvas tote. Reinforced handles. Black on white print.",
                    "section": "swag",
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
            # q0 "how do I reset my password"
            (0, "d101", 3),  # best — body has full recovery flow
            (0, "d102", 1),  # decoy — title-match swag
            (0, "d103", 2),  # okay — adjacent password-change article
            (0, "d104", 0),  # distractor — title-match swag
            # q1 "enable 2fa"
            (1, "d201", 3),
            (1, "d202", 1),
            (1, "d203", 2),
            (1, "d204", 0),
            # q2 "slack integration setup"
            (2, "d301", 3),
            (2, "d302", 1),
            (2, "d303", 2),
            (2, "d304", 0),
            # q3 "github webhook"
            (3, "d401", 3),
            (3, "d402", 1),
            (3, "d403", 2),
            (3, "d404", 0),
            # q4 "export data csv"
            (4, "d501", 3),
            (4, "d502", 1),
            (4, "d503", 2),
            (4, "d504", 0),
        ],
        "study_name": "reduce-fuzziness-helpcenter-search",
        # UBI demo config (FR-8 / D-2). corp targets rung_1 (sparse signal) +
        # hybrid converter so the LLM fills the long tail past CTR-only
        # coverage. See acme entry above for the source-of-truth pointers.
        "ubi_target_rung": "rung_1",
        "ubi_converter": "hybrid_ubi_llm",
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
        # Data-design recipe (same as acme-products-prod above). news-search
        # only exposes title_boost, so the lever is "title weight vs fixed
        # body weight." Decoys put the headline phrasing in the title; best
        # answers carry the lede paragraph in the body and a generic topical
        # title. published_at uses _days_ago_iso() so freshness-decay scores
        # stay above zero at headroom-test runtime (otherwise the gauss decay
        # function in the template multiplies every score to ~0 and the
        # ranking is meaningless).
        "docs": [
            # === q0 "fed interest rate decision" ===
            # BEST ANSWER (rating=3): topic title, body carries the query terms.
            {
                "id": "n101",
                "doc": {
                    "title": "Central Bank Holds Steady Amid Mixed Inflation Signals",
                    "body": "The Federal Reserve announced today that it would maintain its benchmark interest rate at the current level, the third such decision this year. Officials cited easing but still-elevated inflation, a softening but firm labor market, and uncertainty around the impact of tariffs. The decision was unanimous. Markets had widely expected the central bank to hold, and equities ended the session roughly flat. Members of the committee signaled openness to a rate cut at the next meeting if inflation continues to slow; one member suggested the hurdle for a cut was lower than it has been in months.",
                    "topic": "economy",
                    "published_at": _days_ago_iso(1),
                },
            },
            # DECOY (rating=1)
            {
                "id": "n102",
                "doc": {
                    "title": "Fed Interest Rate Decision Coverage Photo Gallery",
                    "body": "Photo gallery from the press conference. Twelve images.",
                    "topic": "economy",
                    "published_at": _days_ago_iso(2),
                },
            },
            # OKAY (rating=2)
            {
                "id": "n103",
                "doc": {
                    "title": "Bond Markets React To Steady Monetary Policy Posture",
                    "body": "Treasury yields ticked lower after the central bank held its benchmark rate. Two-year yields fell by three basis points; ten-year yields slipped by two basis points.",
                    "topic": "economy",
                    "published_at": _days_ago_iso(1),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "n104",
                "doc": {
                    "title": "Fed Interest Rate Decision Trivia Night Sponsor Spotlight",
                    "body": "Sponsored content from a local pub trivia series.",
                    "topic": "economy",
                    "published_at": _days_ago_iso(3),
                },
            },
            # === q1 "tech layoffs Q4" ===
            # BEST ANSWER (rating=3)
            {
                "id": "n201",
                "doc": {
                    "title": "Workforce Reductions Slow At Major Software Firms",
                    "body": "Major technology employers reported a notable slowdown in workforce reductions during Q4, according to filings reviewed by analysts. The pace of tech layoffs across the largest software, semiconductor, and cloud-services firms fell to roughly forty percent of the Q3 rate. Net hiring at the same employers remains subdued; openings in core engineering ladders are flat year-over-year, while openings in AI-adjacent roles continue to grow. Recruiters surveyed expect the slowdown to persist into Q1.",
                    "topic": "tech",
                    "published_at": _days_ago_iso(2),
                },
            },
            # DECOY (rating=1)
            {
                "id": "n202",
                "doc": {
                    "title": "Tech Layoffs Q4 Statistics Infographic Tweet Thread",
                    "body": "Social media thread. Twelve embedded charts.",
                    "topic": "tech",
                    "published_at": _days_ago_iso(2),
                },
            },
            # OKAY (rating=2)
            {
                "id": "n203",
                "doc": {
                    "title": "Hiring Mix Shifts Toward Machine Learning Roles",
                    "body": "Software firms continued to grow their AI staff in the fourth quarter even as broader headcount fell. Recruiters say the trend is most pronounced at large vendors.",
                    "topic": "tech",
                    "published_at": _days_ago_iso(3),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "n204",
                "doc": {
                    "title": "Tech Layoffs Q4 Themed Halloween Costume Roundup",
                    "body": "Cultural commentary roundup. Fifteen costumes ranked.",
                    "topic": "tech",
                    "published_at": _days_ago_iso(4),
                },
            },
            # === q2 "climate summit geneva" ===
            # BEST ANSWER (rating=3)
            {
                "id": "n301",
                "doc": {
                    "title": "World Leaders Convene For Major Emissions Talks",
                    "body": "Heads of state from over ninety countries gathered in Geneva today for the opening session of the most consequential climate summit in three years. The talks are expected to focus on the next phase of global emissions reductions, including binding targets for the largest emitters and a new finance mechanism for adaptation. Delegates from the host nation framed the summit as a turning point; Geneva officials estimate the conference will draw more than fifteen thousand attendees over its ten-day run.",
                    "topic": "climate",
                    "published_at": _days_ago_iso(1),
                },
            },
            # DECOY (rating=1)
            {
                "id": "n302",
                "doc": {
                    "title": "Climate Summit Geneva Souvenir Pin Set",
                    "body": "Official commemorative enamel pin set. Twelve pins.",
                    "topic": "climate",
                    "published_at": _days_ago_iso(2),
                },
            },
            # OKAY (rating=2)
            {
                "id": "n303",
                "doc": {
                    "title": "Adaptation Finance Mechanism Draft Released",
                    "body": "Negotiators released a draft of the proposed adaptation finance mechanism on the second day of the conference. The draft includes both grant and concessional-loan components and contemplates a sliding contribution scale based on cumulative historical emissions.",
                    "topic": "climate",
                    "published_at": _days_ago_iso(1),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "n304",
                "doc": {
                    "title": "Climate Summit Geneva Tote Bag Limited Edition",
                    "body": "Eco-cotton tote bag in two colorways.",
                    "topic": "climate",
                    "published_at": _days_ago_iso(3),
                },
            },
            # === q3 "renewable energy 2025" ===
            # BEST ANSWER (rating=3)
            {
                "id": "n401",
                "doc": {
                    "title": "New Generation Capacity Hits Record Across The Year",
                    "body": "Solar and wind installations together accounted for the overwhelming majority of new electricity generation capacity added during 2025, a year-end industry report concludes. Renewable additions outpaced new fossil capacity by a ratio of roughly nine to one. Battery storage paired with solar grew faster than any other technology in the renewable energy category; analysts now project that energy storage will represent more than thirty percent of all new utility-scale capacity in 2026.",
                    "topic": "climate",
                    "published_at": _days_ago_iso(2),
                },
            },
            # DECOY (rating=1)
            {
                "id": "n402",
                "doc": {
                    "title": "Renewable Energy 2025 Calendar Wallchart",
                    "body": "Wall-mounted calendar. Twelve full-color pages.",
                    "topic": "climate",
                    "published_at": _days_ago_iso(3),
                },
            },
            # OKAY (rating=2)
            {
                "id": "n403",
                "doc": {
                    "title": "Battery Storage Pairings Lead Utility Buildouts",
                    "body": "Utility procurement filings show that storage paired with solar accounted for nearly a third of all new build approvals in the second half of the year. Standalone storage projects also continued to grow.",
                    "topic": "climate",
                    "published_at": _days_ago_iso(2),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "n404",
                "doc": {
                    "title": "Renewable Energy 2025 Conference Photo Compilation",
                    "body": "Photo gallery from industry conferences. One hundred images.",
                    "topic": "climate",
                    "published_at": _days_ago_iso(4),
                },
            },
            # === q4 "quantum computing breakthrough" ===
            # BEST ANSWER (rating=3)
            {
                "id": "n501",
                "doc": {
                    "title": "Error-Correction Milestone Demonstrated On 100-Qubit System",
                    "body": "Researchers at a leading lab demonstrated stable error-correction protocols running continuously on a 100-qubit superconducting system, a major step that observers are calling the most significant quantum computing breakthrough since the supremacy demonstrations of the previous decade. The team reported logical-qubit error rates two orders of magnitude below the underlying physical-qubit rate. Independent groups have replicated portions of the result within the past week.",
                    "topic": "tech",
                    "published_at": _days_ago_iso(1),
                },
            },
            # DECOY (rating=1)
            {
                "id": "n502",
                "doc": {
                    "title": "Quantum Computing Breakthrough Poster Print",
                    "body": "Large-format wall poster. Eighteen by twenty four inches.",
                    "topic": "tech",
                    "published_at": _days_ago_iso(2),
                },
            },
            # OKAY (rating=2)
            {
                "id": "n503",
                "doc": {
                    "title": "Logical-Qubit Error Rates Reach New Low",
                    "body": "A separate research group reported logical-qubit error rates that align with the headline result from earlier this week. The replication strengthens the case that error-correction at scale is becoming practical.",
                    "topic": "tech",
                    "published_at": _days_ago_iso(2),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "n504",
                "doc": {
                    "title": "Quantum Computing Breakthrough Sticker Pack",
                    "body": "Vinyl die-cut sticker pack. Eight unique designs.",
                    "topic": "tech",
                    "published_at": _days_ago_iso(3),
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
            # q0 "fed interest rate decision"
            (0, "n101", 3),
            (0, "n102", 1),
            (0, "n103", 2),
            (0, "n104", 0),
            # q1 "tech layoffs Q4"
            (1, "n201", 3),
            (1, "n202", 1),
            (1, "n203", 2),
            (1, "n204", 0),
            # q2 "climate summit geneva"
            (2, "n301", 3),
            (2, "n302", 1),
            (2, "n303", 2),
            (2, "n304", 0),
            # q3 "renewable energy 2025"
            (3, "n401", 3),
            (3, "n402", 1),
            (3, "n403", 2),
            (3, "n404", 0),
            # q4 "quantum computing breakthrough"
            (4, "n501", 3),
            (4, "n502", 1),
            (4, "n503", 2),
            (4, "n504", 0),
        ],
        "study_name": "add-7day-freshness-decay-news",
        # UBI demo config (FR-8 / D-2). news-search-staging is the negative
        # case — no synthetic UBI; rung classifier reports rung_0 so the
        # on-ramp nudge surface stays demonstrable.
        "ubi_target_rung": None,
        "ubi_converter": None,
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
        # Data-design recipe (same as acme-products-prod above). jobs exposes
        # title_boost + company_boost; description weight is fixed at 1.0.
        # Decoys put the role string in the title (and use a low-prestige
        # company name); the best answers carry the actual role spec in the
        # description and use generic role-family titles. posted_at uses
        # _days_ago_iso() so the exp decay (scale=30d) keeps multipliers
        # ~uniform across the small panel (every doc is 1-7 days old →
        # multiplier ~0.95+).
        "docs": [
            # === q0 "senior software engineer backend" ===
            # BEST ANSWER (rating=3): topical title, role spec in description.
            {
                "id": "j101",
                "doc": {
                    "title": "Stripe Infrastructure Posting (L5)",
                    "company": "Stripe",
                    "location": "San Francisco, CA",
                    "description": "Stripe is hiring a senior software engineer for the core backend group. The successful candidate will lead the build and operation of the central payments-processing stack serving millions of transactions per day. Stack is mostly Go with a Python control plane. Prior senior engineer experience required (six or more years). Backend systems design background expected. We expect the engineer to mentor mid-level peers on the team. The senior backend role reports to the engineering manager of the platform group.",
                    "posted_at": _days_ago_iso(2),
                },
            },
            # DECOY (rating=1): title is the query.
            {
                "id": "j102",
                "doc": {
                    "title": "Senior Software Engineer Backend Greeter",
                    "company": "ConferenceCo",
                    "location": "Remote",
                    "description": "Greet incoming attendees at our developer conference.",
                    "posted_at": _days_ago_iso(3),
                },
            },
            # EXTRA DISTRACTOR (rated 0) — extra title-match competitor on q0.
            {
                "id": "j105",
                "doc": {
                    "title": "Senior Software Engineer Backend Mascot Costume Operator",
                    "company": "EventStaff",
                    "location": "On-site",
                    "description": "Wear the company mascot suit during the conference week.",
                    "posted_at": _days_ago_iso(5),
                },
            },
            # OKAY (rating=2)
            {
                "id": "j103",
                "doc": {
                    "title": "Backend Platform Posting (Senior)",
                    "company": "Stripe",
                    "location": "Remote",
                    "description": "Mid-senior backend role on the platform reliability group. Five plus years of experience expected. Polyglot stack with Go and Python.",
                    "posted_at": _days_ago_iso(3),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "j104",
                "doc": {
                    "title": "Senior Software Engineer Backend Office Coffee Runner",
                    "company": "EventStaff",
                    "location": "On-site",
                    "description": "Coffee delivery for the engineering floor on a major release week.",
                    "posted_at": _days_ago_iso(4),
                },
            },
            # === q1 "site reliability engineer" ===
            # BEST ANSWER (rating=3)
            {
                "id": "j201",
                "doc": {
                    "title": "Datadog Observability Posting (Staff)",
                    "company": "Datadog",
                    "location": "New York, NY",
                    "description": "Datadog is hiring a staff-level site reliability engineer to lead reliability and observability initiatives across the product. The candidate will own incident-response standards, drive Kubernetes platform reliability work, and partner with product engineering on SLOs. Five-plus years operating distributed systems at scale expected. Prior reliability engineer leadership a strong plus. The reliability site team partners with the platform engineer pods on every major launch.",
                    "posted_at": _days_ago_iso(2),
                },
            },
            # DECOY (rating=1)
            {
                "id": "j202",
                "doc": {
                    "title": "Site Reliability Engineer T-Shirt Designer",
                    "company": "MerchCo",
                    "location": "Remote",
                    "description": "Design merch graphics for engineering conferences.",
                    "posted_at": _days_ago_iso(3),
                },
            },
            # OKAY (rating=2)
            {
                "id": "j203",
                "doc": {
                    "title": "Platform Reliability Posting (Staff)",
                    "company": "Datadog",
                    "location": "Remote",
                    "description": "Cross-team reliability posting on the platform engineer ladder. Strong Kubernetes and incident-response experience required.",
                    "posted_at": _days_ago_iso(3),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "j204",
                "doc": {
                    "title": "Site Reliability Engineer Lounge Furniture Buyer",
                    "company": "FacilitiesCo",
                    "location": "On-site",
                    "description": "Procurement role for the engineering floor lounge buildout.",
                    "posted_at": _days_ago_iso(5),
                },
            },
            # === q2 "product manager search" ===
            # BEST ANSWER (rating=3)
            {
                "id": "j301",
                "doc": {
                    "title": "Algolia Relevance Posting (Senior PM)",
                    "company": "Algolia",
                    "location": "Remote",
                    "description": "Algolia is hiring a senior product manager to own the relevance and ranking-quality roadmap for our search-as-a-service platform. The product manager will partner with the ML and engineering pods on driving measurable search quality wins, and will own the quarterly relevance OKRs. Prior product manager experience in search infrastructure strongly preferred. The search manager pod runs an agile cadence.",
                    "posted_at": _days_ago_iso(2),
                },
            },
            # DECOY (rating=1)
            {
                "id": "j302",
                "doc": {
                    "title": "Product Manager Search Internship Mentor",
                    "company": "InternHub",
                    "location": "Remote",
                    "description": "Mentor early-career interns on a quarterly basis.",
                    "posted_at": _days_ago_iso(3),
                },
            },
            # OKAY (rating=2)
            {
                "id": "j303",
                "doc": {
                    "title": "Discovery Surface Posting (Lead PM)",
                    "company": "Algolia",
                    "location": "Remote",
                    "description": "Lead the product roadmap for the discovery surfaces. Partner with the search engineering pod.",
                    "posted_at": _days_ago_iso(4),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "j304",
                "doc": {
                    "title": "Product Manager Search Office Plant Curator",
                    "company": "FacilitiesCo",
                    "location": "On-site",
                    "description": "Curate the office plant rotation.",
                    "posted_at": _days_ago_iso(5),
                },
            },
            # === q3 "product designer remote" ===
            # BEST ANSWER (rating=3)
            {
                "id": "j401",
                "doc": {
                    "title": "Linear Onboarding Posting (Senior Designer)",
                    "company": "Linear",
                    "location": "Remote",
                    "description": "Linear is hiring a senior product designer to shape the first-five-minutes experience for new teams. The designer will partner with engineering on the remote onboarding flow and design-systems fluency is expected. Strong remote-first collaboration habits a plus. The product designer reports to the head of design and works in a remote pod.",
                    "posted_at": _days_ago_iso(2),
                },
            },
            # DECOY (rating=1)
            {
                "id": "j402",
                "doc": {
                    "title": "Product Designer Remote Conference Greeter",
                    "company": "ConferenceCo",
                    "location": "On-site",
                    "description": "Greet attendees at our annual design summit.",
                    "posted_at": _days_ago_iso(3),
                },
            },
            # OKAY (rating=2)
            {
                "id": "j403",
                "doc": {
                    "title": "Activation Surface Posting (Senior Designer)",
                    "company": "Linear",
                    "location": "Remote",
                    "description": "Senior designer role on the activation surfaces. Remote-first team and tooling. Design systems experience expected.",
                    "posted_at": _days_ago_iso(4),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "j404",
                "doc": {
                    "title": "Product Designer Remote Office Snack Buyer",
                    "company": "FacilitiesCo",
                    "location": "Remote",
                    "description": "Snack procurement for the engineering floor.",
                    "posted_at": _days_ago_iso(5),
                },
            },
            # === q4 "machine learning engineer" ===
            # BEST ANSWER (rating=3)
            {
                "id": "j501",
                "doc": {
                    "title": "Pinterest Ranking Posting (Senior MLE)",
                    "company": "Pinterest",
                    "location": "Seattle, WA",
                    "description": "Pinterest is hiring a senior machine learning engineer to improve ranking models that power the discovery feeds. The successful candidate will work in PyTorch with large-scale training infrastructure and own a portion of the production ranking stack. Five-plus years of machine learning engineering experience required. Prior recommendations or learning-to-rank background strongly preferred. The learning team works closely with the engineer pods on the feed surface.",
                    "posted_at": _days_ago_iso(2),
                },
            },
            # DECOY (rating=1)
            {
                "id": "j502",
                "doc": {
                    "title": "Machine Learning Engineer Conference Photographer",
                    "company": "ConferenceCo",
                    "location": "On-site",
                    "description": "Event photography role at an industry conference.",
                    "posted_at": _days_ago_iso(3),
                },
            },
            # OKAY (rating=2)
            {
                "id": "j503",
                "doc": {
                    "title": "Recommendations Modeling Posting (Staff Engineer)",
                    "company": "Pinterest",
                    "location": "Remote",
                    "description": "Staff-level ranking and recommendations engineer role. PyTorch and large-scale training infrastructure background expected.",
                    "posted_at": _days_ago_iso(3),
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "j504",
                "doc": {
                    "title": "Machine Learning Engineer Office Bike Mechanic",
                    "company": "FacilitiesCo",
                    "location": "On-site",
                    "description": "Bicycle maintenance for the office commuter program.",
                    "posted_at": _days_ago_iso(5),
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
            # q0 "senior software engineer backend"
            (0, "j101", 3),  # best — description has full role spec
            (0, "j102", 1),  # decoy — title-match (greeter role)
            (0, "j103", 2),  # okay — adjacent backend posting
            (0, "j104", 0),  # distractor — title-match (coffee runner)
            (0, "j105", 0),  # extra distractor — title-match (mascot operator)
            # q1 "site reliability engineer"
            (1, "j201", 3),
            (1, "j202", 1),
            (1, "j203", 2),
            (1, "j204", 0),
            # q2 "product manager search"
            (2, "j301", 3),
            (2, "j302", 1),
            (2, "j303", 2),
            (2, "j304", 0),
            # q3 "product designer remote"
            (3, "j401", 3),
            (3, "j402", 1),
            (3, "j403", 2),
            (3, "j404", 0),
            # q4 "machine learning engineer"
            (4, "j501", 3),
            (4, "j502", 1),
            (4, "j503", 2),
            (4, "j504", 0),
        ],
        "study_name": "tune-jobtitle-vs-company-boost",
        # UBI demo config (FR-8 / D-2). jobs targets rung_2 + hybrid converter
        # so the demo exercises the middle rung of the on-ramp ladder.
        "ubi_target_rung": "rung_2",
        "ubi_converter": "hybrid_ubi_llm",
    },
    # infra_adapter_solr Story A13 / spec §19 decision log: the 5th demo
    # scenario showcases the MVP2 Apache Solr adapter. KB-search use case
    # fits Solr's traditional enterprise-search positioning and
    # differentiates from the ES product-search scenarios. UBI on rung_2
    # + hybrid converter demonstrates the UBI judgment path on Solr (events
    # are synthesized directly into the ubi_queries/ubi_events collections —
    # the stock solr image ships no live solr.UBIComponent; the spec
    # recommends rung_2 + hybrid_ubi_llm — see spec §19).
    {
        "slug": "acme-kb-docs-solr",
        "engine_type": "solr",
        "base_url": "http://solr:8983",
        "auth_kind": "solr_basic",
        "credentials_ref": "local-solr",
        "environment": "prod",
        "target_filter": "acme-kb-*",
        "host_base_url": SOLR,
        "host_auth": SOLR_AUTH,
        "target": "acme-kb-docs",
        # Solr collections are created from configsets, not from a JSON
        # mapping. The reseed dispatcher uses this hint to call the
        # /admin/collections?action=CREATE endpoint instead of the ES
        # PUT /<index> path. The configset name lives in the Solr Compose
        # service's /etc/solr-bootstrap mount.
        "solr_configset": "relyloop_products",
        # Data-design recipe (same as acme-products-prod above). Solr edismax
        # exposes title_boost + bullet_points_boost; description weight is
        # fixed at 1.0. Decoys put the operator-question phrasing in the
        # title; best answers carry the query terms in the BULLET POINTS
        # (the bullet_points field is what bullet_points_boost tunes) and a
        # generic topical title. With baseline equal-midpoint weights, the
        # short decoy title outscores the longer best-answer bullets; at the
        # better-params setting (low title + high bullets), the bullet match
        # wins.
        "docs": [
            # === q0 "okta sso setup" ===
            # BEST ANSWER (rating=3): topical title, each query term appears
            # ONCE in bullets buried inside a long bullet sentence.
            {
                "id": "kb101",
                "doc": {
                    "title": "Identity Provider Wiring Reference Document",
                    "description": "Step-by-step guide for connecting an external identity provider to ACME using SAML 2.0 with example configuration walkthroughs and screenshots.",
                    "bullet_points": [
                        "Create the okta application in the upstream identity provider admin console using the bundled certificate signing request and the audience URL printed at the bottom of the workspace settings page",
                        "Run the federation wizard located in the ACME workspace identity area to retrieve the assertion consumer URL and the entity ID required for federated trust between the two systems and then save the connection record before moving on",
                        "Upload the provider metadata XML to complete the sso configuration via the upload dialog at the workspace identity settings area and confirm the green health badge appears next to the connection entry within thirty seconds",
                        "Test the federated redirect URL once the configuration is saved by opening a private browser session and triggering a fresh authentication setup request against the just-configured provider",
                    ],
                    "category": "Authentication",
                    "in_stock": True,
                },
            },
            # DECOY (rating=1): title is the query.
            {
                "id": "kb102",
                "doc": {
                    "title": "Okta SSO Setup Reference Card",
                    "description": "Printed pocket card.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # OKAY (rating=2)
            {
                "id": "kb103",
                "doc": {
                    "title": "Workforce Identity Federation Overview",
                    "description": "Conceptual overview of federation models supported by ACME.",
                    "bullet_points": [
                        "SAML and OIDC are both supported as identity provider protocols on the workspace federation surface",
                        "okta workspaces are the common deployment case for the federation overview reference flows that ACME ships",
                        "Configure either protocol at the workspace level via the settings panel after registering the upstream provider",
                    ],
                    "category": "Authentication",
                    "in_stock": True,
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "kb104",
                "doc": {
                    "title": "Okta SSO Setup Conference Sticker",
                    "description": "Vinyl sticker.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # EXTRA DISTRACTOR (rated 0)
            {
                "id": "kb105",
                "doc": {
                    "title": "Okta SSO Setup Branded Notebook",
                    "description": "Spiral-bound notebook.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # === q1 "forgot admin password" ===
            # BEST ANSWER (rating=3)
            {
                "id": "kb201",
                "doc": {
                    "title": "Account Recovery Workflow Reference",
                    "description": "Recovery flow for the primary owner of an ACME workspace.",
                    "bullet_points": [
                        "Click the forgot credentials link on the sign-in surface when the recovery flow is needed and then proceed to the next confirmation step on the recovery wizard surface",
                        "Receive the recovery email at the registered admin address within thirty seconds and locate the message in the inbox folder rather than the spam folder",
                        "Reset the credential password using the single-use link printed in the email and confirm the change by entering the new value twice on the reset surface",
                        "Re-authenticate the admin session on every device that was previously signed in and verify the change took effect on each",
                    ],
                    "category": "Authentication",
                    "in_stock": True,
                },
            },
            # DECOY (rating=1)
            {
                "id": "kb202",
                "doc": {
                    "title": "Forgot Admin Password Sticky Note Pack",
                    "description": "Sticky notes.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # OKAY (rating=2)
            {
                "id": "kb203",
                "doc": {
                    "title": "Changing The Primary Owner Of A Workspace",
                    "description": "Procedure when the primary admin leaves the company.",
                    "bullet_points": [
                        "Use the password recovery flow if the admin is unreachable for an extended period during a leadership transition or vacation",
                        "Contact ACME support if the recovery email has lapsed and the registered address is no longer monitored by the new owner",
                    ],
                    "category": "Authentication",
                    "in_stock": True,
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "kb204",
                "doc": {
                    "title": "Forgot Admin Password Stress Ball",
                    "description": "Foam stress ball.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # EXTRA DISTRACTOR (rated 0)
            {
                "id": "kb205",
                "doc": {
                    "title": "Forgot Admin Password Hat Embroidered",
                    "description": "Baseball cap.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # === q2 "api rate limits" ===
            # BEST ANSWER (rating=3)
            {
                "id": "kb301",
                "doc": {
                    "title": "Throughput Policy Reference Document",
                    "description": "Throughput governance for the public-facing surface.",
                    "bullet_points": [
                        "Default api quota is sixty requests per minute on the standard public-facing surface for new workspaces and applies to all unauthenticated public traffic",
                        "Burst window allows short five-second spikes above the published rate ceiling without immediately triggering a throttle response on the gateway tier",
                        "Higher-tier limits available via the operator request form for workspaces with documented traffic peaks above the standard ceiling at sustained load",
                        "Per-tenant ceilings override the workspace-wide configuration when an enterprise contract specifies dedicated capacity for the tenant in question",
                    ],
                    "category": "API",
                    "in_stock": True,
                },
            },
            # DECOY (rating=1)
            {
                "id": "kb302",
                "doc": {
                    "title": "API Rate Limits Reference Poster",
                    "description": "Wall poster.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # OKAY (rating=2)
            {
                "id": "kb303",
                "doc": {
                    "title": "Burst-Window Behavior Under Spike Load",
                    "description": "Explainer for burst-window mechanics.",
                    "bullet_points": [
                        "Burst window is rolling not fixed-window so the ceiling moves continuously with the trailing five-second window of observed traffic",
                        "Throttled requests return HTTP 429 with a Retry-After header that the client library should respect when scheduling the next attempt",
                        "Apply exponential backoff on receiving the throttle signal to avoid synchronized re-spike from many clients at once",
                    ],
                    "category": "API",
                    "in_stock": True,
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "kb304",
                "doc": {
                    "title": "API Rate Limits Hoodie Black Embroidered",
                    "description": "Cotton blend hoodie.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # EXTRA DISTRACTOR (rated 0)
            {
                "id": "kb305",
                "doc": {
                    "title": "API Rate Limits Coffee Tumbler Stainless",
                    "description": "Stainless tumbler.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # === q3 "rest api authentication" ===
            # BEST ANSWER (rating=3)
            {
                "id": "kb401",
                "doc": {
                    "title": "Programmatic Access Identity Reference",
                    "description": "Identity model for programmatic clients.",
                    "bullet_points": [
                        "Generate an api key from the operator surface to enable programmatic rest access against the public endpoint with stable long-lived credentials",
                        "Scope the issued key to a single project for least-privilege programmatic access and minimize the blast radius of any single credential leak event",
                        "Use Bearer token authentication on every outbound rest call with the issued key passed in the standard Authorization header value",
                        "Rotate the issued key quarterly and revoke immediately on suspected compromise via the operator surface revocation panel",
                    ],
                    "category": "API",
                    "in_stock": True,
                },
            },
            # DECOY (rating=1)
            {
                "id": "kb402",
                "doc": {
                    "title": "Rest API Authentication Conference Tote",
                    "description": "Tote bag.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # OKAY (rating=2)
            {
                "id": "kb403",
                "doc": {
                    "title": "Token Rotation Cadence Recommendations",
                    "description": "Recommended rotation cadence per token kind.",
                    "bullet_points": [
                        "Rotate the issued credential key quarterly for routine programmatic clients as a defense-in-depth practice on top of scoping",
                        "Rotate immediately on suspected compromise rather than waiting for the next scheduled cadence window to complete",
                        "Use short-lived tokens for CI pipelines and dynamic agents rather than long-lived credentials that may persist in build logs",
                    ],
                    "category": "API",
                    "in_stock": True,
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "kb404",
                "doc": {
                    "title": "Rest API Authentication Trivia Card Set",
                    "description": "Trivia cards.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # EXTRA DISTRACTOR (rated 0)
            {
                "id": "kb405",
                "doc": {
                    "title": "Rest API Authentication Lanyard Embroidered",
                    "description": "Polyester lanyard.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # === q4 "billing refund policy" ===
            # BEST ANSWER (rating=3)
            {
                "id": "kb501",
                "doc": {
                    "title": "Account Settlement FAQ Document",
                    "description": "Common operator questions about invoices and credits.",
                    "bullet_points": [
                        "Refund eligibility under the standard billing terms is documented in the master service agreement that all workspaces accept on signup",
                        "Window is fourteen days after the invoice posts and applies to both monthly subscription invoices and per-seat additions made during the cycle",
                        "Submit a request from the admin surface via the support ticket flow under the account settlement category for the fastest turnaround",
                        "Proration math and credit-note timing under the refund policy and the broader settlement policy framework that the agreement codifies",
                    ],
                    "category": "Billing",
                    "in_stock": True,
                },
            },
            # DECOY (rating=1)
            {
                "id": "kb502",
                "doc": {
                    "title": "Billing Refund Policy Coffee Mug",
                    "description": "Ceramic mug.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # OKAY (rating=2)
            {
                "id": "kb503",
                "doc": {
                    "title": "Invoice Cadence And Proration Math",
                    "description": "Detailed worked examples of mid-cycle adjustments.",
                    "bullet_points": [
                        "Invoices post on the first of each month and a notification email goes to the registered billing contact at the same time",
                        "Mid-cycle plan changes prorate to the day and the new line items appear on the next monthly invoice cycle",
                        "Credit notes attach to the next billing invoice automatically and offset the new charges before any payment is captured",
                    ],
                    "category": "Billing",
                    "in_stock": True,
                },
            },
            # DISTRACTOR (rated 0)
            {
                "id": "kb504",
                "doc": {
                    "title": "Billing Refund Policy T-Shirt Black",
                    "description": "Cotton tee.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
            # EXTRA DISTRACTOR (rated 0)
            {
                "id": "kb505",
                "doc": {
                    "title": "Billing Refund Policy Notebook Spiral-Bound",
                    "description": "Lined notebook.",
                    "bullet_points": [],
                    "category": "Swag",
                    "in_stock": True,
                },
            },
        ],
        "template_name": "products_edismax",
        # Reuse the same edismax template the tutorial uses — declared
        # params map to title / description / bullet_points boosts +
        # tie + mm. Templates are loaded by name from
        # samples/templates/solr/.
        "template_body": (
            "{\n"
            '  "defType": "edismax",\n'
            '  "q": "{{ query_text }}",\n'
            '  "field_boosts": {\n'
            '    "title": {{ title_boost }},\n'
            '    "description": 1.0,\n'
            '    "bullet_points": {{ bullet_points_boost }}\n'
            "  },\n"
            '  "tie_breaker": 0.3,\n'
            '  "min_should_match": "50%",\n'
            '  "fl": "*,score"\n'
            "}\n"
        ),
        # The reseed builds a study search-space from these declared params,
        # and ``estimate_cardinality`` counts every float as 100 → the demo's
        # ``> 10^6`` guard allows at most 3 floats. The Solr scenario tunes the
        # two boosts named in ``study_name`` (title vs bullet); description /
        # tie / min_should_match are fixed in the template above so the study
        # stays at 100^2 = 10^4 (comfortably under the cap). See the demo-seed
        # cardinality note in feat_demo_reseed_solr_and_steplog.
        "template_declared_params": {
            "title_boost": "float",
            "bullet_points_boost": "float",
        },
        "query_set_name": "acme-kb-top-queries-q4-2025",
        "queries": [
            {"query_text": "okta sso setup"},
            {"query_text": "forgot admin password"},
            {"query_text": "api rate limits"},
            {"query_text": "rest api authentication"},
            {"query_text": "billing refund policy"},
        ],
        "judgment_list_name": "acme-kb-relevance-2025-12",
        "rubric": "Rate articles by how directly they answer the operator question. 0=off-topic, 1=tangential, 2=on-topic, 3=lead answer.",
        "judgments_map": [
            # q0 "okta sso setup"
            (0, "kb101", 3),  # best — query terms in bullets
            (0, "kb102", 1),  # decoy — title-match swag
            (0, "kb103", 2),  # okay — adjacent federation article
            (0, "kb104", 0),  # distractor — title-match swag
            (0, "kb105", 0),  # distractor — title-match swag
            # q1 "forgot admin password"
            (1, "kb201", 3),
            (1, "kb202", 1),
            (1, "kb203", 2),
            (1, "kb204", 0),
            (1, "kb205", 0),
            # q2 "api rate limits"
            (2, "kb301", 3),
            (2, "kb302", 1),
            (2, "kb303", 2),
            (2, "kb304", 0),
            (2, "kb305", 0),
            # q3 "rest api authentication"
            (3, "kb401", 3),
            (3, "kb402", 1),
            (3, "kb403", 2),
            (3, "kb404", 0),
            (3, "kb405", 0),
            # q4 "billing refund policy"
            (4, "kb501", 3),
            (4, "kb502", 1),
            (4, "kb503", 2),
            (4, "kb504", 0),
            (4, "kb505", 0),
        ],
        "study_name": "tune-kb-title-vs-bullet-boosts-solr",
        # FR-8 / spec §19 recommendation: Solr scenario gets rung_2 +
        # hybrid_ubi_llm so the demo exercises the UBI judgment read-path on
        # Solr (synthesized events in ubi_queries/ubi_events — no live
        # solr.UBIComponent in the stock image) AND demonstrates the hybrid
        # UBI+LLM converter on the new engine.
        "ubi_target_rung": "rung_2",
        "ubi_converter": "hybrid_ubi_llm",
    },
]

# FR-8 invariant: ubi_converter is None iff ubi_target_rung is None. A single
# scenario that drifts (e.g., target_rung set without a converter) would
# silently produce a broken demo — assert at import time so any future
# editor of SCENARIOS gets a hard stop. The unit test at
# backend/tests/unit/scripts/test_scenarios_ubi_config.py pins the
# (slug, target) parity against DEMO_UBI_SCENARIO_ALLOWLIST.
for _scenario in SCENARIOS:
    assert (_scenario.get("ubi_converter") is None) == (_scenario.get("ubi_target_rung") is None), (
        f"SCENARIOS[{_scenario['slug']}]: ubi_converter and ubi_target_rung "
        f"must be both None or both non-None "
        f"(got ubi_target_rung={_scenario.get('ubi_target_rung')!r}, "
        f"ubi_converter={_scenario.get('ubi_converter')!r})"
    )
del _scenario


# ---------------------------------------------------------------------------
# Seed flow per scenario
# ---------------------------------------------------------------------------


async def _async_seed_synthetic_ubi(
    *,
    scenario_slug: str,
    target_application: str,
    target_rung: str,
    scenario_judgments_map: list[tuple[int, str, int]],
    query_id_by_index: dict[int, str],
    query_text_by_index: dict[int, str],
    seed_anchor_iso: str,
    engine_base_url: str,
    host_auth: tuple[str, str],
    engine_type: str,
) -> int:
    """Sync-callable wrapper around the async UBI helpers (Story 2.5 / FR-5).

    The CLI is sync (urllib); the canonical UBI helpers in
    ``backend.app.services.demo_ubi_seed`` are async (``httpx.AsyncClient``)
    so the home-button reseed and the CLI share a single source of truth
    for the index mappings + bulk-write posture. Wrapping a short-lived
    httpx client here in ``asyncio.run`` keeps the CLI's sync control
    flow intact without duplicating the generator + writer.
    """
    # Imports deferred to inside the async wrapper — the CLI runs
    # outside the api-container and `make seed-demo` shouldn't pay the
    # cost of importing backend.app.* unless a UBI-enabled scenario
    # actually fires.
    import httpx

    from backend.app.domain.demo.synthetic_ubi import (
        UbiRung,
        fabricate_ubi_for_scenario,
    )
    from backend.app.services.demo_ubi_seed import (
        ensure_ubi_indices,
        seed_synthetic_ubi,
    )

    queries, events = fabricate_ubi_for_scenario(
        scenario_judgments_map=scenario_judgments_map,
        query_id_by_index=query_id_by_index,
        query_text_by_index=query_text_by_index,
        target_application=target_application,
        target_rung=cast(UbiRung, target_rung),
        seed_anchor_iso=seed_anchor_iso,
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        await ensure_ubi_indices(
            engine_client=client,
            engine_base_url=engine_base_url,
            host_auth=host_auth,
            engine_type=engine_type,
            # CLI runs on the HOST — the in-container default
            # /app/samples/ubi_index_mappings.json does not exist here.
            # Resolve the repo-root samples/ path instead (GPT-5.5 final
            # review on PR #320). The home-button reseed runs inside the
            # api container where the in-container default is correct.
            mapping_path=SAMPLES_DIR / "ubi_index_mappings.json",
        )
        return await seed_synthetic_ubi(
            engine_client=client,
            engine_base_url=engine_base_url,
            host_auth=host_auth,
            engine_type=engine_type,
            scenario_slug=scenario_slug,
            target_application=target_application,
            queries=queries,
            events=events,
        )


def _poll_judgment_list_until_terminal(judgment_list_id: str, *, slug: str) -> dict:
    """Sync CLI mirror of demo_seeding._poll_judgment_list_until_terminal."""
    deadline = time.time() + 180
    detail: dict = {}
    while time.time() < deadline:
        detail = http("GET", f"{API}/judgment-lists/{judgment_list_id}")
        status = detail.get("status")
        if status == "complete":
            return detail
        if status == "failed":
            raise RuntimeError(
                f"ubi_judgments/{slug}: failed "
                f"({detail.get('failed_reason') or 'no failed_reason set'})"
            )
        time.sleep(3)
    raise RuntimeError(
        f"ubi_judgments/{slug}: poll ceiling 180s exceeded (last status={detail.get('status')!r})"
    )


def _create_one_study(
    s: dict,
    *,
    study_name: str,
    judgment_list_id: str,
    cluster_id: str,
    template_id: str,
    qset_id: str,
) -> str:
    """Inline study create + poll + digest wait. Returns study_id.

    Extracted from the original seed_scenario step 8 so the dual-study
    path can call it twice (LLM list + UBI list) per Story 2.5 / FR-9.
    """
    search_space = {
        "params": {
            name: {"type": "float", "low": 0.5, "high": 5.0, "log": True}
            for name in s["template_declared_params"]
        }
    }
    study_create = post(
        "/studies",
        {
            "name": study_name,
            "cluster_id": cluster_id,
            "target": s["target"],
            "template_id": template_id,
            "query_set_id": qset_id,
            "judgment_list_id": judgment_list_id,
            "search_space": search_space,
            "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
            "config": {
                "max_trials": DEMO_SMALL_STUDY_MAX_TRIALS,
                "parallelism": 2,
                "sampler": "tpe",
                "seed": 42,
            },
        },
    )
    study_id = study_create["id"]
    print(f"  study created: {study_id} ({study_name}), polling for completion...")
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
        return study_id
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
    return study_id


def _seed_solr_scenario_minimum(s: dict) -> list[dict]:
    """Minimum-viable Solr scenario: register the cluster + DB rows; assume
    `make seed-solr` already created the Solr collection out-of-band.

    infra_adapter_solr Story A13. Returns the same `list[dict]` shape as the
    main `seed_scenario` so the caller's accumulation logic is unchanged;
    items without a corresponding UBI study return a single-element list.

    Operators who haven't run `make seed-solr` yet see the registration
    fail with `CLUSTER_UNREACHABLE` (probe couldn't reach the collection) —
    the error message points at the `make seed-solr` command.
    """
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
    # Create the query template + query set + judgment list rows. The study
    # itself isn't created here — operators kick that off via the UI once
    # they've verified the collection contents in /clusters/<id>.
    template = post(
        "/query-templates",
        {
            "name": s["template_name"],
            "engine_type": s["engine_type"],
            "body": s["template_body"],
            "declared_params": s["template_declared_params"],
        },
    )
    print(f"  template: {template['id']}")
    return [
        {
            "scenario": s["slug"],
            "cluster_id": cluster_id,
            "template_id": template["id"],
            "skipped_index_path": True,
            "next_step": "Run `make seed-solr`, then create the demo study via the UI.",
        }
    ]


def seed_scenario(s: dict) -> list[dict]:
    """Seed one scenario. Returns 1 result for non-UBI, 2 for UBI-enabled.

    Story 2.5 / FR-5 / FR-9: for scenarios with `ubi_target_rung` non-None,
    after the LLM judgment list imports we dispatch a UBI judgment
    generation against the synthetic UBI rows the orchestrator wrote
    earlier, poll until terminal, then seed a second study (UBI-graded)
    on the same query set. Both studies are named with " (LLM)" / " (UBI)"
    suffixes so the rename step disambiguates them in the tutorial.
    """
    print(f"\n=== {s['slug']} ({s['engine_type']}) ===")

    # infra_adapter_solr Story A13: Solr's per-engine seeding path
    # (configset CREATE + bulk update) lives in
    # backend/app/scripts/seed_solr_products.py + `make seed-solr`. The
    # home-button reseed orchestrator doesn't drive that path yet —
    # operators run `make seed-solr` separately, then this orchestrator
    # registers the local-solr cluster + study/judgments rows. Skip the
    # ES-style index creation for Solr scenarios with a clear message;
    # the cluster row + DB rows still get created below.
    if s["engine_type"] == "solr":
        print(
            "  Solr scenario — collection creation handled by `make seed-solr`. "
            "Skipping index PUT + doc upserts."
        )
        return _seed_solr_scenario_minimum(s)

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

    # 6.5. Synthetic UBI seeding (Story 2.5 / FR-3, FR-5) — runs BEFORE
    # the LLM judgment import so a UBI-seeding failure surfaces early.
    # Mirrors the home-button reseed orchestrator's insertion order
    # (between qrows-fetched and judgments-imported).
    ubi_target_rung = s.get("ubi_target_rung")
    seed_anchor_iso = datetime.now(UTC).isoformat()
    if ubi_target_rung is not None:
        query_id_by_index = dict(enumerate(qid_by_idx))
        query_text_by_index = {i: q["query_text"] for i, q in enumerate(s["queries"])}
        event_count = asyncio.run(
            _async_seed_synthetic_ubi(
                scenario_slug=s["slug"],
                target_application=s["target"],
                target_rung=ubi_target_rung,
                scenario_judgments_map=s["judgments_map"],
                query_id_by_index=query_id_by_index,
                query_text_by_index=query_text_by_index,
                seed_anchor_iso=seed_anchor_iso,
                engine_base_url=s["host_base_url"],
                host_auth=s["host_auth"],
                engine_type=s["engine_type"],
            )
        )
        print(f"  synthetic UBI: {event_count} events ({ubi_target_rung})")

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
    # That broke demo credibility (a relevance engineer immediately notices when
    # four "different" scenarios produce the exact same metric to 3 decimals).
    #
    # Real-study path: POST /api/v1/studies with a fixed Optuna seed
    # (config.seed=42) → Arq worker runs trials against the real ES backing
    # store → real metric_delta + LLM-generated digest emerge from the data.
    # Repeatable: same seed + same judgments + same docs + pinned ES version
    # = same numbers run after run.
    #
    # For acme specifically, ALSO create a second template (function_score
    # price-decay shape) so the digest worker has a candidate it CAN suggest
    # as a swap_template followup. Whether the LLM actually picks it is up to
    # the digest prompt + the study's data — we don't fake it.
    if s["slug"] == "acme-products-prod":
        # Per Gemini Code Assist review on PR #281: this template originally
        # claimed to do "recency decay" but its body was just a bare
        # function_score wrapper around multi_match — no actual scoring
        # function, and the products index has no date field to decay on
        # anyway. Renamed to "price-decay" + added a real gauss function
        # over the existing `price` field so the swap_template followup
        # would actually produce different ranking on a Run-followup click.
        swap_template = post(
            "/query-templates",
            {
                "name": "function-score-price-decay-v1",
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
                                },
                                "functions": [
                                    {
                                        "gauss": {
                                            "price": {
                                                "origin": 0,
                                                "scale": 100,
                                                "decay": 0.5,
                                            }
                                        }
                                    }
                                ],
                                "score_mode": "multiply",
                            }
                        }
                    }
                ),
                "declared_params": s["template_declared_params"],
            },
        )
        print(f"  swap template: {swap_template['id']} (function-score-price-decay-v1)")

    # 8. REAL study create + poll + digest wait (LLM-grade study). For
    # UBI-enabled scenarios (Story 2.5 / FR-9) the LLM study gets a
    # " (LLM)" suffix up front so the rename step doesn't have to
    # special-case it; non-UBI scenarios keep the bare study_name.
    base_study_name = s["study_name"]
    llm_study_name = f"{base_study_name} (LLM)" if ubi_target_rung is not None else base_study_name
    llm_study_id = _create_one_study(
        s,
        study_name=llm_study_name,
        judgment_list_id=jlist_id,
        cluster_id=cluster_id,
        template_id=template_id,
        qset_id=qset_id,
    )

    results: list[dict] = [
        {
            "slug": s["slug"],
            "cluster_id": cluster_id,
            "query_set_id": qset_id,
            "template_id": template_id,
            "judgment_list_id": jlist_id,
            "study_id": llm_study_id,
            "study_name": llm_study_name,
        }
    ]

    # 9. UBI dispatch + dual study (Story 2.5 / FR-4, FR-9).
    if ubi_target_rung is not None:
        ubi_converter = s["ubi_converter"]
        ubi_jlist_name = f"{s['judgment_list_name']} (UBI)"
        ubi_dispatch_body: dict[str, Any] = {
            "name": ubi_jlist_name,
            "query_set_id": qset_id,
            "cluster_id": cluster_id,
            "target": s["target"],
            "since": (datetime.fromisoformat(seed_anchor_iso) - timedelta(seconds=60)).isoformat(),
            "until": seed_anchor_iso,
            "converter": ubi_converter,
            "mapping_strategy": "reject",
            # The sync count gate defaults to 100 events; the sparse rung_1
            # scenario (corp-docs) only seeds ~50 by design — it exists to
            # demo hybrid LLM-fill on thin UBI. Derive the floor from the
            # actually-seeded count so the demo's own data always clears the
            # gate, while dense rungs (240/640 events) keep the 100 default.
            "min_impressions_threshold": min(100, event_count),
        }
        if ubi_converter == "hybrid_ubi_llm":
            ubi_dispatch_body["current_template_id"] = template_id
            ubi_dispatch_body["rubric"] = s["rubric"]
        print(f"  dispatching UBI judgment generation ({ubi_converter})...")
        dispatch_resp = post("/judgments/generate-from-ubi", ubi_dispatch_body)
        ubi_jlist_id = dispatch_resp["judgment_list_id"]
        print(f"  polling UBI judgment-list {ubi_jlist_id[:8]} for completion...")
        _poll_judgment_list_until_terminal(ubi_jlist_id, slug=s["slug"])
        print(f"  UBI judgment-list: {ubi_jlist_id}")
        ubi_study_name = f"{base_study_name} (UBI)"
        ubi_study_id = _create_one_study(
            s,
            study_name=ubi_study_name,
            judgment_list_id=ubi_jlist_id,
            cluster_id=cluster_id,
            template_id=template_id,
            qset_id=qset_id,
        )
        results.append(
            {
                "slug": s["slug"],
                "cluster_id": cluster_id,
                "query_set_id": qset_id,
                "template_id": template_id,
                "judgment_list_id": ubi_jlist_id,
                "study_id": ubi_study_id,
                "study_name": ubi_study_name,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Rich-data scenario — 1000 ESCI products + LLM-generated judgments
# ---------------------------------------------------------------------------


def seed_rich_scenario() -> dict:
    """Fifth scenario using the full 1000-product ESCI sample dataset.

    The four small SCENARIOS above are deliberately tiny (5 docs each) so they
    seed in seconds and demonstrate the system's mechanics, but they hit a
    metric ceiling — the optimizer correctly reports "no headroom" because
    the sparse judgments fix the ranking regardless of boost values. That's
    honest, but it's not a headline-lift demo story.

    This rich scenario uses:

    - 1000 Amazon ESCI products bulk-indexed into a dedicated
      `acme-products-rich` index (separate from `make seed-es`'s `products`
      index so they coexist cleanly).
    - 5 real product-search queries from `samples/queries.csv`.
    - LLM-generated judgments via `POST /judgments/generate` (real OpenAI
      call against the real cluster, ~30-60s, ~$0.05 with gpt-4o-mini).
    - A 3-param multi_match template (`title_boost`,
      `description_boost`, `bullet_points_boost`) from
      `samples/templates/product_search.j2`.
    - A real 15-trial Optuna study with `config.seed=42` for repeatability.

    Total runtime: ~3-5 min added to `make seed-demo`. Cost: ~$0.05 in LLM
    tokens. With this much data the optimizer has real headroom — the
    digest will show real `metric_delta` (baseline → best, non-zero lift)
    and populated `parameter_importance` across all three boosts.

    Failures here are tolerated: the four small scenarios are still
    valuable on their own, so the caller wraps this in a try/except
    rather than aborting the whole seed.
    """
    slug = "acme-products-rich-prod"
    index_name = "acme-products-rich"
    print(f"\n=== {slug} (elasticsearch, rich ESCI data) ===")

    # 1. Load 1000 ESCI products from samples/.
    products = json.loads((SAMPLES_DIR / "products.json").read_text())
    print(f"  loading {len(products)} products from samples/products.json")

    # 2. DELETE + recreate the index with explicit mapping.
    try:
        http("DELETE", f"{ES}/{index_name}", auth=ES_AUTH)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    http(
        "PUT",
        f"{ES}/{index_name}",
        body={
            "mappings": {
                "properties": {
                    "title": {"type": "text"},
                    "description": {"type": "text"},
                    "brand": {"type": "keyword"},
                    "color": {"type": "keyword"},
                    "bullet_points": {"type": "text"},
                }
            }
        },
        auth=ES_AUTH,
    )
    print(f"  index: {index_name} (mapping created)")

    # 3. Bulk-index in chunks of 500 (NDJSON over /_bulk). We bypass the http()
    #    helper here because /_bulk requires application/x-ndjson, not JSON.
    bulk_chunk = 500
    for i in range(0, len(products), bulk_chunk):
        chunk = products[i : i + bulk_chunk]
        lines = []
        for p in chunk:
            lines.append(json.dumps({"index": {"_index": index_name, "_id": p["id"]}}))
            lines.append(json.dumps({k: v for k, v in p.items() if k != "id"}))
        body = ("\n".join(lines) + "\n").encode()
        req = urllib.request.Request(
            f"{ES}/_bulk",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-ndjson",
                "Authorization": _basic(ES_AUTH),
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
    http("POST", f"{ES}/{index_name}/_refresh", body=None, auth=ES_AUTH)
    print(f"  docs: {len(products)} bulk-indexed")

    # 4. Register cluster with the right target_filter so the UI dropdown
    #    only surfaces the rich index for this cluster.
    cluster = post(
        "/clusters",
        {
            "name": slug,
            "engine_type": "elasticsearch",
            "base_url": "http://elasticsearch:9200",
            "auth_kind": "es_basic",
            "credentials_ref": "local-es",
            "environment": "prod",
            "target_filter": f"{index_name}*",
        },
    )
    cluster_id = cluster["id"]
    print(f"  cluster: {cluster_id}")

    # 5. Template from samples/templates/product_search.j2 — the canonical
    #    3-param multi_match used by the tutorial.
    template_body = (SAMPLES_DIR / "templates" / "product_search.j2").read_text()
    template = post(
        "/query-templates",
        {
            "name": "product-search-multi-match-v1",
            "engine_type": "elasticsearch",
            "body": template_body,
            "declared_params": {
                "title_boost": "float",
                "description_boost": "float",
                "bullet_points_boost": "float",
            },
        },
    )
    template_id = template["id"]
    print(f"  template: {template_id} (product-search-multi-match-v1)")

    # 6. Query set + queries from samples/queries.csv (first N).
    qset = post(
        "/query-sets",
        {"name": "acme-rich-queries-q4-2025", "cluster_id": cluster_id},
    )
    qset_id = qset["id"]
    csv_lines = (SAMPLES_DIR / "queries.csv").read_text().strip().splitlines()
    queries: list[dict] = []
    for line in csv_lines[1 : RICH_SCENARIO_QUERY_COUNT + 1]:  # skip header
        parts = line.split(",", 1)
        if len(parts) == 2:
            queries.append({"query_text": parts[1].strip()})
    bulk_q = post(f"/query-sets/{qset_id}/queries", {"queries": queries})
    print(f"  query-set: {qset_id} (queries added: {bulk_q['added']})")

    # 7. Generate judgments via LLM. Returns 202; worker generates async.
    jl_resp = post(
        "/judgments/generate",
        {
            "name": "acme-rich-judgments-q4-2025",
            "description": "ESCI demo judgments for the rich-data acme scenario",
            "query_set_id": qset_id,
            "cluster_id": cluster_id,
            "target": index_name,
            "current_template_id": template_id,
            "rubric": (
                "Rate 0-3 by relevance to the query: "
                "0=irrelevant, 1=partial, 2=relevant, 3=highly relevant."
            ),
        },
    )
    jlist_id = jl_resp["judgment_list_id"]
    print(f"  judgment-list: {jlist_id} (generating via LLM, ~30-60s)")

    # Poll until judgments complete. 3-min ceiling; gpt-4o-mini against 5
    # queries × top-K is typically 30-60s, the wide margin protects against
    # rate-limit hiccups.
    jl_deadline = time.time() + 180
    jl_detail: dict = jl_resp
    while time.time() < jl_deadline:
        try:
            jl_detail = http("GET", f"{API}/judgment-lists/{jlist_id}", quiet_404=True)
            if jl_detail.get("status") in {"complete", "failed"}:
                break
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        time.sleep(5)
    if jl_detail.get("status") != "complete":
        print(f"  WARNING: judgment generation status={jl_detail.get('status')!r}; skipping study")
        return {"slug": slug, "cluster_id": cluster_id, "judgment_list_id": jlist_id}
    print(
        f"  judgment-list: complete "
        f"(count={jl_detail.get('judgment_count', '?')}, "
        f"cost=${jl_detail.get('cost_usd', '?')})"
    )

    # 8. Real 15-trial study against the rich data. Three boost knobs gives
    #    Optuna a 3-D search space that actually moves the metric.
    search_space = {
        "params": {
            "title_boost": {"type": "float", "low": 0.5, "high": 5.0, "log": True},
            "description_boost": {"type": "float", "low": 0.5, "high": 5.0, "log": True},
            "bullet_points_boost": {"type": "float", "low": 0.5, "high": 5.0, "log": True},
        }
    }
    study_name = "tune-acme-products-rich-boosts"
    study_create = post(
        "/studies",
        {
            "name": study_name,
            "cluster_id": cluster_id,
            "target": index_name,
            "template_id": template_id,
            "query_set_id": qset_id,
            "judgment_list_id": jlist_id,
            "search_space": search_space,
            "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
            "config": {
                "max_trials": 15,
                "parallelism": 3,
                "sampler": "tpe",
                "seed": 42,
            },
        },
    )
    study_id = study_create["id"]
    print(f"  study created: {study_id}, polling for completion (~1-3 min)...")
    study_deadline = time.time() + 300
    detail: dict = study_create
    while time.time() < study_deadline:
        detail = http("GET", f"{API}/studies/{study_id}")
        if detail["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(5)
    print(f"  study: {study_id} ({detail['status']}, best_metric={detail.get('best_metric')})")

    if detail["status"] == "completed":
        digest_deadline = time.time() + 120
        while time.time() < digest_deadline:
            try:
                digest = http("GET", f"{API}/studies/{study_id}/digest", quiet_404=True)
                followups = digest.get("suggested_followups") or []
                kinds = ", ".join(f.get("kind", "?") for f in followups) or "(none)"
                print(f"  digest: {digest['id']} ({len(followups)} followups: {kinds})")
                break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
            time.sleep(3)

    return {
        "slug": slug,
        "cluster_id": cluster_id,
        "query_set_id": qset_id,
        "template_id": template_id,
        "judgment_list_id": jlist_id,
        "study_id": study_id,
        "study_name": study_name,
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
        # Solr-minimum scenarios (infra_adapter_solr Story A13) register a
        # cluster + template but create no study — operators start it from the
        # UI after `make seed-solr`. Those result dicts carry neither
        # `study_id` nor `study_name`, so there's nothing to rename; skip them.
        # Guard on BOTH keys the body dereferences (the summary loop guards on
        # `study_id`) so the two consumers stay consistent and robust to any
        # partial dict. (Mirrors the rich scenario's `if rich_result.get(
        # "study_id")` study-presence guard.)
        if "study_id" not in r or "study_name" not in r:
            continue
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


def _engine_reachable(host_base_url: str, engine_type: str) -> bool:
    """Sync wrapper around the async ``is_engine_reachable`` probe.

    The CLI runs on the HOST and uses each scenario's ``host_base_url`` directly
    (no Compose-DNS resolution — that's the in-container orchestrator's job).

    The import of ``is_engine_reachable`` is LOCAL/late on purpose:
    ``backend.app.services.demo_seeding`` imports ``SCENARIOS`` from THIS module,
    so a top-level import here would create a circular import. Matches the
    existing deferred-import pattern in ``_async_seed_synthetic_ubi``.
    (infra_solr_ci_readiness FR-3.)
    """
    import asyncio

    from backend.app.services.demo_seeding import is_engine_reachable

    return asyncio.run(is_engine_reachable(host_base_url, engine_type))  # type: ignore[arg-type]


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

    results: list[dict] = []
    failures: list[tuple[str, Exception]] = []
    # Slugs skipped because their engine wasn't reachable at probe time (engine
    # container not running). Distinct from `failures` — a skip is not an error.
    # (infra_solr_ci_readiness FR-3.)
    skipped: list[str] = []
    for s in SCENARIOS:
        # Skip-on-unreachable: probe the scenario's engine BEFORE attempting to
        # seed. A down engine (e.g. Solr not started locally) yields a logged
        # skip instead of a ConnectError that aborts the whole reseed.
        if not _engine_reachable(str(s["host_base_url"]), str(s["engine_type"])):
            print(
                f"[skip] {s['slug']} — {s['engine_type']} unreachable at {s['host_base_url']}",
                file=sys.stderr,
            )
            skipped.append(str(s["slug"]))
            continue
        try:
            # seed_scenario returns a list — 1 entry for non-UBI scenarios,
            # 2 entries for UBI-enabled (LLM + UBI studies, Story 2.5 / FR-9).
            results.extend(seed_scenario(s))
        except Exception as exc:  # noqa: BLE001 — see continue-on-failure note
            print(f"\n!! scenario {s['slug']} FAILED: {exc!r}")
            failures.append((s["slug"], exc))
            # GPT-5.5 PR #182 review finding #1 fix — partial-seed self-heal.
            # In --if-empty mode (auto-seed from `make up`), a mid-seed
            # failure would leave the `clusters` table non-empty, which
            # would make every subsequent `make up` skip the seed and
            # leave the operator on a broken half-seeded stack. Roll back
            # any rows we inserted so the next `make up` retries cleanly,
            # and bail immediately (don't waste time seeding the rest only
            # to truncate it).
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
            # Explicit `make seed-demo` mode: one failed scenario must NOT
            # abort the rest. A single environmental hiccup (e.g. an
            # Elasticsearch/OpenSearch disk-watermark create-index block on
            # just one engine) used to hard-stop here via `return 1`, silently
            # costing the operator every scenario after the first failure (the
            # classic "I only got 2 of 5 studies" symptom). Keep going so the
            # operator gets every scenario that CAN seed, then report the
            # failures in a summary at the end. See docs/03_runbooks/local-dev.md
            # → "Demo seed produced fewer studies than expected".
            continue

    apply_study_renames(results)

    # Rich-data scenario — fifth, optional. Adds the 1000-product ESCI dataset
    # + LLM-generated judgments + a real 15-trial study. Tolerated failure:
    # the small scenarios are useful on their own, so a rich-scenario
    # crash (LLM rate limit, ES unreachable, judgment-gen timeout) leaves the
    # rest of the seed valid. The operator gets a warning + retry instruction.
    # The rich scenario is an Elasticsearch scenario; gate it on ES reachability
    # the same way the loop gates each scenario (infra_solr_ci_readiness FR-3).
    if not _engine_reachable(ES, "elasticsearch"):
        print(
            f"[skip] acme-products-rich-prod — elasticsearch unreachable at {ES}",
            file=sys.stderr,
        )
        skipped.append("acme-products-rich-prod")
    else:
        try:
            rich_result = seed_rich_scenario()
            if rich_result.get("study_id"):
                results.append(rich_result)
        except Exception as exc:  # noqa: BLE001 — deliberately broad; see comment
            print(
                f"\n!! rich scenario FAILED: {exc!r}\n"
                "   The small-data scenarios above are still valid.\n"
                "   Re-run `make seed-demo FORCE=1` once the cause is resolved.",
                file=sys.stderr,
            )

    print("\n=== seed complete ===")
    for r in results:
        # Study-less entries (Solr-minimum, Story A13): no study was seeded —
        # surface the cluster registration + next-step hint instead of the
        # study line so the operator knows the Solr scenario landed partially.
        if "study_id" not in r:
            print(
                f"  {r.get('scenario', '?')}: cluster registered, no study "
                f"— {r.get('next_step', 'create the demo study via the UI')}"
            )
            continue
        print(f"  {r['slug']}: study={r['study_id']} ({r['study_name']})")

    # Engine-unreachable skips are a distinct, non-error outcome — list them in
    # their own summary section so an operator who didn't start every engine
    # knows what's missing (and that it's recoverable by starting the engine +
    # re-running). (infra_solr_ci_readiness FR-3.)
    if skipped:
        print(
            f"\n=== {len(skipped)} scenario(s) SKIPPED (engine unreachable) ===",
            file=sys.stderr,
        )
        for slug in skipped:
            print(f"  {slug}", file=sys.stderr)
        print(
            "Start the missing engine(s) (ES :9200 / OpenSearch :9201 / "
            "Solr :8983) and re-run `make seed-demo FORCE=1` to seed them — "
            "see docs/03_runbooks/demo-reseed-engine-tolerance.md.",
            file=sys.stderr,
        )

    # Exit-code order matters: check real failures FIRST so a mid-flight error
    # (plus some skips) is never mislabeled as "all engines unreachable".
    # If any small scenario failed in explicit-force mode we still seeded the
    # rest, but the demo is incomplete — surface a loud summary and exit
    # non-zero so the operator (and any caller checking the exit code) knows.
    if failures:
        print(
            f"\n=== {len(failures)} scenario(s) FAILED — demo is incomplete ===",
            file=sys.stderr,
        )
        for slug, err in failures:
            print(f"  {slug}: {err!r}", file=sys.stderr)
        print(
            "Re-run `make seed-demo FORCE=1` after resolving the cause. If the "
            "failure is a 403 index_create_block_exception / "
            "FORBIDDEN/.../cluster create-index blocked, the engine hit its disk "
            "flood-stage watermark — see docs/03_runbooks/local-dev.md → "
            "'Demo seed produced fewer studies than expected'.",
            file=sys.stderr,
        )
        return 1

    # No real failures, but nothing seeded AND something was skipped → every
    # engine was unreachable. That's a hard failure (not a no-op success):
    # mirrors the orchestrator's AllEnginesUnreachableError invariant.
    if not results and skipped:
        print(
            "\nERROR: all engines unreachable — start at least one engine (ES/OS/Solr) and retry.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
