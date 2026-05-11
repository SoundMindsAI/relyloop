import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { OverridePopover } from '@/components/judgments/override-popover';
import type { JudgmentRow } from '@/lib/api/judgments';

const API_BASE = 'http://api.test';

function makeJudgment(overrides: Partial<JudgmentRow> = {}): JudgmentRow {
  return {
    id: 'j-1',
    judgment_list_id: 'list-1',
    query_id: 'q1',
    doc_id: 'd1',
    rating: 3,
    source: 'llm',
    rater_ref: null,
    confidence: 0.8,
    notes: null,
    created_at: '2026-05-12T00:00:00Z',
    ...overrides,
  };
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe('OverridePopover', () => {
  it('PATCH /judgments and emits a success toast on save', async () => {
    let captured: { url: string; body: unknown } = { url: '', body: null };
    server.use(
      http.patch(`${API_BASE}/api/v1/judgment-lists/list-1/judgments/j-1`, async ({ request }) => {
        captured = { url: request.url, body: await request.json() };
        return HttpResponse.json(makeJudgment({ rating: 0, source: 'human', notes: 'wrong' }));
      }),
    );

    wrap(<OverridePopover listId="list-1" judgment={makeJudgment()} />);

    fireEvent.click(screen.getByTestId('override-trigger-j-1'));
    await waitFor(() => expect(screen.getByTestId('override-save')).toBeInTheDocument());

    // Update the notes textarea and submit (default rating retained from selectedJudgment).
    const notes = screen.getByTestId('override-notes') as HTMLTextAreaElement;
    fireEvent.change(notes, { target: { value: 'wrong' } });
    fireEvent.click(screen.getByTestId('override-save'));

    await waitFor(() => expect(captured.body).not.toBeNull());
    expect(captured.url).toContain('/api/v1/judgment-lists/list-1/judgments/j-1');
    expect(captured.body).toMatchObject({ rating: 3, notes: 'wrong' });
  });
});
