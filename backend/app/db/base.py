"""Declarative Base for all RelyLoop ORM models (infra_foundation Story 2.1).

The model registry is intentionally empty in MVP1 — business tables arrive with
their owning features (per ``docs/01_architecture/data-model.md``):

- ``infra_adapter_elastic``: ``clusters``, ``config_repos``
- ``feat_study_lifecycle``: ``query_sets``, ``query_templates``, ``judgment_lists``,
  ``studies``, ``trials``, ``proposals``
- ``feat_llm_judgments``: ``judgments``
- ``feat_digest_proposal``: ``digests``
- ``feat_chat_agent``: ``conversations``, ``messages``

Each feature's models import ``Base`` from this module, define their ORM class,
and Alembic's ``--autogenerate`` picks them up via ``target_metadata = Base.metadata``
in ``migrations/env.py`` (wired by Story 2.2).
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all RelyLoop ORM models."""
