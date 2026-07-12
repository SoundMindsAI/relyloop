# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Digest, proposal, and config-repo models (feat_digest_proposal + feat_github_pr_worker)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.api.v1._wire_types import (
    ConfigRepoProviderWire,
    ProposalPrStateWire,
    ProposalStatusWire,
)
from backend.app.domain.study.followups import FollowupItem

# ---------------------------------------------------------------------------
# feat_digest_proposal Epic 3 schemas (Stories 3.1-3.4)
# ---------------------------------------------------------------------------


class DigestResponse(BaseModel):
    """Body of ``GET /api/v1/studies/{id}/digest`` (FR-3 / AC-3).

    feat_digest_executable_followups Story 4.1 — ``suggested_followups`` is
    now a discriminated-union list (NarrowFollowup | WidenFollowup |
    TextFollowup), populated by the digest handler via
    ``parse_followup_list(digest.suggested_followups, ...)`` so legacy or
    malformed JSONB payloads never crash the response.
    """

    id: str
    study_id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[FollowupItem]
    generated_by: str
    generated_at: datetime


class CreateProposalRequest(BaseModel):
    """Body of ``POST /api/v1/proposals`` (manual proposal creation, FR-4 / AC-6)."""

    cluster_id: str = Field(min_length=1, max_length=36)
    template_id: str = Field(min_length=1, max_length=36)
    config_diff: dict[str, Any]
    metric_delta: dict[str, Any] | None = None


class RejectProposalRequest(BaseModel):
    """Body of ``POST /api/v1/proposals/{id}/reject`` (FR-4 / AC-5)."""

    reason: str | None = Field(default=None, max_length=500)


class _ClusterEmbed(BaseModel):
    """Inline cluster summary on proposal responses."""

    id: str
    name: str
    engine_type: str
    environment: str | None = None


class _TemplateEmbed(BaseModel):
    """Inline template summary on proposal responses."""

    id: str
    name: str
    version: int
    engine_type: str | None = None


class _StudySummary(BaseModel):
    """Inline study summary on the proposal-detail response."""

    id: str
    name: str
    status: str
    best_metric: float | None
    best_trial_id: str | None
    query_set: dict[str, Any]
    judgment_list: dict[str, Any]


class _DigestEmbed(BaseModel):
    """Inline digest summary on the proposal-detail response.

    feat_digest_executable_followups Story 4.1 — ``suggested_followups`` is
    now a discriminated-union list (see ``DigestResponse``).
    """

    id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[FollowupItem]
    generated_at: datetime


class ProposalSummary(BaseModel):
    """Row in the ``GET /api/v1/proposals`` list response."""

    id: str
    study_id: str | None
    cluster: _ClusterEmbed
    template: _TemplateEmbed
    status: ProposalStatusWire
    pr_state: ProposalPrStateWire | None
    pr_url: str | None
    metric_delta: dict[str, Any] | None
    is_currently_live: bool = False
    """True when this proposal is some ``config_repos.last_merged_proposal_id``
    (feat_config_repo_baseline_tracking FR-5). Pointer-only derivation —
    symmetric with ``?is_last_merged=true``. Defaults to False so list
    responses that don't populate the field (e.g., legacy callers) deserialize
    cleanly."""
    created_at: datetime


class ProposalDetail(BaseModel):
    """Body of the proposal detail endpoints.

    Used by ``GET /api/v1/proposals/{id}``, ``POST /api/v1/proposals``,
    and ``POST /api/v1/proposals/{id}/reject``.
    """

    id: str
    study_id: str | None
    study_summary: _StudySummary | None
    study_trial_id: str | None
    cluster: _ClusterEmbed
    template: _TemplateEmbed
    config_diff: dict[str, Any]
    metric_delta: dict[str, Any] | None
    status: ProposalStatusWire
    pr_url: str | None
    pr_state: ProposalPrStateWire | None
    pr_merged_at: datetime | None
    pr_open_error: str | None
    rejected_reason: str | None
    is_currently_live: bool = False
    """True when this proposal is some ``config_repos.last_merged_proposal_id``
    (feat_config_repo_baseline_tracking FR-5). See :class:`ProposalSummary`."""
    digest: _DigestEmbed | None
    created_at: datetime


class ProposalsListResponse(BaseModel):
    """Body of ``GET /api/v1/proposals``."""

    data: list[ProposalSummary]
    next_cursor: str | None
    has_more: bool


# ---------------------------------------------------------------------------
# feat_github_pr_worker schemas (Story 1.2)
# ---------------------------------------------------------------------------


class OpenPrResponse(BaseModel):
    """Body of ``POST /api/v1/proposals/{id}/open_pr`` (FR-1).

    Returned with HTTP 202 on successful enqueue. Status is always
    ``'pending'`` at enqueue time; the worker flips it to ``'pr_opened'``
    after the PR is open.
    """

    proposal_id: str
    status: Literal["pending"]
    message: str


class CreateConfigRepoRequest(BaseModel):
    """Body of ``POST /api/v1/config-repos`` (FR-3).

    ``provider`` is server-derived from ``repo_url`` (cycle-2 F4 from
    spec review) — NOT in the payload. The validator enforces a strict
    GitHub URL pattern; non-GitHub URLs surface as 400
    ``UNSUPPORTED_PROVIDER`` at the router layer.
    """

    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    repo_url: str = Field(min_length=1, max_length=512)
    # Git-ref-safe pattern (security audit 2026-07-11 finding #7): must start
    # with an alphanumeric so a value can never begin with '-' and be parsed by
    # git as an option (the classic `--upload-pack=...` argument-injection
    # shape); restrict to the safe branch-name charset. These fields flow as
    # positional git arguments in the open_pr worker.
    default_branch: str = Field(
        default="main", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
    )
    pr_base_branch: str = Field(
        default="main", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
    )
    auth_ref: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    webhook_secret_ref: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )


class ConfigRepoDetail(BaseModel):
    """``GET /api/v1/config-repos/{id}`` response + ``POST`` 201 body."""

    id: str
    name: str
    provider: ConfigRepoProviderWire
    repo_url: str
    default_branch: str
    pr_base_branch: str
    auth_ref: str
    webhook_secret_ref: str | None
    webhook_registration_error: str | None
    last_merged_proposal: ProposalSummary | None = None
    """The proposal currently tracked as the live config for this repo
    (feat_config_repo_baseline_tracking FR-4). NULL when no merge has occurred
    yet. Always present in detail responses (populated when the pointer is
    set). On list responses every row defaults to ``None`` — the list path
    does NOT JOIN the proposal embed to keep paginated list responses
    lightweight."""
    created_at: datetime


class ConfigReposListResponse(BaseModel):
    """``GET /api/v1/config-repos`` response."""

    data: list[ConfigRepoDetail]
    next_cursor: str | None
    has_more: bool
