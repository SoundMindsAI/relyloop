// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import { Composer } from '@/components/chat/composer';
import { ExamplePrompts } from '@/components/chat/example-prompts';
import { MessageStream, type ReactiveMessage } from '@/components/chat/message-stream';
import { Alert } from '@/components/ui/alert';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  type MessageWire,
  type SseEvent,
  streamChatMessage,
  useConversation,
} from '@/lib/api/conversations';
import { isApiError, toToastMessage } from '@/lib/api-errors';
import { useQueryClient } from '@tanstack/react-query';

const SECRETS_WARNING_KEY = 'chat-secrets-warning-dismissed';

function ChatDetailInner({ id }: { id: string }) {
  const conversation = useConversation(id);
  const qc = useQueryClient();
  const [overlayMessages, setOverlayMessages] = useState<ReactiveMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [warningDismissed, setWarningDismissed] = useState(() => {
    if (typeof window === 'undefined') return false;
    return sessionStorage.getItem(SECRETS_WARNING_KEY) === '1';
  });
  const abortRef = useRef<AbortController | null>(null);

  const serverMessages: ReactiveMessage[] = useMemo(
    () => (conversation.data?.messages ?? []).map(toReactive),
    [conversation.data?.messages],
  );

  // The displayed list is server messages followed by the live overlay
  // (optimistic user message + streamed assistant tokens + tool cards).
  // The overlay is cleared synchronously inside handleSend's finally block
  // before the refetch lands — that avoids the React 19
  // react-hooks/set-state-in-effect rule, which flags overlay-clearing in
  // useEffect as a cascading-render smell.
  const localMessages: ReactiveMessage[] = useMemo(
    () => [...serverMessages, ...overlayMessages],
    [serverMessages, overlayMessages],
  );

  const setLocalMessages = (updater: (prev: ReactiveMessage[]) => ReactiveMessage[]) => {
    setOverlayMessages((prev) => {
      const combined = [...serverMessages, ...prev];
      const next = updater(combined);
      const serverSet = new Set(serverMessages.map((m) => m.id));
      return next.filter((m) => !serverSet.has(m.id));
    });
  };

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const handleSend = async (userText: string) => {
    if (streaming) return;
    setStreamError(null);
    const abort = new AbortController();
    abortRef.current = abort;
    setStreaming(true);

    // Optimistically append the user message.
    const optimisticId = `optimistic-user-${Date.now()}`;
    setLocalMessages((prev) => [
      ...prev,
      { id: optimisticId, role: 'user', content: { text: userText } },
    ]);

    // Assistant bubble we'll append tokens into.
    const assistantId = `optimistic-assistant-${Date.now()}`;
    let assistantStarted = false;

    const onEvent = (event: SseEvent) => {
      if (event.type === 'token') {
        setLocalMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === assistantId);
          if (idx === -1) {
            assistantStarted = true;
            return [
              ...prev,
              {
                id: assistantId,
                role: 'assistant',
                content: { text: event.data.text },
                inflight: true,
              },
            ];
          }
          const next = [...prev];
          const existing = next[idx]!;
          const existingText = (existing.content as { text?: string }).text ?? '';
          next[idx] = {
            ...existing,
            content: { text: existingText + event.data.text },
          };
          return next;
        });
        return;
      }
      if (event.type === 'tool_call') {
        setLocalMessages((prev) => [
          ...prev,
          {
            id: `tc-${event.data.id}`,
            role: 'assistant',
            content: { text: '' },
            tool_calls: [
              {
                id: event.data.id,
                name: event.data.name,
                arguments: JSON.stringify(event.data.arguments),
              },
            ],
          },
        ]);
        return;
      }
      if (event.type === 'tool_result') {
        setLocalMessages((prev) => [
          ...prev,
          {
            id: `tr-${event.data.id}`,
            role: 'tool',
            content: {
              name: event.data.name,
              ...(event.data.error
                ? { error: event.data.error, message: event.data.detail }
                : { result: event.data.result }),
            },
            tool_calls: [{ id: event.data.id }],
          },
        ]);
        return;
      }
      if (event.type === 'done') {
        if (event.data.error) {
          setStreamError(event.data.error);
        }
      }
    };

    try {
      await streamChatMessage(id, userText, { signal: abort.signal, onEvent });
    } catch (err) {
      if (abort.signal.aborted) return;
      setStreamError(err instanceof Error ? err.message : 'Stream failed');
      if (isApiError(err)) {
        toast.error(toToastMessage(err));
      }
    } finally {
      void assistantStarted; // placate eslint if unused
      setStreaming(false);
      abortRef.current = null;
      // Clear the live overlay before kicking off the refetch — the canonical
      // persisted rows from the server replace what we showed locally.
      setOverlayMessages([]);
      qc.invalidateQueries({ queryKey: ['conversation', id] });
    }
  };

  const dismissWarning = () => {
    setWarningDismissed(true);
    if (typeof window !== 'undefined') {
      sessionStorage.setItem(SECRETS_WARNING_KEY, '1');
    }
  };

  const title = useMemo(() => {
    if (conversation.data?.title) return conversation.data.title;
    if (conversation.data) return 'Untitled';
    return 'Loading…';
  }, [conversation.data]);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
      <div className="flex items-center justify-between text-sm">
        <Link href="/chat" className="text-blue-600 hover:underline">
          ← Chats
        </Link>
        {streaming && (
          <span className="text-xs text-muted-foreground" role="status" aria-live="polite">
            Streaming…
          </span>
        )}
      </div>

      {!warningDismissed && (
        <Alert
          variant="warning"
          className="flex items-start justify-between gap-3"
          data-testid="secrets-warning"
        >
          <span>
            ⚠ Don&apos;t paste API keys, GitHub tokens, or other credentials in chat — your messages
            are persisted and re-sent to the LLM each turn. Use the secrets folder for credentials.
          </span>
          <button
            type="button"
            onClick={dismissWarning}
            className="text-xs underline"
            data-testid="dismiss-secrets-warning"
          >
            Dismiss
          </button>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {conversation.isError ? (
            <p className="text-sm text-destructive">
              Failed to load conversation: {conversation.error.message}
            </p>
          ) : (
            <MessageStream messages={localMessages} />
          )}
          {streamError && (
            <Alert variant="destructive" data-testid="stream-error">
              {streamError}
            </Alert>
          )}
        </CardContent>
      </Card>

      {localMessages.length === 0 && !streaming && (
        <ExamplePrompts onSend={handleSend} disabled={streaming} />
      )}
      <Composer onSend={handleSend} streaming={streaming} />
    </main>
  );
}

function toReactive(m: MessageWire): ReactiveMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    tool_calls: m.tool_calls,
  };
}

export default function ChatDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? '';
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      {id && <ChatDetailInner id={id} />}
    </Suspense>
  );
}
