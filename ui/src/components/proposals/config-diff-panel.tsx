'use client';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

export interface ConfigDiffPanelProps {
  diff: Record<string, unknown>;
}

function renderValue(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}

/**
 * Backend writes `proposals.config_diff` from feat_digest_proposal as a
 * flat `{ "<param>": {"from": <prev>, "to": <new>} }` dict — see
 * backend/workers/digest.py:1152. Manual / agent-created proposals may
 * also write a flat `{ "<param>": ["before", "after"] }` 2-tuple
 * (legacy shape) or a non-per-key shape like
 * `{"params": {...}, "source": "..."}` (agent tool); this panel renders
 * the canonical `{from, to}` object form, falls back to the 2-tuple
 * array form, and drops to a single "value" column for everything else.
 */
function extractFromTo(raw: unknown): { from: unknown; to: unknown } {
  // Canonical digest-worker form: { from, to } object per key.
  if (
    raw !== null &&
    typeof raw === 'object' &&
    !Array.isArray(raw) &&
    'from' in (raw as object) &&
    'to' in (raw as object)
  ) {
    const r = raw as { from: unknown; to: unknown };
    return { from: r.from, to: r.to };
  }
  // Legacy 2-tuple form: [before, after].
  if (Array.isArray(raw) && raw.length === 2) {
    return { from: raw[0], to: raw[1] };
  }
  // Unknown shape — render as a single value in the "To" column.
  return { from: null, to: raw };
}

export function ConfigDiffPanel({ diff }: ConfigDiffPanelProps) {
  const entries = Object.entries(diff ?? {}).sort(([a], [b]) => a.localeCompare(b));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Config diff</CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p
            className="py-6 text-center text-sm text-muted-foreground"
            data-testid="config-diff-empty"
          >
            No changes recorded.
          </p>
        ) : (
          <Table data-testid="config-diff-table">
            <TableHeader>
              <TableRow>
                <TableHead>
                  <span className="inline-flex items-center gap-1">
                    Key
                    <InfoTooltip glossaryKey="proposal.config_diff.key" />
                  </span>
                </TableHead>
                <TableHead>
                  <span className="inline-flex items-center gap-1">
                    From
                    <InfoTooltip glossaryKey="proposal.config_diff.from" />
                  </span>
                </TableHead>
                <TableHead>
                  <span className="inline-flex items-center gap-1">
                    To
                    <InfoTooltip glossaryKey="proposal.config_diff.to" />
                  </span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map(([key, raw]) => {
                const { from, to } = extractFromTo(raw);
                return (
                  <TableRow key={key} data-testid={`config-diff-row-${key}`}>
                    <TableCell className="font-mono text-xs">{key}</TableCell>
                    <TableCell className="font-mono text-xs">{renderValue(from)}</TableCell>
                    <TableCell className="font-mono text-xs">{renderValue(to)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
