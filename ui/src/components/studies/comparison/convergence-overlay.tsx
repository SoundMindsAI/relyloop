// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { CurvePoint } from '@/lib/diff/best-so-far-curve';

export interface ConvergenceOverlayProps {
  /** Pre-resolved LLM best-so-far curve (borrowed or derived); null = no data. */
  llmCurve: CurvePoint[] | null;
  /** Pre-resolved UBI best-so-far curve; null = no data. */
  ubiCurve: CurvePoint[] | null;
}

/**
 * Two-series best-so-far overlay (FR-7). Curves are resolved by the parent
 * (consume `convergence.best_so_far_curve` when present, else derive from
 * trials) so this component is a pure renderer.
 */
export function ConvergenceOverlay({ llmCurve, ubiCurve }: ConvergenceOverlayProps) {
  const hasData = (llmCurve?.length ?? 0) > 0 || (ubiCurve?.length ?? 0) > 0;

  // Merge both series onto a single trial_number axis for the chart.
  const byTrial = new Map<number, { trial_number: number; llm?: number; ubi?: number }>();
  for (const p of llmCurve ?? []) {
    byTrial.set(p.trial_number, {
      ...(byTrial.get(p.trial_number) ?? { trial_number: p.trial_number }),
      llm: p.best_so_far,
    });
  }
  for (const p of ubiCurve ?? []) {
    byTrial.set(p.trial_number, {
      ...(byTrial.get(p.trial_number) ?? { trial_number: p.trial_number }),
      ubi: p.best_so_far,
    });
  }
  const data = Array.from(byTrial.values()).sort((a, b) => a.trial_number - b.trial_number);

  return (
    <Card data-testid="compare-convergence-overlay">
      <CardHeader>
        <CardTitle className="text-base">Convergence</CardTitle>
      </CardHeader>
      <CardContent>
        {!hasData ? (
          <p className="text-sm text-muted-foreground" data-testid="compare-convergence-empty">
            no convergence data yet
          </p>
        ) : (
          <div style={{ width: '100%', height: 240 }} data-testid="compare-convergence-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="trial_number" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="llm"
                  name="LLM"
                  stroke="#2563eb"
                  connectNulls
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="ubi"
                  name="UBI"
                  stroke="#16a34a"
                  connectNulls
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
