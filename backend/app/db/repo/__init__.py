"""Repository function registry (infra_adapter_elastic Story 1.4).

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

__all__ = [
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
]
