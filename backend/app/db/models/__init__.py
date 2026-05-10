"""ORM model registry (infra_adapter_elastic Story 1.2 + feat_study_lifecycle Phase 1 Story 1.1).

Importing this package registers every ORM model with ``Base.metadata`` so
Alembic ``--autogenerate`` and ``Base.metadata.create_all`` see them. The
``__all__`` list is the public surface for ``from backend.app.db.models
import Cluster, ConfigRepo, Study, ...``-style imports.
"""

from backend.app.db.models.cluster import Cluster
from backend.app.db.models.config_repo import ConfigRepo
from backend.app.db.models.judgment_list import JudgmentList
from backend.app.db.models.proposal import Proposal
from backend.app.db.models.query import Query
from backend.app.db.models.query_set import QuerySet
from backend.app.db.models.query_template import QueryTemplate
from backend.app.db.models.study import Study
from backend.app.db.models.trial import Trial

__all__ = [
    "Cluster",
    "ConfigRepo",
    "JudgmentList",
    "Proposal",
    "Query",
    "QuerySet",
    "QueryTemplate",
    "Study",
    "Trial",
]
