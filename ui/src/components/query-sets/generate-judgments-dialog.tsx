'use client';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';

import { UbiOnrampNudge } from '@/components/clusters/ubi-onramp-nudge';
import { EntitySelect } from '@/components/common/entity-select';
import { HelpPopover } from '@/components/common/help-popover';
import { UbiSparseDataCard } from '@/components/query-sets/ubi-sparse-data-card';
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
import { useCluster } from '@/lib/api/clusters';
import { useGenerateJudgments } from '@/lib/api/judgments';
import { useTemplates } from '@/lib/api/query-templates';
import { useGenerateJudgmentsFromUbi, useUbiReadiness } from '@/lib/api/ubi';
import { JUDGMENT_GENERATION_METHOD_VALUES, type JudgmentGenerationMethod } from '@/lib/enums';

interface GenerateFormValues {
  name: string;
  description?: string;
  target: string;
  current_template_id: string;
  rubric: string;
  method: JudgmentGenerationMethod;
  since: string;
  until: string;
  llm_fill_threshold: number;
}

export interface GenerateJudgmentsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clusterId: string;
  querySetId: string;
}

const DEFAULT_RUBRIC = [
  'Rate each (query, document) pair on a 0–3 scale:',
  '  0 — not relevant',
  '  1 — marginally relevant',
  '  2 — relevant',
  '  3 — highly relevant',
  'Always include a one-line rationale.',
].join('\n');

const METHOD_LABELS: Record<JudgmentGenerationMethod, string> = {
  llm: 'LLM-as-judge',
  ctr_threshold: 'UBI (click-through)',
  dwell_time: 'UBI (dwell-time)',
  hybrid_ubi_llm: 'Hybrid UBI + LLM',
};

const NUDGE_DISMISS_KEY_PREFIX = 'relyloop.ubi-onramp-nudge.dismissed:';

function thirtyDaysAgoIso(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 30);
  return d.toISOString().slice(0, 16); // datetime-local format YYYY-MM-DDTHH:MM
}

function isoToUtcMs(local: string): string {
  // datetime-local form value is naive (no TZ). Treat it as UTC for the wire.
  // The browser may return YYYY-MM-DDTHH:MM *or* include seconds/milliseconds;
  // string-concatenating ':00.000Z' breaks on the latter, so parse via Date
  // (appending 'Z' to force UTC interpretation) and fall back to "now" on an
  // unparseable value (Gemini PR #317 finding #6).
  if (!local) return new Date().toISOString();
  const naive = local.includes('Z') ? local : `${local}Z`;
  const date = new Date(naive);
  return isNaN(date.getTime()) ? new Date().toISOString() : date.toISOString();
}

function defaultMethodForRung(rung: string | undefined): JudgmentGenerationMethod {
  if (rung === 'rung_3') return 'ctr_threshold';
  if (rung === 'rung_2' || rung === 'rung_1') return 'hybrid_ubi_llm';
  return 'llm';
}

