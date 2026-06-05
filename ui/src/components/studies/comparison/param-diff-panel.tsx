// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { partitionParamDiff } from '@/lib/diff/param-diff';

export interface ParamDiffPanelProps {
  /** LLM best-trial config (digest.recommended_config or trials fallback). */
  llmConfig: Record<string, unknown> | null;
  /** UBI best-trial config. */
  ubiConfig: Record<string, unknown> | null;
}

function render(value: unknown, present: boolean): string {
  if (!present) return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

/** Best-trial parameter-table diff (FR-5): one row per key, `=`/`Δ` flag. */
export function ParamDiffPanel({ llmConfig, ubiConfig }: ParamDiffPanelProps) {
  const rows = partitionParamDiff(llmConfig, ubiConfig);
  return (
    <Card data-testid="compare-param-diff-panel">
      <CardHeader>
        <CardTitle className="text-base">Best-trial parameters</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recommended parameters available.</p>
        ) : (
          <table className="w-full text-sm" data-testid="compare-param-diff-table">
            <thead>
              <tr className="text-xs uppercase text-muted-foreground">
                <th className="text-left">Parameter</th>
                <th className="text-left">LLM</th>
                <th className="text-center">Δ</th>
                <th className="text-left">UBI</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} data-testid={`compare-param-row-${row.key}`}>
                  <td className="font-mono text-xs">{row.key}</td>
                  <td className="font-mono text-xs">{render(row.aValue, row.present.a)}</td>
                  <td
                    className="text-center"
                    aria-label={row.flag === '=' ? 'unchanged' : 'changed'}
                  >
                    {row.flag}
                  </td>
                  <td className="font-mono text-xs">{render(row.bValue, row.present.b)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}
