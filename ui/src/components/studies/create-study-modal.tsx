'use client';
import { useState } from 'react';
import { useForm, type SubmitHandler } from 'react-hook-form';
import { toast } from 'sonner';

import { HelpPopover } from '@/components/common/help-popover';
import { InfoTooltip } from '@/components/common/info-tooltip';
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
import { useClusters, useClusterSchema } from '@/lib/api/clusters';
import { useJudgmentLists } from '@/lib/api/judgments';
import { useTemplates } from '@/lib/api/query-templates';
import { useQuerySets } from '@/lib/api/query-sets';
import { useCreateStudy } from '@/lib/api/studies';
import {
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

const K_REQUIRED: ReadonlySet<ObjectiveMetric> = new Set(['ndcg', 'precision', 'recall']);

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
}

const STEP_TITLES = [
  'Cluster + target',
  'Query set + judgments',
  'Template',
  'Search space',
  'Objective + config',
] as const;

export interface CreateStudyModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateStudyModal({ open, onOpenChange }: CreateStudyModalProps) {
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
      parallelism: 4,
      sampler: 'tpe',
      pruner: 'median',
    },
  });

  const clusterId = form.watch('cluster_id');
  const target = form.watch('target');
  const querySetId = form.watch('query_set_id');
  const metric = form.watch('metric');

  const clusters = useClusters({ limit: 200 });
  const selectedCluster = clusters.data?.data.find((c) => c.id === clusterId);
  const schema = useClusterSchema(clusterId, target || undefined);
  const querySets = useQuerySets({ cluster_id: clusterId || undefined, limit: 200 });
  const judgmentLists = useJudgmentLists({
    query_set_id: querySetId || undefined,
    limit: 200,
  });
  const templates = useTemplates({
    engine_type: selectedCluster?.engine_type,
    limit: 200,
  });

  // Child-select resets are handled inline in onValueChange below — no
  // useEffect needed (and an effect here would create a state-thrash loop
  // under React 19 + jsdom strict-mode rendering).

  function stepValid(s: number, values: FormValues): boolean {
    switch (s) {
      case 0:
        return Boolean(values.cluster_id && values.target);
      case 1:
        return Boolean(values.query_set_id && values.judgment_list_id);
      case 2:
        return Boolean(values.template_id);
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
    if (K_REQUIRED.has(values.metric) && values.k != null) {
      objective.k = values.k;
    } else if (!K_REQUIRED.has(values.metric) && values.k != null) {
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
    };
    const config: ConfigSpec = {};
    if (typeof values.max_trials === 'number') config.max_trials = values.max_trials;
    if (typeof values.time_budget_min === 'number') config.time_budget_min = values.time_budget_min;
    if (typeof values.parallelism === 'number') config.parallelism = values.parallelism;
    if (typeof values.trial_timeout_s === 'number') config.trial_timeout_s = values.trial_timeout_s;
    if (values.sampler) config.sampler = values.sampler;
    if (values.pruner) config.pruner = values.pruner;
    if (typeof values.seed === 'number') config.seed = values.seed;

    setSubmitting(true);
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
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Create study</DialogTitle>
          <DialogDescription>
            Step {step + 1} of {STEP_TITLES.length} — {STEP_TITLES[step]}
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="space-y-4"
          data-testid="create-study-form"
        >
          {step === 0 && (
            <div className="space-y-4" data-testid="step-1">
              <div className="space-y-1.5">
                <Label htmlFor="cs-cluster">Cluster</Label>
                <Select
                  value={values.cluster_id}
                  onValueChange={(v) => {
                    form.setValue('cluster_id', v);
                    form.setValue('query_set_id', '');
                    form.setValue('judgment_list_id', '');
                    form.setValue('template_id', '');
                  }}
                >
                  <SelectTrigger id="cs-cluster">
                    <SelectValue placeholder="Choose a cluster" />
                  </SelectTrigger>
                  <SelectContent>
                    {(clusters.data?.data ?? []).map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.name} ({c.engine_type})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center gap-1">
                  <Label htmlFor="cs-target">Target index / collection</Label>
                  <InfoTooltip glossaryKey="study.target" />
                </div>
                <Input id="cs-target" {...form.register('target')} placeholder="products" />
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
                <Select
                  value={values.query_set_id}
                  onValueChange={(v) => {
                    form.setValue('query_set_id', v);
                    form.setValue('judgment_list_id', '');
                  }}
                >
                  <SelectTrigger id="cs-qs">
                    <SelectValue placeholder="Choose a query set" />
                  </SelectTrigger>
                  <SelectContent>
                    {(querySets.data?.data ?? []).map((q) => (
                      <SelectItem key={q.id} value={q.id}>
                        {q.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cs-jl">Judgment list</Label>
                <Select
                  value={values.judgment_list_id}
                  onValueChange={(v) => form.setValue('judgment_list_id', v)}
                >
                  <SelectTrigger id="cs-jl">
                    <SelectValue placeholder="Choose a judgment list" />
                  </SelectTrigger>
                  <SelectContent>
                    {(judgmentLists.data?.data ?? []).map((j) => (
                      <SelectItem key={j.id} value={j.id}>
                        {j.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
                <Select
                  value={values.template_id}
                  onValueChange={(v) => form.setValue('template_id', v)}
                >
                  <SelectTrigger id="cs-tpl">
                    <SelectValue placeholder="Choose a template" />
                  </SelectTrigger>
                  <SelectContent>
                    {(templates.data?.data ?? []).map((t) => (
                      <SelectItem key={t.id} value={t.id}>
                        {t.name} (v{t.version})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}
          {step === 3 && (
            <div className="space-y-4" data-testid="step-4">
              <div className="space-y-1.5">
                <Label htmlFor="cs-name">Study name</Label>
                <Input id="cs-name" {...form.register('name')} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cs-space">Search space (JSON)</Label>
                <Textarea
                  id="cs-space"
                  rows={10}
                  {...form.register('search_space_text')}
                  data-testid="cs-search-space"
                />
              </div>
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
                    onValueChange={(v) => form.setValue('metric', v as ObjectiveMetric)}
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
                  <div className="flex items-center gap-1">
                    <Label htmlFor="cs-k">k</Label>
                    <InfoTooltip glossaryKey="study.k" />
                  </div>
                  <Select
                    value={values.k != null ? String(values.k) : ''}
                    onValueChange={(v) =>
                      form.setValue('k', v ? (Number(v) as ObjectiveK) : undefined)
                    }
                  >
                    <SelectTrigger id="cs-k">
                      <SelectValue placeholder={K_REQUIRED.has(metric) ? 'required' : 'optional'} />
                    </SelectTrigger>
                    <SelectContent>
                      {OBJECTIVE_K_VALUES.map((k) => (
                        <SelectItem key={k} value={String(k)}>
                          {k}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
                onClick={() => setStep((s) => s + 1)}
                data-testid="step-next"
              >
                Next
              </Button>
            ) : (
              <Button
                type="submit"
                disabled={!stepValid(step, values) || submitting}
                data-testid="create-study-submit"
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
