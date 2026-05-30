// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { useState, type ReactNode } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Textarea } from '@/components/ui/textarea';
import { useUpdateQuery, type QueryRow, type UpdateQueryRequest } from '@/lib/api/query-sets';

interface EditQueryFormValues {
  query_text: string;
  reference_answer: string; // empty string sentinel — converted to null on submit
}

export interface EditQueryPopoverProps {
  querySetId: string;
  query: QueryRow;
  trigger: ReactNode;
}

export function EditQueryPopover({ querySetId, query, trigger }: EditQueryPopoverProps) {
  const [open, setOpen] = useState(false);
  const update = useUpdateQuery(querySetId);
  const form = useForm<EditQueryFormValues>({
    defaultValues: {
      query_text: query.query_text,
      reference_answer: query.reference_answer ?? '',
    },
  });

  const onSubmit = (values: EditQueryFormValues) => {
    // Build a minimal PATCH body: only send keys whose values differ from the
    // current query, so omitted-key semantics are preserved server-side.
    const patch: UpdateQueryRequest = {};
    const trimmedText = values.query_text;
    if (trimmedText !== query.query_text) {
      patch.query_text = trimmedText;
    }
    const newRef = values.reference_answer === '' ? null : values.reference_answer;
    if (newRef !== query.reference_answer) {
      patch.reference_answer = newRef;
    }

    if (Object.keys(patch).length === 0) {
      // No-op — close without firing the PATCH.
      setOpen(false);
      return;
    }

    update.mutate(
      { queryId: query.id, patch },
      {
        onSuccess: () => {
          toast.success('Query updated');
          setOpen(false);
        },
      },
    );
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          form.reset({
            query_text: query.query_text,
            reference_answer: query.reference_answer ?? '',
          });
        }
      }}
    >
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent className="w-96" align="end">
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="space-y-3"
          data-testid="edit-query-form"
        >
          <h3 className="text-sm font-medium">Edit query</h3>
          <div className="space-y-1">
            <Label htmlFor="query_text">Query text</Label>
            <Textarea
              id="query_text"
              rows={3}
              {...form.register('query_text', {
                required: 'Query text is required',
                minLength: { value: 1, message: 'Query text must be at least 1 character' },
                maxLength: { value: 4000, message: 'Query text must be 4000 characters or fewer' },
              })}
              data-testid="edit-query-text"
            />
            {form.formState.errors.query_text && (
              <p className="text-xs text-destructive" role="alert">
                {form.formState.errors.query_text.message}
              </p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="reference_answer">Reference answer (optional)</Label>
            <Textarea
              id="reference_answer"
              rows={2}
              {...form.register('reference_answer')}
              placeholder="Leave blank to clear"
              data-testid="edit-reference-answer"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={update.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={update.isPending} data-testid="edit-query-save">
              {update.isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
