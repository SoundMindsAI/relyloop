'use client';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { StatusBadge } from '@/components/common/status-badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { TrialDetail } from '@/lib/api/studies';
import { TRIAL_SORT_VALUES, type TrialSort } from '@/lib/enums';

export interface TrialsTableProps {
  rows: readonly TrialDetail[];
  sort: TrialSort;
  onSortChange: (sort: TrialSort) => void;
}

export function TrialsTable({ rows, sort, onSortChange }: TrialsTableProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm">
        <div className="flex items-center gap-1">
          <label htmlFor="trial-sort" className="text-muted-foreground">
            Sort by
          </label>
          <InfoTooltip glossaryKey="trial.sort_by" />
        </div>
        <Select value={sort} onValueChange={(v) => onSortChange(v as TrialSort)}>
          <SelectTrigger id="trial-sort" className="w-64">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TRIAL_SORT_VALUES.map((v) => (
              <SelectItem key={v} value={v}>
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {rows.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground" data-testid="trials-empty">
          No trials yet.
        </p>
      ) : (
        <Table data-testid="trials-table">
          <TableHeader>
            <TableRow>
              <TableHead>#</TableHead>
              <TableHead>
                <span className="inline-flex items-center gap-1">
                  Status
                  <InfoTooltip glossaryKey="trial.status" />
                </span>
              </TableHead>
              <TableHead>
                <span className="inline-flex items-center gap-1">
                  Primary metric
                  <InfoTooltip glossaryKey="trial.primary_metric" />
                </span>
              </TableHead>
              <TableHead>
                <span className="inline-flex items-center gap-1">
                  Duration (ms)
                  <InfoTooltip glossaryKey="trial.duration_ms" />
                </span>
              </TableHead>
              <TableHead>
                <span className="inline-flex items-center gap-1">
                  Params
                  <InfoTooltip glossaryKey="trial.params" />
                </span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t) => (
              <TableRow key={t.id} data-testid={`trial-row-${t.id}`}>
                <TableCell>{t.optuna_trial_number}</TableCell>
                <TableCell>
                  <StatusBadge kind="trial" value={t.status} />
                </TableCell>
                <TableCell>
                  {t.primary_metric != null ? t.primary_metric.toFixed(4) : '—'}
                </TableCell>
                <TableCell>{t.duration_ms ?? '—'}</TableCell>
                <TableCell className="font-mono text-xs">{JSON.stringify(t.params)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
