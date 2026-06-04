# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Repository registry (infra_adapter_elastic + feat_study_lifecycle Phase 1+2).

One module per aggregate. Every repository function takes ``db: AsyncSession``
as the first argument, uses ``db.flush()`` for staging, and lets the caller
commit per CLAUDE.md "Repository Layer" convention.
"""

from backend.app.db.repo.cluster import (
    count_clusters,
    create_cluster,
    get_active_cluster_by_name,
    get_any_cluster_by_name,
    get_cluster,
    get_cluster_by_id_for_update,
    list_clusters,
    revive_cluster,
    soft_delete_cluster,
    update_cluster_engine_config,
)
from backend.app.db.repo.config_repo import (
    count_config_repos,
    create_config_repo,
    find_currently_live_proposal_ids,
    get_config_repo,
    get_config_repo_by_name,
    get_config_repo_with_last_merged_proposal,
    list_config_repos,
    lookup_config_repo_by_owner_repo,
    set_webhook_registration_error,
    update_config_repo_last_merged_pointer,
)
from backend.app.db.repo.conversation import (
    count_conversations,
    create_conversation,
    create_message,
    get_conversation,
    list_conversations,
    list_conversations_with_preview_data,
    list_messages,
    soft_delete_conversation,
    update_conversation_title,
)
from backend.app.db.repo.digest import (
    create_digest,
    get_digest_for_study,
    hard_delete_digest,
)
from backend.app.db.repo.judgment import (
    JudgmentListRefRow,
    JudgmentRefCounts,
    bulk_create_judgments,
    count_and_sample_judgment_refs,
    count_judgments_for_list,
    count_judgments_for_list_and_query,
    count_judgments_per_query,
    create_judgment,
    get_judgment,
    list_doc_ids_for_list_and_query,
    list_judgments_paginated,
    source_breakdown_for_list,
    upsert_judgment_human_override,
)
from backend.app.db.repo.judgment_list import (
    count_judgment_lists,
    create_judgment_list,
    get_judgment_list,
    hard_delete_judgment_list,
    list_generating_judgment_list_ids,
    list_judgment_lists,
    update_judgment_list_calibration,
    update_judgment_list_status,
)
from backend.app.db.repo.proposal import (
    InvalidStateTransition,
    ProposalStatusFilter,
    count_proposals,
    create_proposal,
    get_proposal,
    hard_delete_proposal,
    list_pending_proposals_for_boot_scan,
    list_pr_opened_proposals_for_reconcile,
    list_proposals_paginated,
    lookup_proposal_by_pr_url,
    mark_proposal_pr_closed,
    mark_proposal_pr_merged,
    mark_proposal_pr_merged_from_closed,
    mark_proposal_pr_opened,
    mark_proposal_pr_reopened,
    reject_proposal,
    set_proposal_pr_open_error,
    stamp_proposal_last_polled_at,
    update_proposal_for_digest,
)
from backend.app.db.repo.query import (
    bulk_create_queries,
    count_queries_for_set,
    create_query,
    delete_query,
    find_first_judged_query,
    get_query,
    list_queries_for_set,
    list_queries_for_set_cursor,
    update_query,
)
from backend.app.db.repo.query_set import (
    count_queries_for_sets,
    count_queries_in_set,
    count_query_sets,
    create_query_set,
    get_query_set,
    hard_delete_query_set,
    list_query_sets,
)
from backend.app.db.repo.query_template import (
    count_query_templates,
    create_query_template,
    get_query_template,
    get_query_template_by_name_version,
    hard_delete_query_template,
    list_query_templates,
)
from backend.app.db.repo.study import (
    ChainTraversalResult,
    count_studies,
    create_study,
    get_chain_for_study,
    get_study,
    hard_delete_study,
    list_children_of_study,
    list_queued_study_ids,
    list_recent_completed_chains,
    list_running_study_ids,
    list_studies,
)
from backend.app.db.repo.trial import (
    TrialCounts,
    TrialsSummary,
    aggregate_trials_summary,
    count_trials,
    count_trials_for_studies,
    create_trial,
    get_trial,
    list_complete_optuna_trials_for_studies,
    list_complete_optuna_trials_for_study,
    list_trials_for_study,
    list_trials_paginated,
)

__all__ = [
    # Cluster aggregate (infra_adapter_elastic + infra_adapter_solr Story A9)
    "count_clusters",
    "create_cluster",
    "create_config_repo",
    "get_active_cluster_by_name",
    "get_any_cluster_by_name",
    "get_cluster",
    "get_cluster_by_id_for_update",
    "get_config_repo",
    "get_config_repo_by_name",
    "list_clusters",
    "revive_cluster",
    "soft_delete_cluster",
    "update_cluster_engine_config",
    # feat_study_lifecycle Phase 1
    "create_judgment_list",
    "create_proposal",
    "create_query",
    "create_query_set",
    "create_query_template",
    "create_study",
    "create_trial",
    "get_judgment_list",
    "get_proposal",
    "get_query_set",
    "get_query_template",
    "get_query_template_by_name_version",
    "get_study",
    "list_queries_for_set",
    "list_trials_for_study",
    # feat_study_lifecycle Phase 2 Story 1.4 extensions
    "TrialsSummary",
    "aggregate_trials_summary",
    "bulk_create_queries",
    "count_queries_for_sets",
    "count_queries_in_set",
    "count_query_sets",
    "count_query_templates",
    "count_studies",
    "count_trials",
    "list_query_sets",
    "list_query_templates",
    "list_children_of_study",
    "list_queued_study_ids",
    "list_running_study_ids",
    "list_studies",
    "list_trials_paginated",
    # feat_overnight_autopilot Story 1.2 — chain traversal for the rolled-up
    # overnight-chain summary (FR-3).
    "ChainTraversalResult",
    "get_chain_for_study",
    # feat_overnight_studies_summary_card Story 1.1 — recent-completed-chains
    # discovery feeding the "Ran while you were away" card on /studies (FR-1).
    "list_recent_completed_chains",
    # feat_llm_judgments Story 1.2 (judgments child table + judgment_list extensions)
    "bulk_create_judgments",
    "count_judgment_lists",
    "count_judgments_for_list",
    "count_judgments_for_list_and_query",
    "create_judgment",
    "get_judgment",
    "list_generating_judgment_list_ids",
    "list_judgment_lists",
    "list_judgments_paginated",
    "source_breakdown_for_list",
    "update_judgment_list_calibration",
    "update_judgment_list_status",
    "upsert_judgment_human_override",
    # feat_digest_proposal Story 1.2 (digest repo + proposal repo extensions)
    "InvalidStateTransition",
    "ProposalStatusFilter",
    "count_proposals",
    "create_digest",
    "get_digest_for_study",
    "list_pending_proposals_for_boot_scan",
    "list_proposals_paginated",
    "reject_proposal",
    "update_proposal_for_digest",
    # feat_github_pr_worker Story 1.1 (config_repo list/count + proposal pr-transition helpers)
    "count_config_repos",
    "list_config_repos",
    "mark_proposal_pr_opened",
    "set_proposal_pr_open_error",
    # feat_config_repo_baseline_tracking Story 1.2 (last-merged pointer helpers)
    "find_currently_live_proposal_ids",
    "get_config_repo_with_last_merged_proposal",
    "update_config_repo_last_merged_pointer",
    # feat_github_webhook Story 1.4 (webhook receiver + polling reconciler + auto-register)
    "list_pr_opened_proposals_for_reconcile",
    "lookup_config_repo_by_owner_repo",
    "lookup_proposal_by_pr_url",
    "mark_proposal_pr_closed",
    "mark_proposal_pr_merged",
    "mark_proposal_pr_merged_from_closed",
    "mark_proposal_pr_reopened",
    "set_webhook_registration_error",
    # chore_reconciler_terminal_closed_no_poll FR-2
    "stamp_proposal_last_polled_at",
    # feat_chat_agent Story 1.3 (conversations + messages aggregate)
    "count_conversations",
    "create_conversation",
    "create_message",
    "get_conversation",
    "list_conversations",
    "list_conversations_with_preview_data",
    "list_messages",
    "soft_delete_conversation",
    "update_conversation_title",
    # feat_query_inline_crud Stories 1.2 + 2.2 + 3.2 (per-query CRUD)
    "JudgmentListRefRow",
    "JudgmentRefCounts",
    "count_and_sample_judgment_refs",
    "count_judgments_per_query",
    "count_queries_for_set",
    "delete_query",
    "get_query",
    # feat_agent_propose_search_space Story 2.1
    "get_trial",
    "list_queries_for_set_cursor",
    "update_query",
    # chore_e2e_test_rows_isolation Story 1.1 — hard-delete for test-only cleanup
    "hard_delete_digest",
    "hard_delete_judgment_list",
    "hard_delete_proposal",
    "hard_delete_query_set",
    "hard_delete_query_template",
    "hard_delete_study",
    # feat_study_preflight_overlap_probe Story 1.1 — repo helpers for the
    # create-time overlap probe.
    "find_first_judged_query",
    "list_doc_ids_for_list_and_query",
    # feat_study_convergence_indicator Story 2.1 — read-side helper feeding
    # the trailing-window-flat convergence classifier.
    "list_complete_optuna_trials_for_study",
    # feat_studies_convergence_visibility Story 1.1 — batched count + trial
    # load for the studies-list trial_count + convergence_verdict fields.
    "TrialCounts",
    "count_trials_for_studies",
    "list_complete_optuna_trials_for_studies",
]
