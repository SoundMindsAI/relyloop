"""Application settings (infra_foundation Story 2.1, FR-3 application layer).

RelyLoop reads secrets from mounted files via ``*_FILE``-suffixed env vars per
[`docs/01_architecture/deployment.md` §"Secrets"](../../../docs/01_architecture/deployment.md).
Bare env vars (e.g. ``OPENAI_API_KEY=sk-...``) are NOT supported for secrets —
they appear in container ``inspect`` output, container logs, and ``ps``-style
introspection, defeating the secrets-management purpose (CLAUDE.md Absolute
Rule #2).

Required secrets (raise ``SettingsError`` on missing or empty content):
    - ``DATABASE_URL_FILE``
    - ``POSTGRES_PASSWORD_FILE``

Optional secrets (return ``None`` on missing/empty; API logs WARN at startup):
    - ``OPENAI_API_KEY_FILE``
    - ``GITHUB_TOKEN_FILE``
    - ``CLUSTER_CREDENTIALS_FILE``

Plain values (env-var literal):
    ``REDIS_URL``, ``OPENAI_BASE_URL``, ``OPENAI_MODEL``, ``OPENAI_MODEL_CHAT``,
    ``OPENAI_DAILY_BUDGET_USD``, ``RELYLOOP_GIT_SHA``, ``ES_HEAP_SIZE``,
    ``RELYLOOP_ALLOW_PRIVATE_CLUSTERS``, ``STUDIES_DEFAULT_PARALLELISM``,
    ``STUDIES_DEFAULT_TIMEOUT_S``.

Use ``get_settings()`` (lru_cache'd) anywhere settings are needed; never
instantiate ``Settings()`` directly.
"""

from functools import cached_property, lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(RuntimeError):
    """Raised when a required secret file is missing or empty at startup."""


def _read_secret_file(path: Path | None, *, required: bool, name: str) -> str | None:
    """Read a mounted secret file's content (stripped).

    Args:
        path: The ``Path`` from a ``*_FILE`` setting, or ``None`` if unset.
        required: If True, missing/empty content raises ``SettingsError``.
        name: Human-readable secret name for error messages.

    Returns:
        The file content stripped of trailing whitespace, or ``None`` for
        optional secrets that are missing/empty.
    """
    if path is None or not path.exists():
        if required:
            raise SettingsError(
                f"Required secret {name} is not configured: file path is missing or unreadable. "
                f"Run `make up` to auto-generate, or check ./secrets/ exists."
            )
        return None
    content = path.read_text().strip()
    if not content:
        if required:
            raise SettingsError(
                f"Required secret {name} is empty at {path}. Populate the file before starting."
            )
        return None
    return content


