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
import { Textarea } from '@/components/ui/textarea';
import { useCreateQuerySet } from '@/lib/api/query-sets';

interface CreateQuerySetFormValues {
  name: string;
  description?: string;
  cluster_id: string;
}

export interface CreateQuerySetModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultClusterId?: string;
}

export function CreateQuerySetModal({
  open,
  onOpenChange,
  defaultClusterId,
}: CreateQuerySetModalProps) {
  const create = useCreateQuerySet();
  const [submitting, setSubmitting] = useState(false);
  const form = useForm<CreateQuerySetFormValues>({
    defaultValues: {
      name: '',
      description: '',
      cluster_id: defaultClusterId ?? '',
    },
  });

  function submit(values: CreateQuerySetFormValues) {
    setSubmitting(true);
    create.mutate(
      {
        name: values.name,
        description: values.description || null,
        cluster_id: values.cluster_id,
      },
      {
        onSuccess: () => {
          toast.success('Query set created');
          form.reset();
          onOpenChange(false);
        },
        onSettled: () => setSubmitting(false),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create query set</DialogTitle>
          <DialogDescription>
            A query set is a named collection of queries scoped to one cluster. Use the bulk-add
            dialog on the detail page to upload JSON or CSV.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={form.handleSubmit(submit)}
          className="space-y-4"
          data-testid="create-query-set-form"
        >
          <div className="space-y-1.5">
            <Label htmlFor="qs-name">Name</Label>
            <Input id="qs-name" {...form.register('name', { required: true })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="qs-cluster">Cluster ID</Label>
            <Input
              id="qs-cluster"
              {...form.register('cluster_id', { required: true })}
              placeholder="UUIDv7 of the registered cluster"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="qs-desc">Description (optional)</Label>
            <Textarea id="qs-desc" rows={3} {...form.register('description')} />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting} data-testid="create-query-set-submit">
              {submitting ? 'Creating…' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
