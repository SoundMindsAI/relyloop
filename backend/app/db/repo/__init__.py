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
    list_clusters,
    revive_cluster,
    soft_delete_cluster,
)
from backend.app.db.repo.config_repo import (
    count_config_repos,
    create_config_repo,
    get_config_repo,
    get_config_repo_by_name,
    list_config_repos,
    lookup_config_repo_by_owner_repo,
    set_webhook_registration_error,
)
from backend.app.db.repo.digest import (
    create_digest,
    get_digest_for_study,
)
from backend.app.db.repo.judgment import (
    bulk_create_judgments,
    count_judgments_for_list,
    count_judgments_for_list_and_query,
    create_judgment,
    get_judgment,
    list_judgments_paginated,
    source_breakdown_for_list,
    upsert_judgment_human_override,
)
from backend.app.db.repo.judgment_list import (
    count_judgment_lists,
    create_judgment_list,
    get_judgment_list,
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
    list_pending_proposals_for_boot_scan,
    list_pr_opened_proposals_for_reconcile,
    list_proposals_paginated,
    lookup_proposal_by_pr_url,
    mark_proposal_pr_closed,
    mark_proposal_pr_merged,
    mark_proposal_pr_opened,
    mark_proposal_pr_reopened,
    reject_proposal,
    set_proposal_pr_open_error,
    update_proposal_for_digest,
)
from backend.app.db.repo.query import (
    bulk_create_queries,
    create_query,
    list_queries_for_set,
)
from backend.app.db.repo.query_set import (
    count_queries_in_set,
    count_query_sets,
    create_query_set,
    get_query_set,
    list_query_sets,
)
from backend.app.db.repo.query_template import (
    count_query_templates,
    create_query_template,
    get_query_template,
    get_query_template_by_name_version,
    list_query_templates,
)
from backend.app.db.repo.study import (
    count_studies,
    create_study,
    get_study,
    list_queued_study_ids,
    list_running_study_ids,
    list_studies,
)
from backend.app.db.repo.trial import (
    TrialsSummary,
    aggregate_trials_summary,
    count_trials,
    create_trial,
    list_trials_for_study,
    list_trials_paginated,
)

__all__ = [
    # Cluster aggregate (infra_adapter_elastic)
    "count_clusters",
    "create_cluster",
    "create_config_repo",
    "get_active_cluster_by_name",
    "get_any_cluster_by_name",
    "get_cluster",
    "get_config_repo",
    "get_config_repo_by_name",
    "list_clusters",
    "revive_cluster",
    "soft_delete_cluster",
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
    "count_queries_in_set",
    "count_query_sets",
    "count_query_templates",
    "count_studies",
    "count_trials",
    "list_query_sets",
    "list_query_templates",
    "list_queued_study_ids",
    "list_running_study_ids",
    "list_studies",
    "list_trials_paginated",
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
    # feat_github_webhook Story 1.4 (webhook receiver + polling reconciler + auto-register)
    "list_pr_opened_proposals_for_reconcile",
    "lookup_config_repo_by_owner_repo",
    "lookup_proposal_by_pr_url",
    "mark_proposal_pr_closed",
    "mark_proposal_pr_merged",
    "mark_proposal_pr_reopened",
    "set_webhook_registration_error",
]
