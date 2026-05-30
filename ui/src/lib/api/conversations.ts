// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import { ApiError } from '@/lib/api-errors';
import type { MessageRole, SseEventType } from '@/lib/enums';

// ---------------------------------------------------------------------------
// Wire types — mirror backend/app/api/v1/schemas.py (feat_chat_agent Stories 3.1 + 3.2).
//
// Maintained inline rather than via `components['schemas']` so consumers don't
// need a fresh `pnpm types:gen` after every backend bump. The contract tests
// in backend/tests/contract/test_conversations_api_contract.py guarantee the
// backend shape; this file mirrors it.
// ---------------------------------------------------------------------------

export interface MessageWire {
  id: string;
  role: MessageRole;
  content: Record<string, unknown>;
  tool_calls: ToolCallJson[] | null;
  created_at: string;
}

export interface ToolCallJson {
  id?: string;
  name?: string;
  arguments?: string;
  /** Convenience field used for tool-role rows so the FE can look up the
   * originating tool_call_id without an extra round-trip. */
  [key: string]: unknown;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  created_at: string;
  message_count: number;
  /** Most recent user/assistant message text, truncated to 120 chars at the
   * repo layer with `…` suffix when cut. Skips tool-role rows and
   * `system_notice` assistant rows. `null` for empty conversations.
   * chore_chat_last_message_preview. */
  last_message_preview: string | null;
  /** `created_at` of the same message picked for `last_message_preview`,
   * or `null` when the conversation has no qualifying messages. */
  last_message_at: string | null;
}

export interface ConversationDetail {
  id: string;
  title: string | null;
  created_at: string;
  messages: MessageWire[];
}

export interface ConversationsListResponse {
  data: ConversationSummary[];
  next_cursor: string | null;
  has_more: boolean;
}

export type ConversationsPage = ConversationsListResponse & { totalCount: number };

export interface UseConversationsFilter {
  cursor?: string | undefined;
  limit?: number | undefined;
}

export function useConversations(
  filter: UseConversationsFilter = {},
): UseQueryResult<ConversationsPage, ApiError> {
  const { cursor, limit } = filter;
  return useQuery<ConversationsPage, ApiError>({
    queryKey: ['conversations', { cursor, limit }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<ConversationsListResponse>(
        '/api/v1/conversations',
        {
          params: { cursor, limit },
        },
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

export function useConversation(id: string): UseQueryResult<ConversationDetail, ApiError> {
  return useQuery<ConversationDetail, ApiError>({
    queryKey: ['conversation', id],
    queryFn: async () => {
      const { data } = await apiClient.get<ConversationDetail>(`/api/v1/conversations/${id}`);
      return data;
    },
    enabled: Boolean(id),
  });
}

export interface CreateConversationVars {
  title?: string | null;
}

export function useCreateConversation(): UseMutationResult<
  ConversationSummary,
  ApiError,
  CreateConversationVars
> {
  const qc = useQueryClient();
  return useMutation<ConversationSummary, ApiError, CreateConversationVars>({
    mutationFn: async ({ title }) => {
      const { data } = await apiClient.post<ConversationSummary>('/api/v1/conversations', {
        title: title ?? null,
      });
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['conversations'] });
    },
  });
}

export function useDeleteConversation(): UseMutationResult<void, ApiError, string> {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: async (id) => {
      await apiClient.delete<void>(`/api/v1/conversations/${id}`);
    },
    onSettled: (_data, _err, id) => {
      qc.invalidateQueries({ queryKey: ['conversations'] });
      qc.invalidateQueries({ queryKey: ['conversation', id] });
    },
  });
}

// ---------------------------------------------------------------------------
// SSE consumer — fetch + ReadableStream pattern (POST body required, so
// EventSource doesn't fit). See docs/01_architecture/ui-architecture.md
// §"Streaming chat".
// ---------------------------------------------------------------------------

export type SseEvent =
  | { type: 'token'; data: { text: string } }
  | {
      type: 'tool_call';
      data: { id: string; name: string; arguments: Record<string, unknown> };
    }
  | {
      type: 'tool_result';
      data: {
        id: string;
        name: string;
        result?: unknown;
        error?: string;
        detail?: string;
      };
    }
  | {
      type: 'done';
      data: {
        conversation_id: string;
        tokens_used?: number;
        cost_usd?: number;
        error?: string;
      };
    };

export interface StreamChatOptions {
  signal?: AbortSignal;
  onEvent: (event: SseEvent) => void;
}

const DEFAULT_API_BASE_URL = 'http://localhost:8000';

function resolveApiBaseUrl(): string {
  if (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }
  return DEFAULT_API_BASE_URL;
}

export async function streamChatMessage(
  conversationId: string,
  userText: string,
  options: StreamChatOptions,
): Promise<void> {
  const requestId =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const response = await fetch(
    `${resolveApiBaseUrl()}/api/v1/conversations/${conversationId}/messages`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        'X-Request-ID': requestId,
      },
      body: JSON.stringify({ role: 'user', content: { text: userText } }),
      signal: options.signal,
    },
  );

  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => null)) as {
      detail?: { error_code?: string; message?: string; retryable?: boolean };
    } | null;
    throw new ApiError({
      status: response.status,
      errorCode: body?.detail?.error_code ?? 'STREAM_FAILED',
      message: body?.detail?.message ?? 'Chat stream failed',
      retryable: body?.detail?.retryable ?? false,
      requestId: response.headers.get('X-Request-ID') ?? requestId,
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const rawEvents = buffer.split('\n\n');
    buffer = rawEvents.pop() ?? '';
    for (const raw of rawEvents) {
      const parsed = parseSSEEvent(raw);
      if (parsed) options.onEvent(parsed);
    }
  }

  // Flush any trailing event (some servers don't terminate the last event
  // with \n\n).
  if (buffer.trim()) {
    const parsed = parseSSEEvent(buffer);
    if (parsed) options.onEvent(parsed);
  }
}

function parseSSEEvent(raw: string): SseEvent | null {
  const lines = raw.split('\n');
  let type: string | null = null;
  let dataStr = '';
  for (const line of lines) {
    if (line.startsWith('event: ')) type = line.slice('event: '.length);
    else if (line.startsWith('data: ')) dataStr += line.slice('data: '.length);
  }
  if (!type || !dataStr) return null;
  try {
    return {
      type: type as SseEventType,
      data: JSON.parse(dataStr),
    } as SseEvent;
  } catch {
    return null;
  }
}
