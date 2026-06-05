// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BestMetricPanel } from '@/components/studies/comparison/best-metric-panel';

describe('BestMetricPanel (FR-6)', () => {
  it('AC-12: minimize direction frames the lower UBI value as better', () => {
    render(
      <BestMetricPanel llmMetric={0.4} ubiMetric={0.3} direction="minimize" metricLabel="ndcg" />,
    );
    const delta = screen.getByTestId('compare-best-metric-delta');
    expect(delta).toHaveTextContent('-0.100');
    expect(delta).toHaveTextContent('UBI better');
  });

  it('maximize: higher UBI is better', () => {
    render(
      <BestMetricPanel llmMetric={0.4} ubiMetric={0.5} direction="maximize" metricLabel="ndcg" />,
    );
    expect(screen.getByTestId('compare-best-metric-delta')).toHaveTextContent('UBI better');
  });

  it('null metric → em-dash, no delta', () => {
    render(
      <BestMetricPanel llmMetric={null} ubiMetric={0.5} direction="maximize" metricLabel="ndcg" />,
    );
    expect(screen.getByTestId('compare-best-metric-llm')).toHaveTextContent('—');
    expect(screen.queryByTestId('compare-best-metric-delta')).toBeNull();
  });

  it('objectiveMismatch renders the qualifier caption', () => {
    render(
      <BestMetricPanel
        llmMetric={0.4}
        ubiMetric={0.5}
        direction="maximize"
        metricLabel="ndcg"
        objectiveMismatch
      />,
    );
    expect(screen.getByTestId('compare-best-metric-objective-caption')).toBeInTheDocument();
  });
});
