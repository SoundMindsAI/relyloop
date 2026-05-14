'use client';
import { useState } from 'react';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CursorPaginator } from '@/components/common/cursor-paginator';
import { EmptyState } from '@/components/common/empty-state';
import { useQueries, type QueryRow } from '@/lib/api/query-sets';

import { DeleteQueryDialog } from './delete-query-dialog';
import { EditMetadataDialog } from './edit-metadata-dialog';
import { EditQueryPopover } from './edit-query-popover';

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 50;

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}

export interface QueriesTableProps {
  querySetId: string;
}

export function QueriesTable({ querySetId }: QueriesTableProps) {
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const [metadataQuery, setMetadataQuery] = useState<QueryRow | null>(null);

  const currentCursor = cursorStack[cursorStack.length - 1];
  const queries = useQueries(querySetId, { cursor: currentCursor, limit: pageSize });

  const onNext = () => {
    if (queries.data?.next_cursor) {
      setCursorStack((prev) => [...prev, queries.data.next_cursor ?? undefined]);
    }
  };
  const onPrev = () => {
    if (cursorStack.length > 1) {
      setCursorStack((prev) => prev.slice(0, -1));
    }
  };
  const onPageSizeChange = (next: number) => {
    setPageSize(next);
    setCursorStack([undefined]); // reset to first page on page-size change
  };

  if (queries.isPending) {
    return <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (queries.isError) {
    return <EmptyState title="Failed to load queries" message="Try again or check the backend." />;
  }
  if (!queries.data || queries.data.data.length === 0) {
    return (
      <EmptyState
        title="No queries yet"
        message="Use Add queries above to bulk-upload JSON or CSV."
      />
    );
  }

  const rows = queries.data.data;

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground" data-testid="queries-total">
        {queries.data.totalCount.toLocaleString()} queries total
      </p>
      <Table data-testid="queries-table">
        <TableHeader>
          <TableRow>
            <TableHead>Query text</TableHead>
            <TableHead>Reference answer</TableHead>
            <TableHead>Metadata</TableHead>
            <TableHead
              className="w-24 text-right"
              title="Number of (query, doc) ratings across all judgment lists for this query"
            >
              Judgments
            </TableHead>
            <TableHead className="w-32" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id} data-testid={`row-${row.id}`}>
              <TableCell className="max-w-md" title={row.query_text}>
                {truncate(row.query_text, 100)}
              </TableCell>
              <TableCell
                className="max-w-xs"
                title={row.reference_answer ?? 'Reference answer not set'}
              >
                {row.reference_answer === null ? '—' : truncate(row.reference_answer, 50)}
              </TableCell>
              <TableCell>
                <Badge
                  variant={row.query_metadata ? 'default' : 'secondary'}
                  role="button"
                  tabIndex={0}
                  aria-label={
                    row.query_metadata
                      ? 'Edit query metadata (set)'
                      : 'Edit query metadata (not set)'
                  }
                  onClick={() => setMetadataQuery(row)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setMetadataQuery(row);
                    }
                  }}
                  className="cursor-pointer focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
                  data-testid={`meta-badge-${row.id}`}
                >
                  {row.query_metadata ? 'Set' : '—'}
                </Badge>
              </TableCell>
              <TableCell className="text-right">{row.judgment_count.toLocaleString()}</TableCell>
              <TableCell className="text-right">
                <div className="flex justify-end gap-1">
                  <EditQueryPopover
                    querySetId={querySetId}
                    query={row}
                    trigger={
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Edit query"
                        title="Edit query text and reference answer"
                        data-testid={`edit-${row.id}`}
                      >
                        ✏️
                      </Button>
                    }
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setMetadataQuery(row)}
                    aria-label="Edit query metadata"
                    title="Edit query metadata"
                    data-testid={`meta-${row.id}`}
                  >
                    {'{ }'}
                  </Button>
                  <DeleteQueryDialog
                    querySetId={querySetId}
                    query={row}
                    trigger={
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Delete query"
                        title={
                          row.judgment_count > 0
                            ? `Delete blocked — query has ${row.judgment_count} judgment(s). Remove the parent judgment list first.`
                            : 'Delete query'
                        }
                        className="text-destructive"
                        data-testid={`delete-${row.id}`}
                      >
                        🗑
                      </Button>
                    }
                  />
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <CursorPaginator
        hasMore={queries.data.has_more}
        onNext={queries.data.has_more ? onNext : undefined}
        onPrev={cursorStack.length > 1 ? onPrev : undefined}
        pageSize={pageSize}
        onPageSizeChange={onPageSizeChange}
        totalCount={queries.data.totalCount}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
      />

      {metadataQuery && (
        <EditMetadataDialog
          querySetId={querySetId}
          query={metadataQuery}
          open={metadataQuery !== null}
          onOpenChange={(open) => {
            if (!open) setMetadataQuery(null);
          }}
        />
      )}
    </div>
  );
}
