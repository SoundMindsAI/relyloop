// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

export interface ParameterImportanceChartProps {
  data: Record<string, number>;
  height?: number;
}

export function ParameterImportanceChart({ data, height = 240 }: ParameterImportanceChartProps) {
  const rows = Object.entries(data)
    .map(([param, importance]) => ({ param, importance }))
    .sort((a, b) => b.importance - a.importance);
  if (rows.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground" data-testid="param-chart-empty">
        No parameter-importance data yet.
      </p>
    );
  }
  return (
    <div data-testid="parameter-importance-chart" style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 8, right: 16, bottom: 8, left: 24 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis dataKey="param" type="category" width={120} />
          <Tooltip formatter={(value) => Number(value).toFixed(3)} />
          <Bar dataKey="importance" fill="#3b82f6" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