class Settings(BaseSettings):
    """Application configuration loaded from env vars and mounted secret files."""

    model_config = SettingsConfigDict(
        env_file=None,  # Settings read from env directly; .env is for Compose substitution
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
    )

    # Required secret-file paths (resolved content via @cached_property below)
    database_url_file: Path = Field(
        description="Path to file containing the Postgres SQLAlchemy URL"
    )
    postgres_password_file: Path = Field(
        description="Path to file containing the Postgres password"
    )

    # Optional secret-file paths
    openai_api_key_file: Path | None = Field(
        default=None,
        description="Path to file containing the OpenAI API key (or any OpenAI-compatible "
        "endpoint's key). Optional pre-feat_llm_judgments; empty file = not configured.",
    )
    github_token_file: Path | None = Field(
        default=None,
        description="Path to file containing the GitHub PAT. Optional pre-feat_github_pr_worker.",
    )
    cluster_credentials_file: Path | None = Field(
        default=None,
        description="Path to YAML file containing per-cluster credentials. "
        "Optional pre-infra_adapter_elastic; empty doc {} = no clusters need creds.",
    )

    # Plain values
    redis_url: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection URL for Arq queue + capability cache",
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI-compatible endpoint root. For local LLM, "
        "e.g. http://host.docker.internal:11434/v1 (Ollama)",
    )
    openai_model: str = Field(
        default="gpt-4o-2024-08-06",
        description="LLM model for judgment generation + digest narrative",
    )
    openai_model_chat: str = Field(
        default="gpt-4o-mini-2024-07-18",
        description="LLM model for chat orchestrator (cost-sensitive)",
    )
    openai_daily_budget_usd: float = Field(
        default=10.0,
        description="Rolling 24h spend cap. 0 disables the budget guard.",
    )
    relyloop_git_sha: str = Field(
        default="dev",
        description="Build-time git SHA injected via Docker ARG; surfaced in /healthz.version",
    )
    # feat_github_pr_worker Story 1.3 — operator-configured URL used to
    # construct study-detail links in PR bodies. None → links omitted.
    relyloop_base_url: str | None = Field(
        default=None,
        description=(
            "Base URL of the operator's RelyLoop install. "
            "Used to construct study-detail links in PR bodies (e.g. "
            "https://relyloop.internal.acme.com/studies/{id}). "
            "None → study link omitted from PR body."
        ),
    )
    # feat_github_pr_worker Story 1.3 + cycle-2 F3 — bot identity for
    # commits opened by the PR worker. Operator MUST override the email
    # in production via env var; the default is a safe placeholder so
    # dev installs don't ship a real-looking address.
    relyloop_git_author_name: str = Field(
        default="relyloop-bot",
        description=(
            "Commit author + committer NAME used by the PR worker when "
            "creating commits in operator config repos."
        ),
    )
    relyloop_git_author_email: str = Field(
        default="relyloop-bot@example.com",
        description=(
            "Commit author + committer EMAIL used by the PR worker. "
            "Operator MUST override this in production via env var to "
            "the install-domain bot address."
        ),
    )
    relyloop_pr_poll_minutes: int = Field(
        default=15,
        ge=1,
        le=1440,
        description=(
            "Cron cadence for the reconcile_pr_state worker (feat_github_webhook "
            "FR-2). MVP1 default 15. Restricted to the whitelist of "
            "cron-expressible values: divisors of 60 (1, 2, 3, 4, 5, 6, 10, 12, "
            "15, 20, 30, 60) plus multiples of 60 that divide 1440 (120, 180, "
            "240, 360, 720, 1440). Values outside this set raise at startup; "
            "see backend.workers.pr_reconcile.SUPPORTED_POLL_MINUTES."
        ),
    )

    @field_validator("relyloop_pr_poll_minutes")
    @classmethod
    def _validate_pr_poll_minutes(cls, value: int) -> int:
        """Narrow ``relyloop_pr_poll_minutes`` to the cron-expressible whitelist.

        Whitelist lives in :data:`backend.workers.pr_reconcile.SUPPORTED_POLL_MINUTES`
        — keeping the validator here means a misconfigured operator sees the
        error at boot rather than at the first cron tick.
        """
        from backend.workers.pr_reconcile import SUPPORTED_POLL_MINUTES

        if value not in SUPPORTED_POLL_MINUTES:
            raise ValueError(
                f"RELYLOOP_PR_POLL_MINUTES={value} is not in the supported set "
                f"{sorted(SUPPORTED_POLL_MINUTES)}. Pick a divisor of 60 (≤60) or a "
                "multiple of 60 that divides 1440 (>60)."
            )
        return value

    es_heap_size: str = Field(
        default="512m",
        description="ES_JAVA_OPTS heap sizing for the elasticsearch+opensearch containers",
    )
    relyloop_allow_private_clusters: bool = Field(
        default=True,
        description="Permit cluster registration against private-range / loopback IPs. "
        "Default True for MVP1 (laptop convenience) per spec §10 Threat 3; flips to "
        "False at MVP3 hardening so production deployments can't accidentally point "
        "at internal hosts.",
    )
    # Comma-separated list of allowed CORS origins for the browser UI.
    # Default covers the Next dev server (localhost:3000) and the same host
    # via LAN IP (Next prints both URLs on startup). Operators add their
    # production origin when MVP3 staging lands. Empty string disables CORS.
    cors_allow_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description=(
            "Comma-separated list of origins the API permits in the "
            "Access-Control-Allow-Origin response header. MVP1 default "
            "covers the local Next dev server. Set to empty string to "
            "disable CORS entirely."
        ),
    )
    # feat_study_lifecycle Phase 2 fallbacks. The API layer does NOT
    # materialize these into the stored `studies.config` JSONB — the keys
    # stay omitted so `infra_optuna_eval`'s pruner key-presence contract
    # (spec FR-2 explicit-override semantics) remains intact. The worker
    # reads these via `get_settings()` at job time when the key is absent.
    studies_default_parallelism: int = Field(
        default=4,
        ge=1,
        le=64,
        description="Fallback for `studies.config.parallelism` when omitted "
        "at study create. Operator-tunable without redeploy.",
    )
    studies_default_timeout_s: int = Field(
        default=60,
        ge=5,
        le=3600,
        description="Fallback for `studies.config.trial_timeout_s` when "
        "omitted at study create. Bounds the wall-clock budget for a single "
        "Optuna trial. Operator-tunable without redeploy.",
    )

    @cached_property
    def database_url(self) -> str:
        """Resolved Postgres URL from ``DATABASE_URL_FILE``. Required."""
        content = _read_secret_file(self.database_url_file, required=True, name="DATABASE_URL")
        # _read_secret_file raises when required=True and the secret is missing,
        # so the None branch here is unreachable — narrow for mypy.
        if content is None:  # pragma: no cover  - unreachable, see above
            raise SettingsError("required secret resolved to None unexpectedly")
        return content

    @cached_property
    def postgres_password(self) -> str:
        """Resolved Postgres password from ``POSTGRES_PASSWORD_FILE``. Required."""
        content = _read_secret_file(
            self.postgres_password_file, required=True, name="POSTGRES_PASSWORD"
        )
        if content is None:  # pragma: no cover  - unreachable, see database_url
            raise SettingsError("required secret resolved to None unexpectedly")
        return content

    @cached_property
    def openai_api_key(self) -> str | None:
        """Resolved OpenAI key. Returns ``None`` if file is missing or empty."""
        return _read_secret_file(self.openai_api_key_file, required=False, name="OPENAI_API_KEY")

    @cached_property
    def github_token(self) -> str | None:
        """Resolved GitHub PAT. Returns ``None`` if file is missing or empty."""
        return _read_secret_file(self.github_token_file, required=False, name="GITHUB_TOKEN")

    @cached_property
    def cluster_credentials_yaml(self) -> str | None:
        """Resolved cluster-credentials YAML body. Returns ``None`` if missing/empty."""
        return _read_secret_file(
            self.cluster_credentials_file,
            required=False,
            name="CLUSTER_CREDENTIALS",
        )


@lru_cache
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    Uses ``lru_cache`` so the file-IO behind the @cached_property accessors only
    runs once per process. Tests using ``monkeypatch.setenv`` should call
    ``get_settings.cache_clear()`` between tests to force re-read.
    """
    return Settings()
