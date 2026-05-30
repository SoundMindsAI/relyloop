// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

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
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useUpdateQuery, type QueryRow } from '@/lib/api/query-sets';

interface FormValues {
  metadata_json: string;
}

export interface EditMetadataDialogProps {
  querySetId: string;
  query: QueryRow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const NULL_PLACEHOLDER = '';

function initialJson(query: QueryRow): string {
  return query.query_metadata ? JSON.stringify(query.query_metadata, null, 2) : NULL_PLACEHOLDER;
}

export function EditMetadataDialog({
  querySetId,
  query,
  open,
  onOpenChange,
}: EditMetadataDialogProps) {
  const update = useUpdateQuery(querySetId);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const form = useForm<FormValues>({
    defaultValues: { metadata_json: initialJson(query) },
  });

  const onSubmit = (values: FormValues) => {
    setJsonError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(values.metadata_json);
    } catch {
      setJsonError('Invalid JSON');
      return;
    }
    // Plain object only — arrays, scalars, null all rejected per spec §FR-2.
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setJsonError('Metadata must be a JSON object. Use Clear metadata to set NULL.');
      return;
    }
    update.mutate(
      { queryId: query.id, patch: { query_metadata: parsed as Record<string, unknown> } },
      {
        onSuccess: () => {
          toast.success('Metadata updated');
          onOpenChange(false);
        },
      },
    );
  };

  const onClear = () => {
    setJsonError(null);
    update.mutate(
      { queryId: query.id, patch: { query_metadata: null } },
      {
        onSuccess: () => {
          toast.success('Metadata cleared');
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setJsonError(null);
          form.reset({ metadata_json: initialJson(query) });
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Edit query metadata</DialogTitle>
          <DialogDescription>
            Whole-object replace — Save sends the edited object as the new metadata.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="space-y-3"
          data-testid="edit-metadata-form"
        >
          <div className="space-y-1">
            <Label htmlFor="metadata_json">Metadata JSON</Label>
            <Textarea
              id="metadata_json"
              rows={12}
              className="font-mono text-xs"
              {...form.register('metadata_json')}
              data-testid="edit-metadata-textarea"
            />
            <p className="text-xs text-muted-foreground" data-testid="metadata-helper">
              JSON object only — arrays, strings, numbers, and <code>null</code> literal are
              rejected. Use <strong>Clear metadata</strong> to set the column to NULL.
            </p>
            {jsonError && (
              <p
                className="text-xs text-destructive"
                role="alert"
                data-testid="metadata-json-error"
              >
                {jsonError}
              </p>
            )}
          </div>
          <DialogFooter className="flex flex-row justify-between gap-2 sm:justify-between">
            <Button
              type="button"
              variant="outline"
              onClick={onClear}
              disabled={update.isPending}
              data-testid="clear-metadata-button"
            >
              Clear metadata
            </Button>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={update.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={update.isPending} data-testid="save-metadata-button">
                {update.isPending ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
