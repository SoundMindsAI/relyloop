import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// Recharts ResponsiveContainer requires layout/measurement that jsdom doesn't
// provide. Stub it to a simple <div> wrapper so children render at a fixed size.
vi.mock('recharts', async () => {
  const actual: typeof import('recharts') = await vi.importActual('recharts');
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container" style={{ width: 800, height: 240 }}>
        {children}
      </div>
    ),
  };
});

const { ParameterImportanceChart } = await import('@/components/common/parameter-importance-chart');

describe('ParameterImportanceChart', () => {
  it('renders the chart container with the provided data', () => {
    render(<ParameterImportanceChart data={{ slop: 0.32, boost: 0.71, fuzziness: 0.05 }} />);
    expect(screen.getByTestId('parameter-importance-chart')).toBeInTheDocument();
    // jsdom doesn't lay out SVG, so we can't assert pixel-rendered bars.
    // Verify the data path is alive by asserting the chart wrapper rendered.
    expect(screen.queryByTestId('param-chart-empty')).toBeNull();
  });

  it('renders empty state when data is empty', () => {
    render(<ParameterImportanceChart data={{}} />);
    expect(screen.getByTestId('param-chart-empty')).toBeInTheDocument();
  });
});
