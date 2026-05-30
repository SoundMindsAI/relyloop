// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { InfoTooltip } from '@/components/common/info-tooltip';
import type { Schema } from '@/lib/api/clusters';

export interface IndexSummarySchemaTableProps {
  schema: Schema;
  /** Show the doc_count column when at least one field reports one. */
  showDocCount?: boolean;
}

type SortKey = 'name' | 'type';
type SortDir = 'asc' | 'desc';

/**
 * Renders the schema fields table for the index summary page (Story 3.2 / FR-7).
 *
 * Columns: Field (sortable), Type, Analyzer (tooltip header), Documents
 * (column-visibility-gated when at least one field reports a count).
 */
export function IndexSummarySchemaTable({
  schema,
  showDocCount = false,
}: IndexSummarySchemaTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [showCount, setShowCount] = useState<boolean>(showDocCount);

  const sortedFields = [...schema.fields].sort((a, b) => {
    const av = (a[sortKey] ?? '').toString();
    const bv = (b[sortKey] ?? '').toString();
    const cmp = av.localeCompare(bv);
    return sortDir === 'asc' ? cmp : -cmp;
  });

  function toggle(col: SortKey) {
    if (sortKey === col) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(col);
      setSortDir('asc');
    }
  }

  const indicator = (col: SortKey) => (sortKey === col ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '');

  const anyDocCount = schema.fields.some((f) => f.doc_count != null);

  return (
    <div className="space-y-2">
      {anyDocCount && (
        <div className="flex justify-end">
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={showCount}
              onChange={(e) => setShowCount(e.target.checked)}
              data-testid="schema-table-show-doc-count"
            />
            Show document counts
          </label>
        </div>
      )}
      <div className="overflow-hidden rounded border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-left text-xs uppercase text-muted-foreground">
            <tr>
              <th
                className="cursor-pointer px-3 py-2 font-medium"
                onClick={() => toggle('name')}
                data-testid="schema-table-th-name"
              >
                Field{indicator('name')}
              </th>
              <th
                className="cursor-pointer px-3 py-2 font-medium"
                onClick={() => toggle('type')}
                data-testid="schema-table-th-type"
              >
                Type{indicator('type')}
              </th>
              <th className="px-3 py-2 font-medium">
                <span className="inline-flex items-center gap-1">
                  Analyzer
                  <InfoTooltip glossaryKey="target.schema_analyzer" />
                </span>
              </th>
              {showCount && <th className="px-3 py-2 font-medium text-right">Documents</th>}
            </tr>
          </thead>
          <tbody data-testid="schema-table-body">
            {sortedFields.map((field) => (
              <tr key={field.name} className="border-t border-border">
                <td className="px-3 py-2 font-mono text-xs">{field.name}</td>
                <td className="px-3 py-2 font-mono text-xs">{field.type}</td>
                <td className="px-3 py-2 font-mono text-xs">
                  {field.analyzer ?? <span className="text-muted-foreground">—</span>}
                </td>
                {showCount && (
                  <td className="px-3 py-2 text-right tabular-nums">
                    {field.doc_count != null ? (
                      field.doc_count.toLocaleString()
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
