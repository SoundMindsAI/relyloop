// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

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
import { extractFromTo, renderValue } from '@/lib/config-diff';

export interface ConfigDiffPanelProps {
  diff: Record<string, unknown>;
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
