"""ORM model registry (infra_adapter_elastic Story 1.2).

Importing this package registers every ORM model with ``Base.metadata`` so
Alembic ``--autogenerate`` and ``Base.metadata.create_all`` see them. The
``__all__`` list is the public surface for ``from backend.app.db.models
import Cluster, ConfigRepo``-style imports.
"""

from backend.app.db.models.cluster import Cluster
from backend.app.db.models.config_repo import ConfigRepo

__all__ = ["Cluster", "ConfigRepo"]
