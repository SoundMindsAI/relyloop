'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useForm, type SubmitHandler } from 'react-hook-form';
import { toast } from 'sonner';

import { HelpPopover } from '@/components/common/help-popover';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { EntitySelect } from '@/components/common/entity-select';
import { isDemoClusterName } from '@/lib/demo-data';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import {
  useClusters,
  useClusterSchema,
  useClusterTargets,
  type TargetSummary,
} from '@/lib/api/clusters';
import { useStudyDigest } from '@/lib/api/digests';
import { useJudgmentLists } from '@/lib/api/judgments';
import { useTemplates, useTemplate } from '@/lib/api/query-templates';
import { useQuerySets } from '@/lib/api/query-sets';
import { useCreateStudy } from '@/lib/api/studies';
import { narrowBoundsAroundWinner } from '@/lib/narrow-bounds';
import {
  AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES,
  OBJECTIVE_DIRECTION_VALUES,
  OBJECTIVE_K_VALUES,
  OBJECTIVE_METRIC_VALUES,
  PRUNER_VALUES,
  SAMPLER_VALUES,
  type ObjectiveDirection,
  type ObjectiveK,
  type ObjectiveMetric,
  type PrunerKind,
  type SamplerKind,
} from '@/lib/enums';
import { buildStarterSearchSpace } from '@/lib/search-space-defaults';

import { SearchSpaceBuilder } from './search-space-builder';
import { ResponsiveLayout } from './search-space-builder/responsive-layout';

// Source-of-truth: backend/app/api/v1/schemas.py:474 _K_REQUIRED_METRICS frozenset.
// Asserted by ui/src/__tests__/components/studies/k-required.test.ts.
export const K_REQUIRED: ReadonlySet<ObjectiveMetric> = new Set(['ndcg', 'precision', 'recall']);

// Source-of-truth: backend/app/eval/scoring.py (metric → ir_measures metric-object mapper).
// Asserted by backend/tests/unit/eval/test_scoring_metric_tokens.py and the
// K_REQUIRED-membership contract test at
// backend/tests/contract/test_k_required_membership.py.
// Asserted on the frontend side by ui/src/__tests__/components/studies/k-ignored.test.ts.
// ERR@k is reserved for MVP2 (infra_optuna_eval §13); when it lands, add 'err' back here.
export const K_IGNORED: ReadonlySet<ObjectiveMetric> = new Set(['mrr']);

// Sentinel value used by the optional-k "—" SelectItem (Radix SelectItem
// rejects empty-string values).
const K_CLEAR_SENTINEL = '__clear__';

export type KTier = 'required' | 'optional' | 'ignored';

export function kTier(metric: ObjectiveMetric): KTier {
  if (K_REQUIRED.has(metric)) return 'required';
  if (K_IGNORED.has(metric)) return 'ignored';
  return 'optional';
}

const PLACEHOLDER_SENTINEL = '__placeholder__';
const UNDO_TIMEOUT_MS = 10_000;

// Stop-condition preset selector (chore_study_default_stop_conditions FR-2/FR-3).
// Frontend-only state — preset wire values are NOT sent to the backend; the
// numeric `max_trials` + `time_budget_min` fields written by the preset are
// the contract surface.
const PRESET_VALUES = ['focused', 'standard', 'deep', 'custom'] as const;
type PresetValue = (typeof PRESET_VALUES)[number];

function presetLabel(preset: PresetValue): string {
  switch (preset) {
    case 'focused':
      return 'Focused (50)';
    case 'standard':
      return 'Standard (200)';
    case 'deep':
      return 'Deep (1000)';
    case 'custom':
      return 'Custom';
  }
}

type PresetWrite = { max_trials: number | ''; time_budget_min: number | '' };
const FOCUSED_WRITE: PresetWrite = { max_trials: 50, time_budget_min: '' };
const STANDARD_WRITE: PresetWrite = { max_trials: 200, time_budget_min: '' };
const DEEP_WRITE: PresetWrite = { max_trials: 1000, time_budget_min: 480 };

// feat_study_sub_warmup_guard FR-5: Custom-mode sub-warmup warning threshold.
// chore_study_default_stop_conditions shipped 50 as the MedianPruner activation
// floor; this guard piggybacks on the same threshold so the wizard warning and
// the backend pruning floor stay in lockstep. See feature_spec.md FR-5.
// Values must match backend/app/eval/optuna_runtime.py STUDIES_TPE_WARMUP_FLOOR
const SUB_WARMUP_FLOOR: number = 50;

function presetWrite(preset: Exclude<PresetValue, 'custom'>): PresetWrite {
  switch (preset) {
    case 'focused':
      return FOCUSED_WRITE;
    case 'standard':
      return STANDARD_WRITE;
    case 'deep':
      return DEEP_WRITE;
  }
}

interface FormValues {
  // Step 1
  cluster_id: string;
  target: string;
  // Step 2
  query_set_id: string;
  judgment_list_id: string;
  // Step 3
  template_id: string;
  // Step 4
  name: string;
  search_space_text: string;
  // Step 5
  metric: ObjectiveMetric;
  k?: ObjectiveK;
  direction: ObjectiveDirection;
  max_trials?: number | '';
  time_budget_min?: number | '';
  parallelism?: number | '';
  trial_timeout_s?: number | '';
  sampler?: SamplerKind;
  pruner?: PrunerKind;
  seed?: number | '';
  // feat_auto_followup_studies Story 3.2 — wizard-side opt-in depth.
  // Wizard-`0` is the OFF sentinel: it maps to `undefined` at payload time
  // so `auto_followup_depth` is omitted from `config` (defaults to null on
  // the wire, which the backend treats as "off"). Wire-`0` is reserved for
  // the worker's decrement path per FR-1 + D-12 — the wizard never sends it.
  auto_followup_depth?: 0 | 1 | 2 | 3 | 4 | 5;
}

const STEP_TITLES = [
  'Cluster + target',
  'Query set + judgments',
  'Template',
  'Search space',
  'Objective + config',
] as const;

/**
 * feat_digest_executable_followups Story 5.2 — prefill payload for the
 * "Run this followup" flow. Carries the parent-study-derived form-field
 * values plus the lineage tuple that gets sent in the POST body's
 * ``parent`` field.
 *
 * feat_study_clone_from_previous Story 2.1 — widened with two clone-mode
 * fields. ``parent`` became optional so the clone path (which carries no
 * proposal-followup lineage) can omit it; ``parent_study_id`` carries the
 * source study's id into the POST body (FR-6 / FR-7); ``cloneSource`` is
 * UI-only metadata read by the cloned-from banner (FR-12 / D-12) — the
 * modal's submit serializer MUST exclude it from the wire payload.
 */