export function GenerateJudgmentsDialog({
  open,
  onOpenChange,
  clusterId,
  querySetId,
}: GenerateJudgmentsDialogProps) {
  const generateLlm = useGenerateJudgments();
  const generateUbi = useGenerateJudgmentsFromUbi();
  const templates = useTemplates({ limit: 200 });
  const cluster = useCluster(clusterId);
  const [submitting, setSubmitting] = useState(false);
  const [nudgeDismissed, setNudgeDismissed] = useState(false);

  const form = useForm<GenerateFormValues>({
    defaultValues: {
      name: '',
      description: '',
      target: '',
      current_template_id: '',
      rubric: DEFAULT_RUBRIC,
      method: 'llm',
      since: thirtyDaysAgoIso(),
      until: '',
      llm_fill_threshold: 20,
    },
  });

  const watchedTarget = form.watch('target');
  const watchedMethod = form.watch('method');
  const ubiReadiness = useUbiReadiness(clusterId, querySetId, watchedTarget || null);
  const rung = ubiReadiness.data?.rung;

  // Seed the picker default from the rung when readiness resolves and the
  // user hasn't manually picked yet (defaultValues stays at 'llm' until then).
  // The setValue runs once per (rung, dialog-open) — the [open, rung] dep
  // resets when the dialog reopens so a re-open re-evaluates.
  useEffect(() => {
    if (!open) return;
    if (rung === undefined) return;
    if (form.formState.dirtyFields.method) return; // operator already picked
    form.setValue('method', defaultMethodForRung(rung));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rung]);

  // Restore the per-cluster nudge dismissal on open.
  useEffect(() => {
    if (!open) return;
    if (typeof window === 'undefined') return;
    try {
      const stored = window.localStorage.getItem(`${NUDGE_DISMISS_KEY_PREFIX}${clusterId}`);
      setNudgeDismissed(stored === '1');
    } catch {
      // localStorage unavailable — assume not dismissed.
      setNudgeDismissed(false);
    }
  }, [open, clusterId]);

  function handleDismissNudge() {
    setNudgeDismissed(true);
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(`${NUDGE_DISMISS_KEY_PREFIX}${clusterId}`, '1');
    } catch {
      // best-effort; UI state already reflects dismissal
    }
  }

  function submit(values: GenerateFormValues) {
    setSubmitting(true);
    const isLlmOnly = values.method === 'llm';
    if (isLlmOnly) {
      generateLlm.mutate(
        {
          name: values.name,
          description: values.description || null,
          query_set_id: querySetId,
          cluster_id: clusterId,
          target: values.target,
          current_template_id: values.current_template_id,
          rubric: values.rubric,
        },
        {
          onSuccess: () => {
            toast.success('LLM generation started — check the judgment list shortly');
            form.reset();
            onOpenChange(false);
          },
          onSettled: () => setSubmitting(false),
        },
      );
      return;
    }
    // values.method is narrowed by the early return above — it can only be
    // one of the three UBI converters here.
    const ubiConverter = values.method as Exclude<JudgmentGenerationMethod, 'llm'>;
    const isHybrid = ubiConverter === 'hybrid_ubi_llm';
    generateUbi.mutate(
      {
        name: values.name,
        description: values.description || null,
        query_set_id: querySetId,
        cluster_id: clusterId,
        target: values.target,
        since: isoToUtcMs(values.since),
        until: values.until ? isoToUtcMs(values.until) : null,
        converter: ubiConverter,
        llm_fill_threshold: isHybrid ? values.llm_fill_threshold : null,
        mapping_strategy: 'reject',
        current_template_id: isHybrid ? values.current_template_id : null,
        rubric: isHybrid ? values.rubric : null,
      },
      {
        onSuccess: () => {
          toast.success('UBI generation started — check the judgment list shortly');
          form.reset();
          onOpenChange(false);
        },
        onSettled: () => setSubmitting(false),
      },
    );
  }

  const showNudge = rung === 'rung_0' && !nudgeDismissed && cluster.data;
  const showSparseCard =
    rung === 'rung_1' && (watchedMethod === 'ctr_threshold' || watchedMethod === 'dwell_time');
  const showRubric = watchedMethod === 'llm' || watchedMethod === 'hybrid_ubi_llm';
  const showTemplate = watchedMethod === 'llm' || watchedMethod === 'hybrid_ubi_llm';
  const showUbiWindow = watchedMethod !== 'llm';
  const showLlmFillThreshold = watchedMethod === 'hybrid_ubi_llm';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Generate judgments</DialogTitle>
          <DialogDescription>
            Rate every (query × top-K) pair via LLM, UBI signal, or a hybrid mix.
          </DialogDescription>
        </DialogHeader>
        {showNudge && cluster.data && (
          <UbiOnrampNudge
            clusterId={clusterId}
            engineType={cluster.data.engine_type}
            onDismiss={handleDismissNudge}
          />
        )}
        <form
          onSubmit={form.handleSubmit(submit)}
          className="space-y-4"
          data-testid="generate-form"
        >
          <div className="space-y-1.5">
            <Label htmlFor="gen-name">Judgment list name</Label>
            <Input
              id="gen-name"
              data-testid="gen-name"
              {...form.register('name', { required: true })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gen-target">Target index / collection</Label>
            <Input
              id="gen-target"
              data-testid="gen-target"
              {...form.register('target', { required: true })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gen-method">
              Method
              <HelpPopover glossaryKey="judgment.converter" />
            </Label>
            <Select
              value={watchedMethod}
              onValueChange={(v) =>
                form.setValue('method', v as JudgmentGenerationMethod, { shouldDirty: true })
              }
            >
              <SelectTrigger id="gen-method" data-testid="gen-method">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {JUDGMENT_GENERATION_METHOD_VALUES.map((method) => (
                  <SelectItem key={method} value={method}>
                    {METHOD_LABELS[method]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {showSparseCard && (
            <UbiSparseDataCard
              coveragePct={ubiReadiness.data?.covered_pairs_pct ?? null}
              onSwitchToHybrid={() =>
                form.setValue('method', 'hybrid_ubi_llm', { shouldDirty: true })
              }
            />
          )}
          {showUbiWindow && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="gen-since">UBI window — from</Label>
                <Input
                  id="gen-since"
                  type="datetime-local"
                  data-testid="gen-since"
                  {...form.register('since')}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="gen-until">UBI window — to (optional)</Label>
                <Input
                  id="gen-until"
                  type="datetime-local"
                  data-testid="gen-until"
                  {...form.register('until')}
                />
              </div>
            </div>
          )}
          {showTemplate && (
            <div className="space-y-1.5">
              <Label htmlFor="gen-template">Current template</Label>
              <EntitySelect
                id="gen-template"
                data-testid="gen-template"
                query={templates}
                getId={(t) => t.id}
                getLabel={(t) => `${t.name} (v${t.version})`}
                value={form.watch('current_template_id') || undefined}
                onChange={(v) => form.setValue('current_template_id', v ?? '')}
                placeholder="Choose a template"
              />
            </div>
          )}
          {showLlmFillThreshold && (
            <div className="space-y-1.5">
              <Label htmlFor="gen-llm-fill">LLM-fill threshold (impressions)</Label>
              <Input
                id="gen-llm-fill"
                type="number"
                min={1}
                data-testid="gen-llm-fill"
                {...form.register('llm_fill_threshold', { valueAsNumber: true, min: 1 })}
              />
              <p className="text-xs text-muted-foreground">
                Pairs with fewer than this many impressions get LLM-rated; the rest use UBI signal.
              </p>
            </div>
          )}
          {showRubric && (
            <div className="space-y-1.5">
              <Label htmlFor="gen-rubric">Rubric</Label>
              <Textarea
                id="gen-rubric"
                rows={6}
                {...form.register('rubric', { required: showRubric })}
              />
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting} data-testid="generate-submit">
              {submitting ? 'Starting…' : 'Generate'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
