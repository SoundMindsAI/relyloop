// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `<TemplatesTable>` thin DataTable consumer
 * (feat_data_table_primitive Story 3.4).
 */
import { DataTable } from '@/components/common/data-table';
import { templatesColumns } from '@/components/templates/templates-table.column-config';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';
import type { QueryTemplateSummary } from '@/lib/api/query-templates';

export interface TemplatesTableProps {
  rows: readonly QueryTemplateSummary[];
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;
  isLoading: boolean;
  isError: boolean;
  urlState: DataTableUrlStateApi;
}

export function TemplatesTable({
  rows,
  totalCount,
  has_more,
  next_cursor,
  isLoading,
  isError,
  urlState,
}: TemplatesTableProps) {
  return (
    <DataTable<QueryTemplateSummary>
      tableId="templates"
      tableTestId="templates-table"
      rowTestId={(r) => `template-row-${r.id}`}
      columns={templatesColumns}
      data={rows}
      isLoading={isLoading}
      isError={isError}
      totalCount={totalCount}
      has_more={has_more}
      next_cursor={next_cursor}
      searchable
      sort={urlState.sort}
      onSortChange={urlState.setSort}
      filters={urlState.filters}
      onFilterChange={urlState.setFilter}
      q={urlState.q}
      onQChange={urlState.setQ}
      cursor={urlState.cursor}
      pageSize={urlState.pageSize}
      onCursorChange={urlState.setCursor}
      onPageSizeChange={urlState.setPageSize}
      onClearMatchers={urlState.clearAllMatchers}
      anyMatcherActive={urlState.anyMatcherActive}
      emptyStateNoRows={{
        title: 'No templates yet',
        message: 'Click "Create template" to add one.',
      }}
      emptyStateNoMatch={{
        title: 'No templates match',
        message: 'No templates match the current filters.',
      }}
    />
  );
}
