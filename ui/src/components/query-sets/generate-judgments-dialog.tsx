'use client';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';

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
import { useGenerateJudgments } from '@/lib/api/judgments';
import { useTemplates } from '@/lib/api/query-templates';

interface GenerateFormValues {
  name: string;
  description?: string;
  target: string;
  current_template_id: string;
  rubric: string;
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

export function GenerateJudgmentsDialog({
  open,
  onOpenChange,
  clusterId,
  querySetId,
}: GenerateJudgmentsDialogProps) {
  const generate = useGenerateJudgments();
  const templates = useTemplates({ limit: 200 });
  const [submitting, setSubmitting] = useState(false);
  const form = useForm<GenerateFormValues>({
    defaultValues: {
      name: '',
      description: '',
      target: '',
      current_template_id: '',
      rubric: DEFAULT_RUBRIC,
    },
  });

  function submit(values: GenerateFormValues) {
    setSubmitting(true);
    generate.mutate(
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
          toast.success('Generation started — check the judgment list shortly');
          form.reset();
          onOpenChange(false);
        },
        onSettled: () => setSubmitting(false),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Generate judgments</DialogTitle>
          <DialogDescription>
            Run the LLM judge against every (query × top-K) pair retrieved by the chosen template.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={form.handleSubmit(submit)}
          className="space-y-4"
          data-testid="generate-form"
        >
          <div className="space-y-1.5">
            <Label htmlFor="gen-name">Judgment list name</Label>
            <Input id="gen-name" {...form.register('name', { required: true })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gen-target">Target index / collection</Label>
            <Input id="gen-target" {...form.register('target', { required: true })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gen-template">Current template</Label>
            <Select
              value={form.watch('current_template_id')}
              onValueChange={(v) => form.setValue('current_template_id', v)}
            >
              <SelectTrigger id="gen-template">
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
          <div className="space-y-1.5">
            <Label htmlFor="gen-rubric">Rubric</Label>
            <Textarea id="gen-rubric" rows={6} {...form.register('rubric', { required: true })} />
          </div>
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
