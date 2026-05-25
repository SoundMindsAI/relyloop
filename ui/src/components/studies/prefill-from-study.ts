/**
 * feat_study_clone_from_previous Story 2.1 — pure helper that maps a
 * ``StudyDetail`` returned by ``GET /api/v1/studies/{id}`` into the
 * ``PrefillValues`` shape consumed by ``CreateStudyModal``.
 *
 * Called by:
 *   - ``ui/src/app/studies/page.tsx`` (Story 2.3) when the page renders
 *     with ``?clone_from=<source_id>`` and the source-study fetch resolves.
 *
 * Invariants (FR-5 + FR-12 + D-12 of the feature spec):
 *   - ``parent_study_id`` carries the source id straight through; the
 *     backend persists it on ``studies.parent_study_id`` and validates
 *     (existence + same-cluster) per FR-8.
 *   - ``cloneSource`` is the UI-only banner payload; the create-modal's
 *     submit serializer (Story 2.2) MUST exclude it from the wire body.
 *   - ``parent`` is intentionally omitted — the clone path does not carry
 *     proposal-followup lineage. The two lineage axes are independent
 *     per D-5 / FR-10; both may be set in the same request, but the
 *     clone entry point sets only ``parent_study_id``.
 *   - ``name`` = ``source.name.slice(0, 200) + ' (clone)'`` (NO ellipsis)
 *     so the final string stays under the backend's 256-char
 *     ``CreateStudyRequest.name`` bound with comfortable headroom.
 */

import type { StudyDetail } from '@/lib/api/studies';
import type {
  ObjectiveDirection,
  ObjectiveK,
  ObjectiveMetric,
  PrunerKind,
  SamplerKind,
} from '@/lib/enums';

import type { PrefillValues } from './create-study-modal';

const SOURCE_NAME_MAX = 200;

export function buildPrefillFromStudy(source: StudyDetail): PrefillValues {
  const truncatedSourceName = source.name.slice(0, SOURCE_NAME_MAX);
  const objective = source.objective as {
    metric: ObjectiveMetric;
    k?: ObjectiveK;
    direction: ObjectiveDirection;
  };
  const config = source.config as {
    max_trials?: number;
    time_budget_min?: number;
    parallelism?: number;
    trial_timeout_s?: number;
    sampler?: SamplerKind;
    pruner?: PrunerKind;
    seed?: number;
  };
  return {
    cluster_id: source.cluster_id,
    target: source.target,
    template_id: source.template_id,
    query_set_id: source.query_set_id,
    judgment_list_id: source.judgment_list_id,
    name: `${truncatedSourceName} (clone)`,
    search_space_text: JSON.stringify(source.search_space, null, 2),
    metric: objective.metric,
    k: objective.k,
    direction: objective.direction,
    max_trials: config.max_trials,
    time_budget_min: config.time_budget_min,
    parallelism: config.parallelism,
    trial_timeout_s: config.trial_timeout_s,
    sampler: config.sampler,
    pruner: config.pruner,
    seed: config.seed,
    parent_study_id: source.id,
    cloneSource: { id: source.id, name: source.name },
  };
}