export interface PrefillValues {
  cluster_id: string;
  target: string;
  template_id: string;
  query_set_id: string;
  judgment_list_id: string;
  name: string;
  search_space_text: string;
  metric: ObjectiveMetric;
  k?: ObjectiveK;
  direction: ObjectiveDirection;
  max_trials?: number | '';
  time_budget_min?: number | '';
  parallelism?: number | '';
  trial_timeout_s?: number | '';
  sampler?: SamplerKind;
  pruner?: PrunerKind;
  seed?: number | '';
  parent?: {
    proposal_id: string;
    followup_index: number;
  };
  parent_study_id?: string;
  cloneSource?: {
    id: string;
    name: string;
  };
}

export interface CreateStudyModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * feat_digest_executable_followups Story 5.2 — when provided, the modal
   * opens with the form fields pre-populated from the parent study and the
   * POST body carries the ``parent`` lineage payload. Re-renders with a
   * different ``initialValues`` reset the form to the new values.
   */
  initialValues?: PrefillValues;
}

export function CreateStudyModal({ open, onOpenChange, initialValues }: CreateStudyModalProps) {
  const create = useCreateStudy();
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const form = useForm<FormValues>({
    defaultValues: {
      cluster_id: '',
      target: '',
      query_set_id: '',
      judgment_list_id: '',
      template_id: '',
      name: '',
      search_space_text: '{}',
      metric: 'ndcg',
      k: 10,
      direction: 'maximize',
      max_trials: 200,
      parallelism: 4,
      sampler: 'tpe',
      pruner: 'median',
    },
  });

  const clusterId = form.watch('cluster_id');
  const target = form.watch('target');
  const querySetId = form.watch('query_set_id');
  const templateId = form.watch('template_id');
  const metric = form.watch('metric');

  // feat_study_target_judgment_mismatch_guard FR-4: hoist the RHF
  // registration for `target` so the manual-mode <Input> can keep name/ref/
  // onBlur/validate wiring AND tack the judgment_list_id cascade reset onto
  // onChange without an IIFE in JSX. Used at the Step-1 manual-mode branch
  // below.
  const targetReg = form.register('target');

  const clusters = useClusters({ limit: 200 });
  const selectedCluster = clusters.data?.data.find((c) => c.id === clusterId);
  const schema = useClusterSchema(clusterId, target || undefined);
  const targets = useClusterTargets(clusterId);
  const [manualMode, setManualMode] = useState(false);

  // chore_study_default_stop_conditions FR-2/FR-4: stop-condition preset.
  // Derived purely from form values via useMemo — no useState, no watcher
  // useEffect. Manual edits to max_trials / time_budget_min automatically
  // re-derive the active preset on the next render. Chosen over the
  // useState + useEffect watcher pattern because it's simpler and has one
  // fewer render cycle. (Note: this is NOT the fix for the E2E regression
  // tracked in `bug_smoke_create_study_modal_e2e_max_trials_fill/idea.md` —
  // that regression reproduces with both patterns. See the bug file for
  // the seven ruled-out hypotheses.)
  const watchedMaxTrials = form.watch('max_trials');
  const watchedTimeBudget = form.watch('time_budget_min');
  const activePreset: PresetValue = useMemo(() => {
    const norm = (v: unknown): number | '' =>
      v === undefined || v === null || (typeof v === 'number' && Number.isNaN(v))
        ? ''
        : (v as number | '');
    const normMax = norm(watchedMaxTrials);
    const normTime = norm(watchedTimeBudget);
    if (normMax === FOCUSED_WRITE.max_trials && normTime === FOCUSED_WRITE.time_budget_min)
      return 'focused';
    if (normMax === STANDARD_WRITE.max_trials && normTime === STANDARD_WRITE.time_budget_min)
      return 'standard';
    if (normMax === DEEP_WRITE.max_trials && normTime === DEEP_WRITE.time_budget_min) return 'deep';
    return 'custom';
  }, [watchedMaxTrials, watchedTimeBudget]);

  const handlePresetClick = (preset: PresetValue) => {
    // Custom click is a no-op: activePreset is derived from values, and
    // Custom == "values don't match any preset". The user reaches Custom
    // either by clicking a non-Custom preset and then manually editing
    // (which moves values off the preset write) or by being in a
    // post-Deep-reopen state where prior values persist.
    if (preset === 'custom') return;
    const writes = presetWrite(preset);
    form.setValue('max_trials', writes.max_trials, { shouldDirty: true });
    form.setValue('time_budget_min', writes.time_budget_min, { shouldDirty: true });
  };

  // FR-5 modal-open reset: <Dialog> (Radix) keeps this component mounted
  // across open/close toggles, so useState alone does NOT reset on reopen.
  // This effect is the authoritative reset for AC-12.
  useEffect(() => {
    if (open) {
      setManualMode(false);
    }
  }, [open]);

  // feat_digest_executable_followups Story 5.2 — when ``initialValues`` is
  // provided AND the modal is open, reset the form with the prefill payload.
  // Runs AFTER the manualMode-reset effect above (React fires effects in
  // declaration order). Re-renders with a different ``initialValues``
  // reset the form to the new values per AC-2 / D-19.
  useEffect(() => {
    if (open && initialValues) {
      form.reset({
        cluster_id: initialValues.cluster_id,
        target: initialValues.target,
        template_id: initialValues.template_id,
        query_set_id: initialValues.query_set_id,
        judgment_list_id: initialValues.judgment_list_id,
        name: initialValues.name,
        search_space_text: initialValues.search_space_text,
        metric: initialValues.metric,
        k: initialValues.k,
        direction: initialValues.direction,
        max_trials: initialValues.max_trials,
        time_budget_min: initialValues.time_budget_min,
        parallelism: initialValues.parallelism,
        trial_timeout_s: initialValues.trial_timeout_s,
        sampler: initialValues.sampler,
        pruner: initialValues.pruner,
        seed: initialValues.seed,
      });
    }
  }, [open, initialValues, form]);

  // FR-5 auto-engage: when the targets query fails with TARGETS_FORBIDDEN,
  // silently flip into manual mode. `open` is in BOTH the guard AND the
  // dependency list (cycle-2 GPT-5.5 review #3) — without it, a cached
  // TARGETS_FORBIDDEN error from a prior modal session would not re-fire
  // the auto-engage on reopen because the [open] reset above would clobber
  // manualMode back to false and React would not re-run this effect.
  useEffect(() => {
    if (open && targets.isError && targets.error?.errorCode === 'TARGETS_FORBIDDEN') {
      setManualMode(true);
    }
  }, [open, targets.isError, targets.error?.errorCode]);

  // FR-7 alphabetical sort by name (case-insensitive). Done at render time
  // — the hook stays fetch-only. Wrap in a query-shaped object so
  // <EntitySelect query={...}> consumes it without translation.
  const sortedTargets = useMemo(() => {
    const list = targets.data?.data ?? [];
    return [...list].sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
    );
  }, [targets.data?.data]);
  const sortedTargetsQuery = {
    ...targets,
    data: targets.data ? { data: sortedTargets } : undefined,
  } as typeof targets;

  const querySets = useQuerySets({ cluster_id: clusterId || undefined, limit: 200 });
  // feat_study_target_judgment_mismatch_guard FR-4: filter judgment-lists by
  // both the chosen cluster AND the chosen target so the dropdown only shows
  // valid pairings. The backend's POST /studies validators (FR-1 + FR-1b) are
  // the contract; this client-side filter is the UX prefetch so the operator
  // can't even submit a mismatch.
  const judgmentLists = useJudgmentLists({
    query_set_id: querySetId || undefined,
    cluster_id: clusterId || undefined,
    target: target || undefined,
    limit: 200,
  });
  const templates = useTemplates({
    engine_type: selectedCluster?.engine_type,
    limit: 200,
  });
  // Fetch the full template body (with declared_params) as soon as the user
  // picks one in Step 3. Used by the Step-4 auto-fill effect and the
  // client-side validation mirror below.
  const templateQuery = useTemplate(templateId || null);
  const templateBody = templateQuery.data;
  const templateError = templateQuery.error;

  // Set of textarea contents previously emitted by buildStarterSearchSpace.
  // Used to decide whether an auto-fill replacement requires an Undo toast
  // (user-edited content) or can land silently (still matches an earlier
  // auto-fill). Per spec FR-1 / AC-2.
  const [autoFillSignatures, setAutoFillSignatures] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const autoFillTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [searchSpaceError, setSearchSpaceError] = useState<string | null>(null);
  const [placeholderWarning, setPlaceholderWarning] = useState(false);

  // feat_study_clone_narrow_bounds Story 1.3 — Step-4 opt-in checkbox state.
  // Called unconditionally per Rules of Hooks; the `enabled` gate suppresses
  // the network request when there's no clone source (FR-1, D-12).
  const cloneSourceId = initialValues?.cloneSource?.id;
  const sourceDigest = useStudyDigest(cloneSourceId, {
    enabled: Boolean(cloneSourceId),
  });
  const [narrowBoundsChecked, setNarrowBoundsChecked] = useState(false);
  const originalSpaceJsonRef = useRef<string | null>(null);

  // FR-1: checkbox + reference panel render iff both gates pass.
  // Optional chaining + nullish coalescing defends against an API shape
  // that drops ``recommended_config`` (the Pydantic model has it required +
  // non-null, but an evolving wire contract or test fixture could send a
  // partial response — better to fail closed).
  const narrowBoundsGateOpen =
    Boolean(initialValues?.cloneSource) &&
    sourceDigest.status === 'success' &&
    Object.keys(sourceDigest.data?.recommended_config ?? {}).length > 0;

  // FR-7: reset checkbox + ref on every modal close.
  useEffect(() => {
    if (!open) {
      setNarrowBoundsChecked(false);
      originalSpaceJsonRef.current = null;
    }
  }, [open]);

  // FR-4 + FR-5: check/uncheck handler.
  const handleNarrowBoundsToggle = (next: boolean) => {
    if (next) {
      // false → true.
      // §4 Anti-pattern precondition guard: do not invoke the rewrite when
      // the textarea is in a known-malformed state. Force the engineer to
      // resolve the JSON error first.
      if (searchSpaceError !== null) {
        toast.error('Resolve the search-space JSON error before narrowing bounds.');
        originalSpaceJsonRef.current = null;
        // Stay unchecked.
        return;
      }
      const currentText = form.getValues('search_space_text');
      originalSpaceJsonRef.current = currentText;
      try {
        const recommended = sourceDigest.data?.recommended_config ?? {};
        const result = narrowBoundsAroundWinner(currentText, recommended, 20);
        if (result.narrowed.length === 0) {
          // D-11: no-op leaves the textarea bytes exact. Toast explains why.
          toast(
            'No params narrowed — every param is categorical, missing from the winner, or its winner is outside the current bounds.',
          );
        } else {
          form.setValue('search_space_text', result.json);
        }
        setNarrowBoundsChecked(true);
      } catch (err) {
        const msg =
          err instanceof SyntaxError
            ? "Couldn't narrow bounds: search-space JSON is invalid — fix it and try again."
            : `Couldn't narrow bounds: ${err instanceof Error ? err.message : String(err)}`;
        toast.error(msg);
        originalSpaceJsonRef.current = null;
        // Stay unchecked.
      }
    } else {
      // true → false. Restore the captured baseline; clear ref.
      if (originalSpaceJsonRef.current !== null) {
        form.setValue('search_space_text', originalSpaceJsonRef.current);
        originalSpaceJsonRef.current = null;
      }
      setNarrowBoundsChecked(false);
    }
  };

  useEffect(() => {
    return () => {
      if (autoFillTimeoutRef.current) clearTimeout(autoFillTimeoutRef.current);
    };
  }, []);

  // Whether the picked template has zero declared params — Step-3 Next is
  // blocked in that case (spec §11 edge).
  const templateHasNoDeclaredParams =
    Boolean(templateBody) && Object.keys(templateBody?.declared_params ?? {}).length === 0;

  // Surface for the template-detail GET error states. 404 bumps back to
  // Step 3; transient (5xx / network) keeps Step 4 open with a Retry button.
  // ApiError.status is 0 when the fetch never returned an HTTP envelope.
  const templateFetchStatus: 'ok' | '404' | 'transient' | 'idle' = (() => {
    if (!templateId) return 'idle';
    if (!templateError) return templateQuery.isFetching || templateBody ? 'ok' : 'idle';
    return templateError.status === 404 ? '404' : 'transient';
  })();

  // 404 recovery: bump the user back to Step 3 once and surface a toast.
  // Keyed on (templateId, status) so the effect doesn't re-fire on every
  // render while the user sits on Step 3 picking another template.
  useEffect(() => {
    if (templateFetchStatus === '404' && step >= 2) {
      toast.error('The selected template is no longer available. Pick another.');
      form.setValue('template_id', '');
      if (step > 2) setStep(2);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateFetchStatus, templateId]);

  // Step-3 → Step-4 auto-fill effect. Keyed on the fetched template body so
  // template-change replacements re-fire even if the user came back to
  // Step 3 and re-picked.
  useEffect(() => {
    if (!templateBody) return;
    const declared = templateBody.declared_params ?? {};
    const declaredKeys = Object.keys(declared);
    if (declaredKeys.length === 0) return;

    // feat_digest_executable_followups_swap_template Story 3.5 (FR-14 +
    // AC-16): when a followup prefill is active AND it carries a
    // non-empty search_space_text, suppress the autofill entirely so the
    // operator-visible textarea preserves the LLM-proposed bounds. The
    // existing implicit "empty or matches prior signature" guard below
    // already catches most cases; this explicit early return ensures a
    // future autofill rewrite can't regress AC-16. Reads from the prop,
    // not the form state, so it stays valid across re-renders within the
    // same modal-open lifetime.
    const prefillSearchSpace = initialValues?.search_space_text?.trim() ?? '';
    if (initialValues && prefillSearchSpace !== '' && prefillSearchSpace !== '{}') {
      return;
    }

    // feat_agent_propose_search_space Story 1.2 — buildStarterSearchSpace now
    // returns { space, capAwareFallbackParamNames } and may throw on empty
    // input or cap-aware overflow. Surface throws via the existing modal
    // error-toast path; capAwareFallbackParamNames is intentionally ignored
    // here (no new wizard UI — spec keeps v1 backend-only). The wrapper's
    // own `console.warn` still fires when the safe fallback path runs.
    let space;
    try {
      ({ space } = buildStarterSearchSpace(declared));
    } catch (err) {
      toast.error(
        err instanceof Error
          ? `Could not auto-fill search space: ${err.message}`
          : 'Could not auto-fill search space.',
      );
      return;
    }
    const autoJson = JSON.stringify(space, null, 2);
    const current = form.getValues('search_space_text');
    const trimmed = (current ?? '').trim();
    const isEmpty = trimmed === '' || trimmed === '{}';
    const matchesPriorSignature = autoFillSignatures.has(current);

    if (isEmpty || matchesPriorSignature) {
      form.setValue('search_space_text', autoJson);
      setAutoFillSignatures((prev) => {
        const next = new Set(prev);
        next.add(autoJson);
        return next;
      });
      setSearchSpaceError(null);
      setPlaceholderWarning(autoJson.includes(PLACEHOLDER_SENTINEL));
      return;
    }

    // User edits exist — replace immediately, then show an Undo toast.
    const priorText = current;
    form.setValue('search_space_text', autoJson);
    setAutoFillSignatures((prev) => {
      const next = new Set(prev);
      next.add(autoJson);
      return next;
    });
    setSearchSpaceError(null);
    setPlaceholderWarning(autoJson.includes(PLACEHOLDER_SENTINEL));
    if (autoFillTimeoutRef.current) clearTimeout(autoFillTimeoutRef.current);
    autoFillTimeoutRef.current = setTimeout(() => {
      autoFillTimeoutRef.current = null;
    }, UNDO_TIMEOUT_MS);
    toast('Replaced your Step-4 content with defaults for the new template.', {
      duration: UNDO_TIMEOUT_MS,
      action: {
        label: 'Undo',
        onClick: () => {
          form.setValue('search_space_text', priorText);
          if (autoFillTimeoutRef.current) {
            clearTimeout(autoFillTimeoutRef.current);
            autoFillTimeoutRef.current = null;
          }
          setPlaceholderWarning(priorText.includes(PLACEHOLDER_SENTINEL));
        },
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateBody]);

  // Child-select resets are handled inline in onValueChange below — no
  // useEffect needed (and an effect here would create a state-thrash loop
  // under React 19 + jsdom strict-mode rendering).

  function validateSearchSpaceAgainstTemplate(): string | null {
    if (!templateBody) return null;
    const raw = form.getValues('search_space_text') ?? '';
    let parsed: { params?: Record<string, unknown> };
    try {
      parsed = JSON.parse(raw || '{}');
    } catch {
      return 'Search space must be valid JSON.';
    }
    if (!parsed || typeof parsed !== 'object' || !parsed.params) {
      return null;
    }
    const submittedKeys = Object.keys(parsed.params);
    const declared = templateBody.declared_params ?? {};
    const declaredKeys = Object.keys(declared);
    const declaredSet = new Set(declaredKeys);
    const unknown = submittedKeys.filter((k) => !declaredSet.has(k)).sort();
    if (unknown[0] !== undefined) {
      const firstUnknown = unknown[0];
      const sortedDeclared = [...declaredKeys].sort();
      return (
        `Param '${firstUnknown}' is not declared by template '${templateBody.name}'. ` +
        `Declared params: [${sortedDeclared.map((d) => `'${d}'`).join(', ')}].`
      );
    }
    const submittedSet = new Set(submittedKeys);
    const missing = declaredKeys.filter((k) => !submittedSet.has(k)).sort();
    if (missing[0] !== undefined) {
      return (
        `Template '${templateBody.name}' declares param '${missing[0]}' but it is ` +
        `missing from the search space. Add it or remove from the template.`
      );
    }
    return null;
  }

  function refreshPlaceholderWarning(): void {
    const raw = form.getValues('search_space_text') ?? '';
    setPlaceholderWarning(raw.includes(PLACEHOLDER_SENTINEL));
  }

  function handleSearchSpaceBlur(): void {
    setSearchSpaceError(validateSearchSpaceAgainstTemplate());
    refreshPlaceholderWarning();
  }

  function handleStep4Next(): void {
    const error = validateSearchSpaceAgainstTemplate();
    setSearchSpaceError(error);
    refreshPlaceholderWarning();
    if (error) return;
    setStep((s) => s + 1);
  }

  function stepValid(s: number, values: FormValues): boolean {
    switch (s) {
      case 0:
        return Boolean(values.cluster_id && values.target);
      case 1:
        return Boolean(values.query_set_id && values.judgment_list_id);
      case 2:
        // Block transition when the picked template has no tunable params;
        // auto-fill cannot produce a valid SearchSpace from an empty
        // declared_params dict (Pydantic min_length=1 on params).
        return Boolean(values.template_id) && !templateHasNoDeclaredParams;
      case 3:
        if (!values.name) return false;
        try {
          const v = JSON.parse(values.search_space_text || '{}');
          return v && typeof v === 'object';
        } catch {
          return false;
        }
      case 4: {
        const kOk = !K_REQUIRED.has(values.metric) || values.k != null;
        const stopOk =
          (typeof values.max_trials === 'number' && values.max_trials > 0) ||
          (typeof values.time_budget_min === 'number' && values.time_budget_min > 0);
        return kOk && stopOk;
      }
      default:
        return false;
    }
  }

  const onSubmit: SubmitHandler<FormValues> = (values) => {
    let search_space: Record<string, unknown> = {};
    try {
      search_space = JSON.parse(values.search_space_text || '{}');
    } catch {
      toast.error('Search space must be valid JSON');
      return;
    }
    const objective: { metric: ObjectiveMetric; k?: ObjectiveK; direction: ObjectiveDirection } = {
      metric: values.metric,
      direction: values.direction,
    };
    // Include k for required + optional tiers when the user set one.
    // K_IGNORED metrics (mrr / err) never carry k into the POST body.
    if (!K_IGNORED.has(values.metric) && values.k != null) {
      objective.k = values.k;
    }
    type ConfigSpec = {
      max_trials?: number;
      time_budget_min?: number;
      parallelism?: number;
      trial_timeout_s?: number;
      sampler?: SamplerKind;
      pruner?: PrunerKind;
      seed?: number;
      auto_followup_depth?: number;
    };
    const config: ConfigSpec = {};
    if (typeof values.max_trials === 'number') config.max_trials = values.max_trials;
    if (typeof values.time_budget_min === 'number') config.time_budget_min = values.time_budget_min;
    if (typeof values.parallelism === 'number') config.parallelism = values.parallelism;
    if (typeof values.trial_timeout_s === 'number') config.trial_timeout_s = values.trial_timeout_s;
    if (values.sampler) config.sampler = values.sampler;
    if (values.pruner) config.pruner = values.pruner;
    if (typeof values.seed === 'number') config.seed = values.seed;
    // feat_auto_followup_studies Story 3.2 — wizard-`0` = "Off" sentinel
    // maps to omit-from-config (NOT to wire-`0`). Wire-`0` is reserved for
    // the worker's decrement-to-terminal path per FR-1 + D-12.
    if (typeof values.auto_followup_depth === 'number' && values.auto_followup_depth > 0) {
      config.auto_followup_depth = values.auto_followup_depth;
    }

    setSubmitting(true);
    // Lineage attachment — the two axes are independent per D-5 / FR-10 of
    // feat_study_clone_from_previous; both may travel on the same request:
    //   * `parent` — proposal-followup lineage (feat_digest_executable_followups
    //     Story 5.2). Set by the proposals/[id] "Run this followup" flow.
    //   * `parent_study_id` — clone lineage (feat_study_clone_from_previous
    //     FR-6 / FR-7). Set by the /studies?clone_from=… deep-link flow.
    // `initialValues.cloneSource` is UI-only per D-12 (read by the
    // cloned-from banner above) and MUST NOT be serialized — the payload
    // below is field-by-field on purpose; no `...initialValues` spread.
    create.mutate(
      {
        name: values.name,
        cluster_id: values.cluster_id,
        target: values.target,
        template_id: values.template_id,
        query_set_id: values.query_set_id,
        judgment_list_id: values.judgment_list_id,
        search_space,
        objective,
        config,
        ...(initialValues?.parent
          ? {
              parent: {
                proposal_id: initialValues.parent.proposal_id,
                followup_index: initialValues.parent.followup_index,
              },
            }
          : {}),
        ...(initialValues?.parent_study_id
          ? { parent_study_id: initialValues.parent_study_id }
          : {}),
      },
      {
        onSuccess: () => {
          toast.success('Study queued');
          form.reset();
          setStep(0);
          onOpenChange(false);
        },
        onSettled: () => setSubmitting(false),
      },
    );
  };

  const values = form.watch();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create study</DialogTitle>
          <DialogDescription>
            Step {step + 1} of {STEP_TITLES.length} — {STEP_TITLES[step]}
          </DialogDescription>
        </DialogHeader>
        {initialValues?.cloneSource && (
          <div
            className="mb-4 rounded-md border bg-muted/40 px-4 py-2 text-sm"
            data-testid="cloned-from-banner"
          >
            Cloned from study <strong>{initialValues.cloneSource.name}</strong>
            {' · '}
            <Link
              href={`/studies/${initialValues.cloneSource.id}`}
              className="underline hover:text-foreground/80"
            >
              view source
            </Link>
            <span className="ml-1">
              <InfoTooltip glossaryKey="study.cloned_from_banner" />
            </span>
          </div>
        )}
        <form
          // Submission goes exclusively through the explicit submit-button
          // onClick below — the form's submit event is swallowed so that any
          // implicit submit (Enter on an input, Playwright `.fill()`-driven
          // stray submit events in production-build Chromium, etc.) cannot
          // race the user's explicit click. See bug_fix.md alongside
          // bug_smoke_create_study_modal_e2e_max_trials_fill/idea.md.
          onSubmit={(e) => e.preventDefault()}
          className="space-y-4"
          data-testid="create-study-form"
        >
          {step === 0 && (
            <div className="space-y-4" data-testid="step-1">
              <div className="space-y-1.5">
                <Label htmlFor="cs-cluster">Cluster</Label>
                <EntitySelect
                  id="cs-cluster"
                  data-testid="cs-cluster"
                  query={clusters}
                  getId={(c) => c.id}
                  getLabel={(c) =>
                    `${c.name} (${c.engine_type})${isDemoClusterName(c.name) ? ' (Demo)' : ''}`
                  }
                  getStatus={(c) =>
                    c.health_check.status === 'unreachable' ? 'unknown' : c.health_check.status
                  }
                  value={values.cluster_id || undefined}
                  onChange={(v) => {
                    form.setValue('cluster_id', v ?? '');
                    // FR-4: target also resets on cluster change (was missing
                    // from the prior cascade — stale target text would 404
                    // immediately on the new cluster).
                    form.setValue('target', '');
                    form.setValue('query_set_id', '');
                    form.setValue('judgment_list_id', '');
                    form.setValue('template_id', '');
                    // FR-5 cluster-change reset: drop manual mode so the
                    // new cluster's dropdown gets a chance to load.
                    setManualMode(false);
                  }}
                  placeholder="Choose a cluster"
                />
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center gap-1">
                  <Label htmlFor="cs-target">Target index / collection</Label>
                  <InfoTooltip glossaryKey="study.target" />
                </div>

                {manualMode ? (
                  // Manual-mode fallback (preserves the original Input behavior).
                  // feat_study_target_judgment_mismatch_guard FR-4: uses the
                  // hoisted `targetReg` so RHF's name/ref/onBlur/validate
                  // wiring stays intact while onChange ALSO cascade-resets
                  // judgment_list_id (mirror of line ~596 query-set pattern).
                  // Do NOT replace with bare value/onChange — that breaks
                  // RHF dirty/touched/validation state.
                  <>
                    <Input
                      id="cs-target"
                      {...targetReg}
                      onChange={(e) => {
                        targetReg.onChange(e);
                        form.setValue('judgment_list_id', '');
                      }}
                      placeholder="products"
                    />
                    {targets.isError && targets.error?.errorCode === 'TARGETS_FORBIDDEN' && (
                      <p className="text-xs text-amber-600">
                        Cluster restricts index listing — enter the target name manually.
                      </p>
                    )}
                  </>
                ) : !clusterId ? (
                  // FR-4: no cluster picked yet → disabled placeholder Select
                  // matching the EntitySelect visual idiom. The targets query
                  // is also enabled: false in this state (no GET fires).
                  <Select value="" onValueChange={() => {}} disabled>
                    <SelectTrigger id="cs-target" data-testid="cs-target" disabled>
                      <SelectValue placeholder="Pick a cluster first" />
                    </SelectTrigger>
                  </Select>
                ) : (
                  // Dropdown mode (default, with a cluster picked).
                  // feat_study_target_judgment_mismatch_guard FR-4: cascade
                  // reset judgment_list_id on target change so the Step-2
                  // dropdown re-fetches under the new filter.
                  <EntitySelect
                    id="cs-target"
                    data-testid="cs-target"
                    query={sortedTargetsQuery}
                    getId={(t: TargetSummary) => t.name}
                    getLabel={(t: TargetSummary) =>
                      `${t.name} (${t.doc_count != null ? t.doc_count.toLocaleString() : '?'} docs)`
                    }
                    value={values.target || undefined}
                    onChange={(v) => {
                      form.setValue('target', v ?? '');
                      form.setValue('judgment_list_id', '');
                    }}
                    placeholder="Choose a target"
                    emptyState={{
                      message: selectedCluster?.target_filter
                        ? `No targets match filter "${selectedCluster.target_filter}" on this cluster. To change the filter, delete and re-register the cluster — MVP1 has no in-place edit for cluster registrations.`
                        : 'No targets found on this cluster.',
                    }}
                  />
                )}

                {/* "Enter manually" / "Use dropdown" toggle — always visible at Step 1. */}
                <button
                  type="button"
                  onClick={() => setManualMode((prev) => !prev)}
                  className="text-xs text-muted-foreground underline"
                  aria-pressed={manualMode}
                  title="Type the target name instead of picking from the cluster's index list."
                >
                  {manualMode ? 'Use dropdown' : 'Enter manually'}
                </button>

                {schema.data && (
                  <p className="text-xs text-muted-foreground">
                    {schema.data.fields.length} fields discovered
                  </p>
                )}
              </div>
            </div>
          )}
          {step === 1 && (
            <div className="space-y-4" data-testid="step-2">
              <div className="space-y-1.5">
                <Label htmlFor="cs-qs">Query set</Label>
                <EntitySelect
                  id="cs-qs"
                  data-testid="cs-qs"
                  query={querySets}
                  getId={(q) => q.id}
                  getLabel={(q) => q.name}
                  value={values.query_set_id || undefined}
                  onChange={(v) => {
                    form.setValue('query_set_id', v ?? '');
                    form.setValue('judgment_list_id', '');
                  }}
                  placeholder="Choose a query set"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cs-jl">Judgment list</Label>
                <EntitySelect
                  id="cs-jl"
                  data-testid="cs-jl"
                  query={judgmentLists}
                  getId={(j) => j.id}
                  getLabel={(j) => j.name}
                  value={values.judgment_list_id || undefined}
                  onChange={(v) => form.setValue('judgment_list_id', v ?? '')}
                  placeholder="Choose a judgment list"
                  // feat_study_target_judgment_mismatch_guard FR-4: Step-2 is
                  // target-gated (line 384 advance gate requires target set
                  // before this dropdown renders), so the empty-state copy
                  // is unconditional — no "no target yet" fallback branch.
                  emptyState={{
                    message: `No judgment lists for target "${target}" on this cluster + query set. Generate a new one from /judgments.`,
                    cta: { label: 'Generate judgments', href: '/judgments' },
                  }}
                />
              </div>
            </div>
          )}
          {step === 2 && (
            <div className="space-y-4" data-testid="step-3">
              <div className="space-y-1.5">
                <div className="flex items-center gap-1">
                  <Label htmlFor="cs-tpl">Query template (filtered by engine)</Label>
                  <InfoTooltip glossaryKey="study.template" />
                </div>
                <EntitySelect
                  id="cs-tpl"
                  data-testid="cs-tpl"
                  query={templates}
                  getId={(t) => t.id}
                  getLabel={(t) => `${t.name} (v${t.version})`}
                  value={values.template_id || undefined}
                  onChange={(v) => {
                    form.setValue('template_id', v ?? '');
                    setSearchSpaceError(null);
                  }}
                  placeholder="Choose a template"
                />
                {templateHasNoDeclaredParams && (
                  <p
                    role="alert"
                    aria-live="polite"
                    className="text-sm text-destructive"
                    data-testid="cs-zero-declared-error"
                  >
                    This template has no tunable parameters. Pick a different template, or add
                    params to this one before running a study.
                  </p>
                )}
              </div>
            </div>
          )}
          {step === 3 && (
            <div className="space-y-4" data-testid="step-4">
              <div className="space-y-1.5">
                <Label htmlFor="cs-name">Study name</Label>
                <Input id="cs-name" {...form.register('name')} />
              </div>
              {/* feat_study_clone_narrow_bounds Story 1.3 — opt-in smart-rewrite
                  of the cloned search_space. Hidden entirely when not cloning
                  or when the source has no digest (FR-1, D-1: hide-vs-disable). */}
              {narrowBoundsGateOpen && (
                <div
                  className="rounded-md border border-border bg-muted/40 p-3 space-y-2"
                  data-testid="narrow-bounds-section"
                >
                  <div className="flex items-start gap-2">
                    <input
                      id="cs-narrow-bounds"
                      type="checkbox"
                      checked={narrowBoundsChecked}
                      onChange={(ev) => handleNarrowBoundsToggle(ev.target.checked)}
                      data-testid="narrow-bounds-checkbox"
                      className="mt-0.5 h-4 w-4 rounded border-border"
                    />
                    <div className="flex-1">
                      <Label
                        htmlFor="cs-narrow-bounds"
                        className="text-sm font-medium leading-snug flex items-center gap-1"
                      >
                        {"Narrow bounds around the source study's winning params (±20%)"}
                        <InfoTooltip glossaryKey="study.narrow_bounds_checkbox" />
                      </Label>
                    </div>
                  </div>
                  {/* FR-8: collapsible reference panel — native <details>.
                      Reads from cloneSource.name (UI-only metadata) so user
                      edits to the form's `name` field don't corrupt the
                      panel header (banner-style stability per v1 spec D-12). */}
                  <details
                    className="text-xs text-muted-foreground"
                    data-testid="narrow-bounds-reference-panel"
                  >
                    <summary className="cursor-pointer select-none hover:text-foreground">
                      Best-trial values from <strong>{initialValues?.cloneSource?.name}</strong>
                    </summary>
                    <table className="mt-2 w-full text-left">
                      <thead>
                        <tr>
                          <th className="font-medium pr-4">Param</th>
                          <th className="font-medium">Winning value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(sourceDigest.data?.recommended_config ?? {})
                          .sort(([a], [b]) => a.localeCompare(b))
                          .map(([name, value]) => (
                            <tr key={name} data-testid="narrow-bounds-reference-row">
                              <td className="pr-4 font-mono">{name}</td>
                              <td className="font-mono">{JSON.stringify(value)}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </details>
                </div>
              )}
              <ResponsiveLayout
                builder={
                  <SearchSpaceBuilder
                    value={values.search_space_text}
                    onChange={(next) => form.setValue('search_space_text', next)}
                    templateBody={templateBody ?? null}
                    templateId={values.template_id || undefined}
                    templateFetchStatus={templateFetchStatus}
                  />
                }
                textarea={
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1">
                      <Label htmlFor="cs-space">Search space (JSON)</Label>
                      <InfoTooltip glossaryKey="study.search_space" />
                    </div>
                    {templateQuery.isFetching && (
                      <p
                        className="text-xs text-muted-foreground"
                        data-testid="cs-template-loading"
                      >
                        Loading template…
                      </p>
                    )}
                    <Textarea
                      id="cs-space"
                      rows={10}
                      {...form.register('search_space_text', {
                        onBlur: handleSearchSpaceBlur,
                      })}
                      data-testid="cs-search-space"
                    />
                    <div className="mt-1.5">
                      <HelpPopover glossaryKey="study.search_space" />
                    </div>
                    {searchSpaceError && (
                      <p
                        role="alert"
                        aria-live="polite"
                        className="text-sm text-destructive"
                        data-testid="cs-search-space-error"
                      >
                        {searchSpaceError}
                      </p>
                    )}
                    {placeholderWarning && (
                      <p
                        className="text-sm text-amber-700 dark:text-amber-400"
                        data-testid="cs-placeholder-warning"
                      >
                        Replace the &lsquo;__placeholder__&rsquo; value(s) before submitting — they
                        are starter defaults for params with no inferable type.
                      </p>
                    )}
                    {templateFetchStatus === 'transient' && (
                      <div className="flex items-center gap-2" data-testid="cs-template-retry">
                        <p className="text-sm text-muted-foreground">
                          Couldn&rsquo;t load the template. Server-side validation will still catch
                          typos on submit.
                        </p>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => void templateQuery.refetch()}
                        >
                          Retry
                        </Button>
                      </div>
                    )}
                  </div>
                }
              />
            </div>
          )}
          {step === 4 && (
            <div className="space-y-4" data-testid="step-5">
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1">
                    <Label htmlFor="cs-metric">Metric</Label>
                    <HelpPopover glossaryKey="study.metric" />
                  </div>
                  <Select
                    value={values.metric}
                    onValueChange={(v) => {
                      const newMetric = v as ObjectiveMetric;
                      form.setValue('metric', newMetric);
                      // Per spec FR-4 / AC-10a: clear k when the new metric is
                      // in K_IGNORED so a stale k value doesn't leak into the
                      // POST body. Preserved otherwise (AC-10b — map@10 is
                      // meaningful when switching from ndcg@10).
                      if (K_IGNORED.has(newMetric)) {
                        form.setValue('k', undefined);
                      }
                    }}
                  >
                    <SelectTrigger id="cs-metric">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {OBJECTIVE_METRIC_VALUES.map((m) => (
                        <SelectItem key={m} value={m}>
                          {m}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  {(() => {
                    const tier = kTier(metric);
                    if (tier === 'ignored') {
                      return (
                        <p
                          className="text-sm text-muted-foreground"
                          data-testid="cs-k-ignored-caption"
                        >
                          {metric.toUpperCase()} evaluates the full ranked list — no cutoff used.
                        </p>
                      );
                    }
                    return (
                      <>
                        <div className="flex items-center gap-1">
                          <Label htmlFor="cs-k">k</Label>
                          <InfoTooltip glossaryKey="study.k" />
                        </div>
                        <Select
                          value={values.k != null ? String(values.k) : undefined}
                          onValueChange={(v) => {
                            if (v === K_CLEAR_SENTINEL) {
                              form.setValue('k', undefined);
                            } else {
                              form.setValue('k', Number(v) as ObjectiveK);
                            }
                          }}
                        >
                          <SelectTrigger id="cs-k">
                            <SelectValue
                              placeholder={tier === 'required' ? 'required' : 'select (optional)…'}
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {tier === 'optional' && (
                              <SelectItem
                                key="clear"
                                value={K_CLEAR_SENTINEL}
                                data-testid="cs-k-clear"
                              >
                                — (full recall)
                              </SelectItem>
                            )}
                            {OBJECTIVE_K_VALUES.map((k) => (
                              <SelectItem key={k} value={String(k)}>
                                {k}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground" data-testid="cs-k-sublabel">
                          {tier === 'required'
                            ? `Top-k cutoff (required for ${metric.toUpperCase()})`
                            : `Top-k cutoff (optional — leave empty for full-recall ${metric.toUpperCase()})`}
                        </p>
                      </>
                    );
                  })()}
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1">
                    <Label htmlFor="cs-dir">Direction</Label>
                    <InfoTooltip glossaryKey="study.direction" />
                  </div>
                  <Select
                    value={values.direction}
                    onValueChange={(v) => form.setValue('direction', v as ObjectiveDirection)}
                  >
                    <SelectTrigger id="cs-dir">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {OBJECTIVE_DIRECTION_VALUES.map((d) => (
                        <SelectItem key={d} value={d}>
                          {d}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              {/* chore_study_default_stop_conditions FR-2: stop-condition
                  preset button group. Sits above the numeric-inputs grid;
                  selecting a preset writes max_trials + time_budget_min
                  per PRESET_WRITES. */}
              <div className="space-y-2">
                <div className="flex items-center gap-1">
                  <span id="stop-condition-group-label" className="text-sm font-medium">
                    Stop condition
                  </span>
                  <InfoTooltip glossaryKey="study.preset" />
                </div>
                <div
                  role="group"
                  aria-labelledby="stop-condition-group-label"
                  className="flex flex-wrap gap-2"
                >
                  {PRESET_VALUES.map((p) => (
                    <Button
                      key={p}
                      type="button"
                      variant={activePreset === p ? 'default' : 'outline'}
                      aria-pressed={activePreset === p}
                      aria-label={presetLabel(p)}
                      onClick={() => handlePresetClick(p)}
                    >
                      {presetLabel(p)}
                    </Button>
                  ))}
                </div>
              </div>
              {/* feat_study_sub_warmup_guard FR-2/FR-3: non-blocking inline
                  warning when the operator's Custom-mode max_trials falls
                  below the SUB_WARMUP_FLOOR. Mount guard suppresses transient
                  empty / NaN / non-integer typing states; the warning is
                  display-only and does not change the submit path.
                  Visual pattern mirrors cs-placeholder-warning above
                  (text-amber-700 dark:text-amber-400). */}
              {activePreset === 'custom' &&
                typeof watchedMaxTrials === 'number' &&
                !Number.isNaN(watchedMaxTrials) &&
                Number.isInteger(watchedMaxTrials) &&
                watchedMaxTrials < SUB_WARMUP_FLOOR && (
                  <p
                    role="status"
                    className="text-sm text-amber-700 dark:text-amber-400"
                    data-testid="cs-sub-warmup-warning"
                  >
                    <strong>
                      The optimizer spends its first ~10 trials exploring randomly, and studies
                      below 50 trials skip RelyLoop&rsquo;s pruning floor.
                    </strong>{' '}
                    With {watchedMaxTrials} trials this study is unlikely to converge — switch to{' '}
                    <strong>Focused (50)</strong> for a quick run or <strong>Standard (200)</strong>{' '}
                    for a result worth turning into a PR.
                  </p>
                )}
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1">
                    <Label htmlFor="cs-max">Max trials</Label>
                    <InfoTooltip glossaryKey="study.max_trials" />
                  </div>
                  <Input
                    id="cs-max"
                    type="number"
                    {...form.register('max_trials', { valueAsNumber: true })}
                  />
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1">
                    <Label htmlFor="cs-budget">Time budget (min)</Label>
                    <InfoTooltip glossaryKey="study.time_budget_min" />
                  </div>
                  <Input
                    id="cs-budget"
                    type="number"
                    step="0.1"
                    {...form.register('time_budget_min', { valueAsNumber: true })}
                  />
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1">
                    <Label htmlFor="cs-par">Parallelism</Label>
                    <InfoTooltip glossaryKey="study.parallelism" />
                  </div>
                  <Input
                    id="cs-par"
                    type="number"
                    {...form.register('parallelism', { valueAsNumber: true })}
                  />
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1">
                    <Label htmlFor="cs-sampler">Sampler</Label>
                    <HelpPopover glossaryKey="study.sampler" />
                  </div>
                  <Select
                    value={values.sampler ?? ''}
                    onValueChange={(v) => form.setValue('sampler', v as SamplerKind)}
                  >
                    <SelectTrigger id="cs-sampler">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SAMPLER_VALUES.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1">
                    <Label htmlFor="cs-pruner">Pruner</Label>
                    <HelpPopover glossaryKey="study.pruner" />
                  </div>
                  <Select
                    value={values.pruner ?? ''}
                    onValueChange={(v) => form.setValue('pruner', v as PrunerKind)}
                  >
                    <SelectTrigger id="cs-pruner">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PRUNER_VALUES.map((p) => (
                        <SelectItem key={p} value={p}>
                          {p}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1">
                    <Label htmlFor="cs-seed">Seed</Label>
                    <InfoTooltip glossaryKey="study.seed" />
                  </div>
                  <Input
                    id="cs-seed"
                    type="number"
                    {...form.register('seed', { valueAsNumber: true })}
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                Provide either max trials or a time budget — both gates apply when both are set.
              </p>
              {/*
                feat_auto_followup_studies Story 3.2 — wizard depth selector (FR-11).
                Source-of-truth: backend/app/api/v1/schemas.py StudyConfigSpec.auto_followup_depth
                (validator enforces 0..5; wizard sends undefined for "Off" — wire-0 is
                worker-internal terminal-state and the wizard never sends it per D-12).
              */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-1">
                  <Label htmlFor="cs-auto-followup">Auto-followup chain</Label>
                  <InfoTooltip glossaryKey="auto_followup_depth" />
                </div>
                <Select
                  value={String(values.auto_followup_depth ?? 0)}
                  onValueChange={(v: string) => {
                    const n = Number.parseInt(v, 10);
                    if (n === 0) {
                      form.setValue('auto_followup_depth', undefined);
                    } else {
                      form.setValue('auto_followup_depth', n as 1 | 2 | 3 | 4 | 5);
                    }
                  }}
                >
                  <SelectTrigger id="cs-auto-followup" data-testid="cs-auto-followup">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES.map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n === 0 ? 'Off' : n === 1 ? '1 follow-up' : `${n} follow-ups`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Run additional studies overnight, each narrowing around the previous winner. Halts
                  on no lift, exhausted budget, or failed parent.
                </p>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                if (step === 0) onOpenChange(false);
                else setStep((s) => s - 1);
              }}
            >
              {step === 0 ? 'Cancel' : 'Back'}
            </Button>
            {step < STEP_TITLES.length - 1 ? (
              <Button
                type="button"
                disabled={!stepValid(step, values)}
                onClick={() => {
                  if (step === 3) {
                    handleStep4Next();
                  } else {
                    setStep((s) => s + 1);
                  }
                }}
                data-testid="step-next"
              >
                Next
              </Button>
            ) : (
              <Button
                // type="button" (not "submit") so submission goes through the
                // explicit onClick path. Pairs with the form's preventDefault
                // onSubmit above — the goal is to keep stray browser-driven
                // submit events from racing the user's deliberate click.
                type="button"
                disabled={!stepValid(step, values) || submitting}
                data-testid="create-study-submit"
                onClick={form.handleSubmit(onSubmit)}
              >
                {submitting ? 'Submitting…' : 'Create study'}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
