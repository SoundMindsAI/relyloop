import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { MetricDelta } from '@/components/common/metric-delta';

describe('MetricDelta', () => {
  it('renders positive delta with + sign and green color', () => {
    render(<MetricDelta baseline={0.612} achieved={0.762} />);
    expect(screen.getByText('0.612 → 0.762')).toBeInTheDocument();
    const pct = screen.getByTestId('metric-delta-pct');
    expect(pct).toHaveTextContent('(+24.5%)');
    expect(pct.className).toContain('text-green-700');
  });

  it('renders negative delta without + and red color', () => {
    render(<MetricDelta baseline={0.8} achieved={0.6} />);
    const pct = screen.getByTestId('metric-delta-pct');
    expect(pct).toHaveTextContent('(-25.0%)');
    expect(pct.className).toContain('text-red-700');
  });

  it('renders zero delta as +0.0%', () => {
    render(<MetricDelta baseline={0.5} achieved={0.5} />);
    const pct = screen.getByTestId('metric-delta-pct');
    expect(pct).toHaveTextContent('(+0.0%)');
  });

  it('renders "(new)" when baseline is 0', () => {
    render(<MetricDelta baseline={0} achieved={0.5} />);
    expect(screen.getByText('0.500')).toBeInTheDocument();
    expect(screen.getByText('(new)')).toBeInTheDocument();
  });

  it('renders "(new)" when baseline is null', () => {
    render(<MetricDelta baseline={null} achieved={0.5} />);
    expect(screen.getByText('(new)')).toBeInTheDocument();
  });

  it('renders "—" when achieved is missing', () => {
    render(<MetricDelta baseline={0.5} achieved={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('respects custom precision', () => {
    render(<MetricDelta baseline={0.612} achieved={0.762} precision={2} />);
    expect(screen.getByText('0.61 → 0.76')).toBeInTheDocument();
  });
});
