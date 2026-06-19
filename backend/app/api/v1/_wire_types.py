# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Canonical wire-value ``Literal`` types for the ``/api/v1`` surface.

Every request/response enum, status value, and ``?sort=`` key the API
accepts or emits lives here as a single source of truth, re-exported from
``backend.app.api.v1.schemas`` for backwards compatibility. Per CLAUDE.md
"Enumerated Value Contract Discipline" each Literal carries a comment
pointing at its backend allowlist (DB CHECK / frozenset / Literal) and/or
the frontend ``ui/src/lib/enums.ts`` array it must stay in parity with.

These are pure type aliases — no model definitions, no imports beyond
``typing`` — so the file is safe to import from anywhere without circular
dependency risk.
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Cluster registry (feat infra_adapter_elastic / infra_adapter_solr)
# ---------------------------------------------------------------------------

EngineType = Literal["elasticsearch", "opensearch", "solr"]
"""Response-only: values are guaranteed by service-layer validation before the
DB write, so the response model is safe to lock down with ``Literal``.
``solr`` added by ``infra_adapter_solr`` (Story A6/A11)."""

Environment = Literal["prod", "staging", "dev"]
"""Both request- and response-side: spec §8.5 has no ENVIRONMENT_NOT_SUPPORTED
domain code, so invalid values surface as 422 VALIDATION_ERROR via Pydantic."""

AuthKind = Literal[
    "es_apikey", "es_basic", "opensearch_basic", "opensearch_sigv4", "solr_basic", "solr_apikey"
]
"""Response-only — see EngineType note. ``solr_basic`` / ``solr_apikey`` added
by ``infra_adapter_solr``."""

HealthStatusValue = Literal["green", "yellow", "red", "unreachable"]


# ---------------------------------------------------------------------------
# feat_study_lifecycle Phase 2 — query-template / query-set / study / trial.
# Per CLAUDE.md "Enumerated Value Contract Discipline" every wire Literal
# carries a source-of-truth comment.
# ---------------------------------------------------------------------------

# Values must match backend/app/adapters/registry.py SUPPORTED_ENGINE_TYPES.
EngineTypeWire = Literal["elasticsearch", "opensearch", "solr"]

# Values must match backend/app/db/models/study.py CHECK constraint AND
# backend/app/db/repo/study.py StudyStatusFilter Literal.
StudyStatusWire = Literal["queued", "running", "completed", "cancelled", "failed"]

# Values must match backend/app/eval/scoring.py SUPPORTED_METRICS frozenset.
# ERR@k is deferred to MVP2 per infra_optuna_eval feature_spec.md §3 / §FR-3 / §13.
ObjectiveMetric = Literal["ndcg", "map", "precision", "recall", "mrr"]

# Values must match backend/app/eval/scoring.py SUPPORTED_K_VALUES frozenset.
ObjectiveK = Literal[1, 3, 5, 10, 20, 50, 100]

ObjectiveDirection = Literal["maximize", "minimize"]

# Values must match backend/app/eval/types.py SamplerKind Literal.
SamplerKind = Literal["tpe", "random"]

# Values must match backend/app/eval/types.py PrunerKind Literal.
PrunerKind = Literal["median", "none"]

# Values must match backend/app/db/repo/trial.py TrialSortKey Literal.
TrialSortKey = Literal[
    "primary_metric_desc",
    "primary_metric_asc",
    "ended_at_desc",
    "ended_at_asc",
    "optuna_trial_number_asc",
]

# Values must match backend/app/db/models/trial.py CHECK constraint.
TrialStatusWire = Literal["complete", "failed", "pruned"]


# ---------------------------------------------------------------------------
# DataTable sort-key Literals (feat_data_table_primitive Story 1.3)
#
# Each ``<Resource>SortKey`` is the cross-product of sortable columns × {asc, desc}
# accepted by ``GET /api/v1/<resource>?sort=<value>``. Frontend mirrors these
# arrays in ``ui/src/lib/enums.ts`` (CI grep gate enforces parity).
# ---------------------------------------------------------------------------

# Values must match ui/src/lib/enums.ts CLUSTER_SORT_VALUES.
ClusterSortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
    "environment:asc",
    "environment:desc",
]

# Values must match ui/src/lib/enums.ts STUDY_SORT_VALUES.
StudySortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
    "completed_at:asc",
    "completed_at:desc",
    "best_metric:asc",
    "best_metric:desc",
    "status:asc",
    "status:desc",
]

# Values must match ui/src/lib/enums.ts QUERY_SET_SORT_VALUES.
QuerySetSortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
]

# Values must match ui/src/lib/enums.ts QUERY_TEMPLATE_SORT_VALUES.
QueryTemplateSortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
    "engine_type:asc",
    "engine_type:desc",
    "version:asc",
    "version:desc",
]

# Values must match ui/src/lib/enums.ts JUDGMENT_LIST_SORT_VALUES.
JudgmentListSortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
    "status:asc",
    "status:desc",
]

# Values must match ui/src/lib/enums.ts JUDGMENT_ROW_SORT_VALUES.
JudgmentRowSortKey = Literal[
    "created_at:asc",
    "created_at:desc",
    "rating:asc",
    "rating:desc",
    "source:asc",
    "source:desc",
]

