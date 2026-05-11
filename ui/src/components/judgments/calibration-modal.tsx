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
import { Textarea } from '@/components/ui/textarea';
import {
  useCalibrate,
  type CalibrationResponse,
  type CalibrationSamplesRequest,
} from '@/lib/api/judgments';

export interface CalibrationModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  listId: string;
}

type ParsedSamples = NonNullable<CalibrationSamplesRequest['human_samples']>;

function parseCsv(text: string): ParsedSamples {
  const lines = text.split('\n').filter((l) => l.trim().length > 0);
  if (lines.length === 0) throw new Error('Empty CSV');
  const headerRow = lines[0];
  if (headerRow == null) throw new Error('Missing header row');
  const header = headerRow.split(',').map((s) => s.trim());
  const qi = header.indexOf('query_id');
  const di = header.indexOf('doc_id');
  const ri = header.indexOf('rating');
  if (qi < 0 || di < 0 || ri < 0) {
    throw new Error('CSV header must include query_id, doc_id, rating');
  }
  const out: ParsedSamples = [];
  for (let i = 1; i < lines.length; i++) {
    const row = lines[i];
    if (!row) continue;
    const parts = row.split(',').map((s) => s.trim());
    const rating = Number(parts[ri]);
    const queryId = parts[qi];
    const docId = parts[di];
    if (queryId == null || docId == null || !Number.isFinite(rating)) {
      throw new Error(`Row ${i + 1}: bad sample`);
    }
    if (rating !== 0 && rating !== 1 && rating !== 2 && rating !== 3) {
      throw new Error(`Row ${i + 1}: rating must be 0..3`);
    }
    out.push({ query_id: queryId, doc_id: docId, rating });
  }
  return out;
}

function parseJson(text: string): ParsedSamples {
  const arr = JSON.parse(text);
  if (!Array.isArray(arr)) throw new Error('JSON must be a list of samples');
  return arr;
}

export function CalibrationModal({ open, onOpenChange, listId }: CalibrationModalProps) {
  const [text, setText] = useState('');
  const [result, setResult] = useState<CalibrationResponse | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const calibrate = useCalibrate(listId);

  function submit() {
    setParseError(null);
    const trimmed = text.trim();
    let samples: ParsedSamples;
    try {
      samples =
        trimmed.startsWith('[') || trimmed.startsWith('{') ? parseJson(trimmed) : parseCsv(trimmed);
    } catch (e) {
      setParseError((e as Error).message);
      return;
    }
    calibrate.mutate(
      { human_samples: samples },
      {
        onSuccess: (response) => {
          setResult(response);
          toast.success(`Calibrated against ${response.n_samples} samples`);
        },
      },
    );
  }

  function handleClose(next: boolean) {
    if (!next) {
      setText('');
      setResult(null);
      setParseError(null);
    }
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Calibrate against human samples</DialogTitle>
          <DialogDescription>
            Paste a CSV (header: <code>query_id,doc_id,rating</code>) or JSON array of samples. The
            server computes Cohen&rsquo;s κ + weighted κ against the LLM judgments.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="cal-samples">Samples</Label>
            <Textarea
              id="cal-samples"
              rows={10}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={'query_id,doc_id,rating\nq1,d1,3\nq1,d2,2\n…'}
              data-testid="cal-samples"
            />
            {parseError && (
              <p className="text-xs text-destructive" data-testid="cal-parse-error">
                {parseError}
              </p>
            )}
          </div>
          {result && (
            <div className="rounded-md border bg-muted/40 p-3 text-sm" data-testid="cal-result">
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1">
                <div>
                  <dt className="text-xs uppercase text-muted-foreground">Cohen&rsquo;s κ</dt>
                  <dd data-testid="cal-cohens">
                    {result.cohens_kappa != null ? result.cohens_kappa.toFixed(3) : '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-muted-foreground">Weighted κ</dt>
                  <dd data-testid="cal-weighted">
                    {result.weighted_kappa != null ? result.weighted_kappa.toFixed(3) : '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-muted-foreground">Samples</dt>
                  <dd data-testid="cal-n">{result.n_samples}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-muted-foreground">Warning</dt>
                  <dd className="text-xs">{result.warning ?? '—'}</dd>
                </div>
              </dl>
              {Object.keys(result.per_class).length > 0 && (
                <div className="mt-3">
                  <p className="text-xs uppercase text-muted-foreground">Per-class agreement</p>
                  <ul className="mt-1 grid grid-cols-2 gap-1 font-mono text-xs">
                    {Object.entries(result.per_class).map(([k, v]) => (
                      <li key={k}>
                        {k}: {v.toFixed(3)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => handleClose(false)}>
            Close
          </Button>
          <Button
            type="button"
            onClick={submit}
            disabled={calibrate.isPending || !text.trim()}
            data-testid="cal-submit"
          >
            {calibrate.isPending ? 'Calibrating…' : 'Calibrate'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
