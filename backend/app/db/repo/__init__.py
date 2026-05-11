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
    create_config_repo,
    get_config_repo,
    get_config_repo_by_name,
)
from backend.app.db.repo.judgment_list import (
    create_judgment_list,
    get_judgment_list,
)
from backend.app.db.repo.proposal import (
    create_proposal,
    get_proposal,
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
]
