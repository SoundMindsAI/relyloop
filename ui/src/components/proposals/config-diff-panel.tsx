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
 * Backend writes `proposals.config_diff` from feat_digest_proposal as a flat
 * `{ "key": ["before_value", "after_value"] }` dict. Manual proposals can carry
 * any flat shape; this panel renders the canonical 2-tuple form and falls back
 * to a single "value" column for non-tuple entries.
 */
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
                let from: unknown = null;
                let to: unknown = raw;
                if (Array.isArray(raw) && raw.length === 2) {
                  [from, to] = raw;
                }
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
