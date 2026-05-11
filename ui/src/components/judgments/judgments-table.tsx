'use client';
import { StatusBadge } from '@/components/common/status-badge';
import { OverridePopover } from '@/components/judgments/override-popover';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { JudgmentRow } from '@/lib/api/judgments';
import { JUDGMENT_SOURCE_FILTER_VALUES } from '@/lib/enums';

const SOURCE_CHOICES = ['all', ...JUDGMENT_SOURCE_FILTER_VALUES] as const;
type SourceChoice = (typeof SOURCE_CHOICES)[number];

export interface JudgmentsTableProps {
  rows: readonly JudgmentRow[];
  listId: string;
  sourceFilter: SourceChoice;
  onSourceFilterChange: (next: SourceChoice) => void;
}

export function JudgmentsTable({
  rows,
  listId,
  sourceFilter,
  onSourceFilterChange,
}: JudgmentsTableProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2" role="group" aria-label="Source filter">
        {SOURCE_CHOICES.map((choice) => (
          <Button
            key={choice}
            type="button"
            variant={choice === sourceFilter ? 'default' : 'outline'}
            size="sm"
            data-testid={`source-chip-${choice}`}
            data-active={choice === sourceFilter ? 'true' : 'false'}
            onClick={() => onSourceFilterChange(choice)}
          >
            {choice}
          </Button>
        ))}
      </div>
      {rows.length === 0 ? (
        <p
          className="py-12 text-center text-sm text-muted-foreground"
          data-testid="judgments-empty"
        >
          No judgments match the current filters.
        </p>
      ) : (
        <Table data-testid="judgments-table">
          <TableHeader>
            <TableRow>
              <TableHead>Query</TableHead>
              <TableHead>Doc</TableHead>
              <TableHead>Rating</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Notes</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((j) => (
              <TableRow key={j.id} data-testid={`judgment-row-${j.id}`}>
                <TableCell className="font-mono text-xs">{j.query_id}</TableCell>
                <TableCell className="font-mono text-xs">{j.doc_id}</TableCell>
                <TableCell data-testid={`judgment-rating-${j.id}`}>{j.rating}</TableCell>
                <TableCell>
                  <span data-testid={`judgment-source-${j.id}`}>
                    <StatusBadge kind="judgment_list" value={j.source} />
                  </span>
                </TableCell>
                <TableCell data-testid={`judgment-notes-${j.id}`}>
                  {j.notes ?? <span className="text-muted-foreground">—</span>}
                </TableCell>
                <TableCell>
                  <OverridePopover listId={listId} judgment={j} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

export type { SourceChoice };
export { SOURCE_CHOICES };
