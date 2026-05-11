'use client';
import { useState } from 'react';
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useAddQueries } from '@/lib/api/query-sets';
import { validateQueryCsv } from '@/lib/csv-validate';

interface JsonQuery {
  query_text: string;
  reference_answer?: string | null;
  query_metadata?: Record<string, unknown> | null;
}

export interface AddQueriesDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  querySetId: string;
}

export function AddQueriesDialog({ open, onOpenChange, querySetId }: AddQueriesDialogProps) {
  const [jsonText, setJsonText] = useState('');
  const [csvText, setCsvText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const add = useAddQueries(querySetId);

  function submitJson() {
    setError(null);
    let parsed: JsonQuery[];
    try {
      const raw = JSON.parse(jsonText);
      if (!Array.isArray(raw)) {
        throw new Error('JSON must be an array of queries');
      }
      parsed = raw as JsonQuery[];
      if (parsed.length === 0) throw new Error('At least one query is required');
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    setSubmitting(true);
    add.mutate(
      { kind: 'json', queries: parsed },
      {
        onSuccess: (resp) => {
          toast.success(`Added ${resp.added} queries`);
          setJsonText('');
          onOpenChange(false);
        },
        onSettled: () => setSubmitting(false),
      },
    );
  }

  function submitCsv() {
    setError(null);
    const size = new Blob([csvText]).size;
    const validation = validateQueryCsv(csvText, size);
    if (!validation.ok) {
      setError(validation.error ?? 'Invalid CSV');
      return;
    }
    setSubmitting(true);
    add.mutate(
      { kind: 'csv', csv: csvText },
      {
        onSuccess: (resp) => {
          toast.success(`Added ${resp.added} queries`);
          setCsvText('');
          onOpenChange(false);
        },
        onSettled: () => setSubmitting(false),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) {
          setError(null);
        }
        onOpenChange(v);
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add queries</DialogTitle>
          <DialogDescription>
            Paste a JSON array or upload a CSV (header:{' '}
            <code>query_text[,reference_answer,metadata]</code>).
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="json">
          <TabsList>
            <TabsTrigger value="json" data-testid="bulk-tab-json">
              JSON
            </TabsTrigger>
            <TabsTrigger value="csv" data-testid="bulk-tab-csv">
              CSV
            </TabsTrigger>
          </TabsList>
          <TabsContent value="json" className="space-y-3 pt-3">
            <div className="space-y-1.5">
              <Label htmlFor="json-textarea">Queries (JSON array)</Label>
              <Textarea
                id="json-textarea"
                rows={12}
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
                placeholder={'[{"query_text":"red shoes"},{"query_text":"blue shoes"}]'}
                data-testid="bulk-json"
              />
            </div>
            <Button onClick={submitJson} disabled={submitting} data-testid="bulk-json-submit">
              {submitting ? 'Uploading…' : 'Upload JSON'}
            </Button>
          </TabsContent>
          <TabsContent value="csv" className="space-y-3 pt-3">
            <div className="space-y-1.5">
              <Label htmlFor="csv-textarea">Queries (CSV)</Label>
              <Textarea
                id="csv-textarea"
                rows={12}
                value={csvText}
                onChange={(e) => setCsvText(e.target.value)}
                placeholder={'query_text\nred shoes\nblue shoes'}
                data-testid="bulk-csv"
              />
            </div>
            <Button onClick={submitCsv} disabled={submitting} data-testid="bulk-csv-submit">
              {submitting ? 'Uploading…' : 'Upload CSV'}
            </Button>
          </TabsContent>
        </Tabs>
        {error && (
          <p className="text-xs text-destructive" data-testid="bulk-error">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