# Values must match ui/src/lib/enums.ts PROPOSAL_SORT_VALUES.
ProposalSortKey = Literal[
    "created_at:asc",
    "created_at:desc",
    "status:asc",
    "status:desc",
    "pr_state:asc",
    "pr_state:desc",
]


# ---------------------------------------------------------------------------
# feat_llm_judgments / feat_ubi_judgments wire values
# ---------------------------------------------------------------------------

# Values must match backend/app/db/models/judgment_list.py CHECK constraint
# judgment_lists_status_check.
JudgmentListStatusWire = Literal["generating", "complete", "failed"]

# Values must match backend/app/db/models/judgment.py CHECK constraint
# judgments_source_check. `click` is live in MVP2 (feat_ubi_judgments FR-10) —
# UBI worker writes `source='click'` rows + the source filter accepts the value
# (see JudgmentSourceFilterWire below).
JudgmentSourceWire = Literal["llm", "human", "click"]

# Used as the ?source= filter on GET /judgment-lists/{id}/judgments.
# Widened in feat_ubi_judgments FR-10 to accept `click` so the UI's
# Source filter on judgment-list detail can surface UBI rows. Cycle 2 F6's
# rejection-at-API-boundary contract was superseded the moment UBI shipped
# click rows.
JudgmentSourceFilterWire = Literal["llm", "human", "click"]

# Values must match backend/app/db/models/judgment.py CHECK constraint
# judgments_rating_check.
RatingWire = Literal[0, 1, 2, 3]

# UBI converter kind — body of POST /api/v1/judgments/generate-from-ubi.
# Source-of-truth: this Literal + the UbiJudgmentGenerationRequest dataclass
# in backend/app/services/agent_judgments_dispatch.py.
UbiConverterKind = Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"]

# Superset surfaced by the frontend method picker (Story 4.2). The `llm`
# branch routes to POST /judgments/generate (existing); the three UBI
# branches route to POST /judgments/generate-from-ubi (Story 3.2). The
# UBI endpoint itself never accepts `llm` for `converter` — that mapping
# happens client-side.
JudgmentGenerationMethodWire = Literal["llm", "ctr_threshold", "dwell_time", "hybrid_ubi_llm"]

# UBI readiness rung label returned by GET /api/v1/clusters/{id}/ubi-readiness.
# Source-of-truth: the UbiReadinessRung Literal in
# backend/app/services/ubi_readiness.py.
UbiReadinessRungWire = Literal["rung_0", "rung_1", "rung_2", "rung_3"]

# UBI mapping strategy (FR-5 step 5 — how the worker joins UBI user_query
# strings to query_set.queries.query_text when they're ambiguous).
# `reject` is the default; under it ambiguous pairs are skipped per-query
# (NOT terminal — cycle-3 finding `ambiguous-mapping-behavior-contradictory`).
UbiMappingStrategyWire = Literal["reject", "first_match", "most_recent"]


# ---------------------------------------------------------------------------
# feat_digest_proposal wire values
# ---------------------------------------------------------------------------

ProposalStatusWire = Literal["pending", "pr_opened", "pr_merged", "rejected", "superseded"]
"""Wire values for ``proposals.status`` filter on ``GET /api/v1/proposals``.

Values must match backend/app/db/models/proposal.py CHECK
proposals_status_check (cycle-2 F4 / cycle-3 F1).
"""

ProposalSourceWire = Literal["study", "manual"]
"""Wire values for ``?source=`` filter on ``GET /api/v1/proposals``.

``study`` → ``study_id IS NOT NULL`` (proposal derived from a completed
study). ``manual`` → ``study_id IS NULL`` (operator-authored hand-crafted
proposal). Omit for both. Per chore_proposals_source_filter_server_side.

Values must match backend/app/db/repo/proposal.py ProposalSourceFilter +
ui/src/components/proposals/proposal-source-filter-chips.tsx (frontend
chip values exclude the meta `all` selection — that's a UI-only "no
filter" sentinel).
"""

ProposalPrStateWire = Literal["open", "closed", "merged"]
"""Wire values for ``proposals.pr_state``.

Values must match backend/app/db/models/proposal.py CHECK
proposals_pr_state_check.
"""


# ---------------------------------------------------------------------------
# feat_github_pr_worker wire values
# ---------------------------------------------------------------------------

ConfigRepoProviderWire = Literal["github"]
"""Wire values for ``config_repos.provider``.

Values must match backend/app/db/models/config_repo.py CHECK
config_repos_provider_check (MVP1: 'github' only; MVP3 extends to
'gitlab' / 'bitbucket').
"""


# ---------------------------------------------------------------------------
# feat_chat_agent wire values (Stories 3.1 + 3.2)
#
# Wire-value Literals also exported through the source-of-truth gate to
# ui/src/lib/enums.ts (Story 4.4). Values must match
# backend/app/db/models/message.py messages_role_check (CHECK constraint).
# ---------------------------------------------------------------------------

MessageRoleWire = Literal["user", "assistant", "tool"]
MESSAGE_ROLE_VALUES: tuple[str, ...] = ("user", "assistant", "tool")

SSEEventTypeWire = Literal["token", "tool_call", "tool_result", "done"]
SSE_EVENT_TYPE_VALUES: tuple[str, ...] = ("token", "tool_call", "tool_result", "done")
