// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { useEffect } from 'react';
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
import { TemplateBodyEditor } from '@/components/templates/template-body-editor';
import { useCreateTemplate, type QueryTemplateDetail } from '@/lib/api/query-templates';

interface ForkFormValues {
  name: string;
  body: string;
}

export interface ForkTemplateModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  parent: QueryTemplateDetail;
}

export function ForkTemplateModal({ open, onOpenChange, parent }: ForkTemplateModalProps) {
  const create = useCreateTemplate();
  const form = useForm<ForkFormValues>({
    defaultValues: { name: `${parent.name} (v${parent.version + 1})`, body: parent.body },
  });

  // Refresh defaults whenever the parent template the modal points at changes.
  useEffect(() => {
    if (open) {
      form.reset({ name: `${parent.name} (v${parent.version + 1})`, body: parent.body });
    }
  }, [open, parent.id, parent.body, parent.name, parent.version, form]);

  function onSubmit(values: ForkFormValues) {
    create.mutate(
      {
        name: values.name,
        engine_type: parent.engine_type,
        body: values.body,
        declared_params: parent.declared_params,
        parent_id: parent.id,
      },
      {
        onSuccess: () => {
          toast.success('Template forked');
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            Fork &ldquo;{parent.name}&rdquo; (v{parent.version})
          </DialogTitle>
          <DialogDescription>
            Templates are immutable. Forking creates a new version that references the parent.
            Declared parameters carry over verbatim — edit the body to adjust the rendered DSL.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" data-testid="fork-form">
          <div className="space-y-1.5">
            <Label htmlFor="fork-name">Name</Label>
            <Input id="fork-name" {...form.register('name', { required: true })} />
          </div>
          <div className="space-y-1.5">
            <Label>Body</Label>
            <TemplateBodyEditor
              value={form.watch('body')}
              onChange={(v) => form.setValue('body', v)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending} data-testid="fork-submit">
              {create.isPending ? 'Forking…' : 'Fork'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
