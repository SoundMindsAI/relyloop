# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Pydantic request/response models for the ``/api/v1`` surface.

Split into feature submodules (clusters, studies, judgments, proposals,
conversations, ubi, comparison). This package re-exports every public
name so ``from backend.app.api.v1.schemas import X`` keeps working. Wire
Literals live in ``_wire_types`` and are re-exported here too.
"""

from __future__ import annotations

from backend.app.api.v1._wire_types import MESSAGE_ROLE_VALUES as MESSAGE_ROLE_VALUES
from backend.app.api.v1._wire_types import SSE_EVENT_TYPE_VALUES as SSE_EVENT_TYPE_VALUES
from backend.app.api.v1._wire_types import AuthKind as AuthKind
from backend.app.api.v1._wire_types import ClusterSortKey as ClusterSortKey
from backend.app.api.v1._wire_types import ConfigRepoProviderWire as ConfigRepoProviderWire
from backend.app.api.v1._wire_types import EngineType as EngineType
from backend.app.api.v1._wire_types import EngineTypeWire as EngineTypeWire
from backend.app.api.v1._wire_types import Environment as Environment
from backend.app.api.v1._wire_types import HealthStatusValue as HealthStatusValue
from backend.app.api.v1._wire_types import (
    JudgmentGenerationMethodWire as JudgmentGenerationMethodWire,
)
from backend.app.api.v1._wire_types import JudgmentListSortKey as JudgmentListSortKey
from backend.app.api.v1._wire_types import JudgmentListStatusWire as JudgmentListStatusWire
from backend.app.api.v1._wire_types import JudgmentRowSortKey as JudgmentRowSortKey
from backend.app.api.v1._wire_types import JudgmentSourceFilterWire as JudgmentSourceFilterWire
from backend.app.api.v1._wire_types import JudgmentSourceWire as JudgmentSourceWire
from backend.app.api.v1._wire_types import MessageRoleWire as MessageRoleWire
from backend.app.api.v1._wire_types import ObjectiveDirection as ObjectiveDirection
from backend.app.api.v1._wire_types import ObjectiveK as ObjectiveK
from backend.app.api.v1._wire_types import ObjectiveMetric as ObjectiveMetric
from backend.app.api.v1._wire_types import ProposalPrStateWire as ProposalPrStateWire
from backend.app.api.v1._wire_types import ProposalSortKey as ProposalSortKey
from backend.app.api.v1._wire_types import ProposalSourceWire as ProposalSourceWire
from backend.app.api.v1._wire_types import ProposalStatusWire as ProposalStatusWire
from backend.app.api.v1._wire_types import PrunerKind as PrunerKind
from backend.app.api.v1._wire_types import QuerySetSortKey as QuerySetSortKey
from backend.app.api.v1._wire_types import QueryTemplateSortKey as QueryTemplateSortKey
from backend.app.api.v1._wire_types import RatingWire as RatingWire
from backend.app.api.v1._wire_types import SamplerKind as SamplerKind
from backend.app.api.v1._wire_types import SSEEventTypeWire as SSEEventTypeWire
from backend.app.api.v1._wire_types import StudySortKey as StudySortKey
from backend.app.api.v1._wire_types import StudyStatusWire as StudyStatusWire
from backend.app.api.v1._wire_types import TrialSortKey as TrialSortKey
from backend.app.api.v1._wire_types import TrialStatusWire as TrialStatusWire
from backend.app.api.v1._wire_types import UbiConverterKind as UbiConverterKind
from backend.app.api.v1._wire_types import UbiMappingStrategyWire as UbiMappingStrategyWire
from backend.app.api.v1._wire_types import UbiReadinessRungWire as UbiReadinessRungWire
from backend.app.api.v1.schemas.clusters import (
    ClusterDetail as ClusterDetail,
)
from backend.app.api.v1.schemas.clusters import (
    ClusterListResponse as ClusterListResponse,
)
from backend.app.api.v1.schemas.clusters import (
    ClusterSummary as ClusterSummary,
)
from backend.app.api.v1.schemas.clusters import (
    ConnectionTestRequest as ConnectionTestRequest,
)
from backend.app.api.v1.schemas.clusters import (
    ConnectionTestResult as ConnectionTestResult,
)
from backend.app.api.v1.schemas.clusters import (
    CreateClusterRequest as CreateClusterRequest,
)
from backend.app.api.v1.schemas.clusters import (
    DocumentListResponse as DocumentListResponse,
)
from backend.app.api.v1.schemas.clusters import (
    DocumentSummary as DocumentSummary,
)
from backend.app.api.v1.schemas.clusters import (
    HealthCheckResult as HealthCheckResult,
)
from backend.app.api.v1.schemas.clusters import (
    RunQueryHit as RunQueryHit,
)
from backend.app.api.v1.schemas.clusters import (
    RunQueryRequest as RunQueryRequest,
)
from backend.app.api.v1.schemas.clusters import (
    RunQueryResponse as RunQueryResponse,
)
from backend.app.api.v1.schemas.clusters import (
    TargetListResponse as TargetListResponse,
)
from backend.app.api.v1.schemas.clusters import (
    _validate_base_url_structure as _validate_base_url_structure,
)
from backend.app.api.v1.schemas.comparison import (
    CompareWarning as CompareWarning,
)
from backend.app.api.v1.schemas.comparison import (
    JudgmentListStudyResponse as JudgmentListStudyResponse,
)
from backend.app.api.v1.schemas.comparison import (
    StudyComparePairing as StudyComparePairing,
)
from backend.app.api.v1.schemas.comparison import (
    StudyPairResponse as StudyPairResponse,
)
from backend.app.api.v1.schemas.conversations import (
    ConversationDetail as ConversationDetail,
)
from backend.app.api.v1.schemas.conversations import (
    ConversationsListResponse as ConversationsListResponse,
)
from backend.app.api.v1.schemas.conversations import (
    ConversationSummary as ConversationSummary,
)
from backend.app.api.v1.schemas.conversations import (
    CreateConversationRequest as CreateConversationRequest,
)
from backend.app.api.v1.schemas.conversations import (
    MessageWire as MessageWire,
)
from backend.app.api.v1.schemas.conversations import (
    SendMessageRequest as SendMessageRequest,
)
from backend.app.api.v1.schemas.conversations import (
    SendMessageRequestContent as SendMessageRequestContent,
)
from backend.app.api.v1.schemas.judgments import (
    CalibrationResponse as CalibrationResponse,
)
from backend.app.api.v1.schemas.judgments import (
    CalibrationSample as CalibrationSample,
)
from backend.app.api.v1.schemas.judgments import (
    CalibrationSamplesRequest as CalibrationSamplesRequest,
)
from backend.app.api.v1.schemas.judgments import (
    CreateJudgmentListGenerateRequest as CreateJudgmentListGenerateRequest,
)
from backend.app.api.v1.schemas.judgments import (
    GenerateJudgmentsResponse as GenerateJudgmentsResponse,
)
from backend.app.api.v1.schemas.judgments import (
    ImportJudgmentItem as ImportJudgmentItem,
)
from backend.app.api.v1.schemas.judgments import (
    ImportJudgmentListRequest as ImportJudgmentListRequest,
)
from backend.app.api.v1.schemas.judgments import (
    JudgmentListDetail as JudgmentListDetail,
)
from backend.app.api.v1.schemas.judgments import (
    JudgmentListJudgmentsResponse as JudgmentListJudgmentsResponse,
)
from backend.app.api.v1.schemas.judgments import (
    JudgmentListListResponse as JudgmentListListResponse,
)
from backend.app.api.v1.schemas.judgments import (
    JudgmentListSummary as JudgmentListSummary,
)
from backend.app.api.v1.schemas.judgments import (
    JudgmentRow as JudgmentRow,
)
from backend.app.api.v1.schemas.judgments import (
    OverrideJudgmentRequest as OverrideJudgmentRequest,
)
from backend.app.api.v1.schemas.judgments import (
    _SourceBreakdown as _SourceBreakdown,
)
from backend.app.api.v1.schemas.proposals import (
    ConfigRepoDetail as ConfigRepoDetail,
)
from backend.app.api.v1.schemas.proposals import (
    ConfigReposListResponse as ConfigReposListResponse,
)
from backend.app.api.v1.schemas.proposals import (
    CreateConfigRepoRequest as CreateConfigRepoRequest,
)
from backend.app.api.v1.schemas.proposals import (
    CreateProposalRequest as CreateProposalRequest,
)
from backend.app.api.v1.schemas.proposals import (
    DigestResponse as DigestResponse,
)
from backend.app.api.v1.schemas.proposals import (
    OpenPrResponse as OpenPrResponse,
)
from backend.app.api.v1.schemas.proposals import (
    ProposalDetail as ProposalDetail,
)
from backend.app.api.v1.schemas.proposals import (
    ProposalsListResponse as ProposalsListResponse,
)
from backend.app.api.v1.schemas.proposals import (
    ProposalSummary as ProposalSummary,
)
from backend.app.api.v1.schemas.proposals import (
    RejectProposalRequest as RejectProposalRequest,
)
from backend.app.api.v1.schemas.proposals import (
    _ClusterEmbed as _ClusterEmbed,
)
from backend.app.api.v1.schemas.proposals import (
    _DigestEmbed as _DigestEmbed,
)
from backend.app.api.v1.schemas.proposals import (
    _StudySummary as _StudySummary,
)
from backend.app.api.v1.schemas.proposals import (
    _TemplateEmbed as _TemplateEmbed,
)
from backend.app.api.v1.schemas.studies import (
    AUTO_FOLLOWUP_STRATEGY_VALUES as AUTO_FOLLOWUP_STRATEGY_VALUES,
)
from backend.app.api.v1.schemas.studies import (
    BulkQueriesJsonRequest as BulkQueriesJsonRequest,
)
from backend.app.api.v1.schemas.studies import (
    BulkQueriesResponse as BulkQueriesResponse,
)
from backend.app.api.v1.schemas.studies import (
    BulkQueryItem as BulkQueryItem,
)
from backend.app.api.v1.schemas.studies import (
    CreateQuerySetRequest as CreateQuerySetRequest,
)
from backend.app.api.v1.schemas.studies import (
    CreateQueryTemplateRequest as CreateQueryTemplateRequest,
)
from backend.app.api.v1.schemas.studies import (
    CreateStudyRequest as CreateStudyRequest,
)
from backend.app.api.v1.schemas.studies import (
    JudgmentListRef as JudgmentListRef,
)
from backend.app.api.v1.schemas.studies import (
    ObjectiveSpec as ObjectiveSpec,
)
from backend.app.api.v1.schemas.studies import (
    ParentFollowupRef as ParentFollowupRef,
)
from backend.app.api.v1.schemas.studies import (
    QueryHasJudgmentsDetail as QueryHasJudgmentsDetail,
)
from backend.app.api.v1.schemas.studies import (
    QueryHasJudgmentsEnvelope as QueryHasJudgmentsEnvelope,
)
from backend.app.api.v1.schemas.studies import (
    QueryListResponse as QueryListResponse,
)
from backend.app.api.v1.schemas.studies import (
    QueryRow as QueryRow,
)
from backend.app.api.v1.schemas.studies import (
    QuerySetDetail as QuerySetDetail,
)
from backend.app.api.v1.schemas.studies import (
    QuerySetListResponse as QuerySetListResponse,
)
from backend.app.api.v1.schemas.studies import (
    QuerySetSummary as QuerySetSummary,
)
from backend.app.api.v1.schemas.studies import (
    QueryTemplateDetail as QueryTemplateDetail,
)
from backend.app.api.v1.schemas.studies import (
    QueryTemplateListResponse as QueryTemplateListResponse,
)
from backend.app.api.v1.schemas.studies import (
    QueryTemplateSummary as QueryTemplateSummary,
)
from backend.app.api.v1.schemas.studies import (
    RecentChainsResponse as RecentChainsResponse,
)
from backend.app.api.v1.schemas.studies import (
    RecentChainSummary as RecentChainSummary,
)
from backend.app.api.v1.schemas.studies import (
    StudyChainLink as StudyChainLink,
)
from backend.app.api.v1.schemas.studies import (
    StudyChainResponse as StudyChainResponse,
)
from backend.app.api.v1.schemas.studies import (
    StudyConfigSpec as StudyConfigSpec,
)
from backend.app.api.v1.schemas.studies import (
    StudyDetail as StudyDetail,
)
from backend.app.api.v1.schemas.studies import (
    StudyListResponse as StudyListResponse,
)
from backend.app.api.v1.schemas.studies import (
    StudySummary as StudySummary,
)
from backend.app.api.v1.schemas.studies import (
    TrialDetail as TrialDetail,
)
from backend.app.api.v1.schemas.studies import (
    TrialListResponse as TrialListResponse,
)
from backend.app.api.v1.schemas.studies import (
    TrialsSummaryShape as TrialsSummaryShape,
)
from backend.app.api.v1.schemas.studies import (
    UpdateQueryRequest as UpdateQueryRequest,
)
from backend.app.api.v1.schemas.ubi import (
    CreateJudgmentListFromUbiRequest as CreateJudgmentListFromUbiRequest,
)
from backend.app.api.v1.schemas.ubi import (
    UbiReadinessResponse as UbiReadinessResponse,
)
from backend.app.domain.study.chain_summary import ChainStopReason as ChainStopReason
from backend.app.domain.study.comparison import CompareKind as CompareKind
from backend.app.domain.study.comparison import CompareWarningCode as CompareWarningCode
from backend.app.domain.study.confidence import ConfidenceShape as ConfidenceShape
from backend.app.domain.study.convergence import ConvergenceVerdict as ConvergenceVerdict
from backend.app.domain.study.convergence import StudyConvergenceShape as StudyConvergenceShape
from backend.app.domain.study.followups import FollowupItem as FollowupItem
