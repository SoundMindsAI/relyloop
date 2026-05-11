import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { CalibrationModal } from '@/components/judgments/calibration-modal';

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe('CalibrationModal', () => {
  it('parses CSV samples, POSTs to /calibration, and renders kappa', async () => {
    let captured: unknown = null;
    server.use(
      http.post(`${API_BASE}/api/v1/judgment-lists/list-1/calibration`, async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          cohens_kappa: 0.83,
          weighted_kappa: 0.91,
          per_class: { '0': 0.7, '1': 0.8, '2': 0.85, '3': 0.95 },
          n_samples: 42,
          warning: null,
        });
      }),
    );

    wrap(<CalibrationModal open={true} onOpenChange={() => {}} listId="list-1" />);

    const ta = screen.getByTestId('cal-samples') as HTMLTextAreaElement;
    fireEvent.change(ta, {
      target: { value: 'query_id,doc_id,rating\nq1,d1,3\nq1,d2,2\nq2,d3,0' },
    });
    fireEvent.click(screen.getByTestId('cal-submit'));

    await waitFor(() => expect(screen.getByTestId('cal-result')).toBeInTheDocument());
    expect(captured).toMatchObject({
      human_samples: [
        { query_id: 'q1', doc_id: 'd1', rating: 3 },
        { query_id: 'q1', doc_id: 'd2', rating: 2 },
        { query_id: 'q2', doc_id: 'd3', rating: 0 },
      ],
    });
    expect(screen.getByTestId('cal-cohens')).toHaveTextContent('0.830');
    expect(screen.getByTestId('cal-weighted')).toHaveTextContent('0.910');
    expect(screen.getByTestId('cal-n')).toHaveTextContent('42');
  });

  it('shows a parse error when the CSV header is malformed', async () => {
    wrap(<CalibrationModal open={true} onOpenChange={() => {}} listId="list-1" />);
    const ta = screen.getByTestId('cal-samples') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'bad_header\nrow1' } });
    fireEvent.click(screen.getByTestId('cal-submit'));
    await waitFor(() => expect(screen.getByTestId('cal-parse-error')).toBeInTheDocument());
  });
});
