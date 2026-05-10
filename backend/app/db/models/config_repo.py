"""``config_repos`` ORM model (infra_adapter_elastic Story 1.2 / FR-5).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"config_repos".

MVP1 only the ``github`` provider is supported (CHECK enforced); MVP3 adds
``gitlab`` and ``bitbucket`` per CLAUDE.md release matrix.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class ConfigRepo(Base):
    """One registered Git config repo (target of merge requests)."""

    __tablename__ = "config_repos"
    __table_args__ = (
        CheckConstraint("provider IN ('github')", name="config_repos_provider_check"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    """UUIDv7 hex."""

    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    """Operator-supplied stable identifier."""

    provider: Mapped[str] = mapped_column(String, nullable=False)
    """One of ``github`` (MVP1). MVP3 extends to ``gitlab | bitbucket``."""

    repo_url: Mapped[str] = mapped_column(String, nullable=False)
    """HTTPS clone URL of the config repo."""

    default_branch: Mapped[str] = mapped_column(String, nullable=False, server_default="main")
    """Repo default branch, e.g. ``main`` or ``master``."""

    pr_base_branch: Mapped[str] = mapped_column(String, nullable=False, server_default="main")
    """Branch the PR worker targets when opening pull requests."""

    auth_ref: Mapped[str] = mapped_column(String, nullable=False)
    """Key into the mounted secrets bundle for this repo's PAT."""

    webhook_secret_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    """Key into the mounted secrets bundle for the webhook HMAC secret."""

    webhook_registration_error: Mapped[str | None] = mapped_column(String, nullable=True)
    """Last error from automated webhook registration; ``NULL`` when registered cleanly."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """Insert timestamp (UTC)."""
