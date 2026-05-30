// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import {
  type SseEvent,
  streamChatMessage,
  useConversations,
  useCreateConversation,
} from '@/lib/api/conversations';
import { server } from '../../setup';

const API_BASE = 'http://api.test';

function wrapper(qc?: QueryClient) {
  const client = qc ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe('useConversations', () => {
  it('returns the page with totalCount parsed from X-Total-Count', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/conversations`, () =>
        HttpResponse.json(
          {
            data: [
              {
                id: 'c1',
                title: 'first',
                created_at: '2026-05-12T00:00:00Z',
                message_count: 4,
                last_message_preview: 'most recent message text',
                last_message_at: '2026-05-12T00:05:00Z',
              },
              {
                id: 'c2',
                title: null,
                created_at: '2026-05-12T00:00:01Z',
                message_count: 0,
                last_message_preview: null,
                last_message_at: null,
              },
            ],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '2' } },
        ),
      ),
    );
    const { result } = renderHook(() => useConversations(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.totalCount).toBe(2);
    expect(result.current.data?.data).toHaveLength(2);
  });

  it('passes cursor + limit on the wire', async () => {
    let captured = '';
    server.use(
      http.get(`${API_BASE}/api/v1/conversations`, ({ request }) => {
        captured = request.url;
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
    );
    const { result } = renderHook(() => useConversations({ cursor: 'CUR', limit: 25 }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const params = new URL(captured).searchParams;
    expect(params.get('cursor')).toBe('CUR');
    expect(params.get('limit')).toBe('25');
  });
});

describe('useCreateConversation', () => {
  it('POSTs and invalidates the list query', async () => {
    let listHits = 0;
    server.use(
      http.post(`${API_BASE}/api/v1/conversations`, async ({ request }) => {
        const body = (await request.json()) as { title: string | null };
        return HttpResponse.json(
          {
            id: 'c-new',
            title: body.title,
            created_at: '2026-05-12T00:00:00Z',
            message_count: 0,
          },
          { status: 201 },
        );
      }),
      http.get(`${API_BASE}/api/v1/conversations`, () => {
        listHits += 1;
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const list = renderHook(() => useConversations(), { wrapper: wrapper(qc) });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    const initialHits = listHits;

    const create = renderHook(() => useCreateConversation(), { wrapper: wrapper(qc) });
    const created = await create.result.current.mutateAsync({ title: 'new chat' });
    expect(created.id).toBe('c-new');

    await waitFor(() => expect(listHits).toBeGreaterThan(initialHits));
  });
});

describe('streamChatMessage', () => {
  it('parses SSE framing and fires onEvent for each event', async () => {
    const sseBody =
      'event: token\ndata: {"text":"hi"}\n\n' +
      'event: tool_call\ndata: {"id":"call_1","name":"list_clusters","arguments":{}}\n\n' +
      'event: tool_result\ndata: {"id":"call_1","name":"list_clusters","result":{"clusters":[]}}\n\n' +
      'event: done\ndata: {"conversation_id":"c1","tokens_used":42,"cost_usd":0.001}\n\n';

    server.use(
      http.post(`${API_BASE}/api/v1/conversations/c1/messages`, () => {
        return new HttpResponse(sseBody, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        });
      }),
    );

    const events: SseEvent[] = [];
    await streamChatMessage('c1', 'hello', { onEvent: (e) => events.push(e) });

    const types = events.map((e) => e.type);
    expect(types).toEqual(['token', 'tool_call', 'tool_result', 'done']);
    expect((events[0] as { type: 'token'; data: { text: string } }).data.text).toBe('hi');
    expect((events[3] as { type: 'done'; data: { tokens_used?: number } }).data.tokens_used).toBe(
      42,
    );
  });

  it('throws ApiError on non-2xx response', async () => {
    server.use(
      http.post(`${API_BASE}/api/v1/conversations/c1/messages`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'OPENAI_NOT_CONFIGURED',
              message: 'no key',
              retryable: false,
            },
          },
          { status: 503 },
        ),
      ),
    );
    await expect(streamChatMessage('c1', 'hello', { onEvent: vi.fn() })).rejects.toMatchObject({
      errorCode: 'OPENAI_NOT_CONFIGURED',
      status: 503,
    });
  });
});
