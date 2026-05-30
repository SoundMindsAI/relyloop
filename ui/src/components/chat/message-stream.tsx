// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useRef } from 'react';

import { ToolCallCard } from '@/components/chat/tool-call-card';
import { ToolResultCard } from '@/components/chat/tool-result-card';
import { Card } from '@/components/ui/card';
import type { MessageWire, ToolCallJson } from '@/lib/api/conversations';
import type { MessageRole } from '@/lib/enums';

export interface MessageStreamProps {
  messages: ReactiveMessage[];
}

/**
 * UI shape for a streamed message — extends the persisted MessageWire with
 * an `inflight` flag for assistant bubbles that are still being streamed.
 */
export interface ReactiveMessage {
  id: string;
  role: MessageRole;
  content: Record<string, unknown>;
  tool_calls?: ToolCallJson[] | null;
  inflight?: boolean;
}

export function MessageStream({ messages }: MessageStreamProps) {
  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  return (
    <div className="flex flex-col gap-3" data-testid="message-stream">
      {messages.map((m) => (
        <MessageRow key={m.id} message={m} />
      ))}
      <div ref={endRef} />
    </div>
  );
}

function MessageRow({ message }: { message: ReactiveMessage }) {
  if (message.role === 'tool') {
    const tcId =
      (Array.isArray(message.tool_calls) && message.tool_calls[0]?.id) || String(message.id);
    const content = message.content || {};
    if ('error' in content) {
      return (
        <ToolResultCard
          id={String(tcId)}
          name={String(content.name ?? 'tool')}
          error={String(content.error)}
          detail={typeof content.message === 'string' ? content.message : undefined}
        />
      );
    }
    return (
      <ToolResultCard
        id={String(tcId)}
        name={String(content.name ?? 'tool')}
        result={'result' in content ? content.result : content}
      />
    );
  }

  // assistant / user bubbles
  const text = typeof message.content?.text === 'string' ? message.content.text : '';
  const isUser = message.role === 'user';
  return (
    <div className={isUser ? 'flex justify-end' : 'flex justify-start'}>
      <Card
        className={`max-w-2xl whitespace-pre-wrap p-3 text-sm ${
          isUser ? 'border-blue-200 bg-blue-50/40' : 'border-gray-200 bg-white'
        }`}
        data-testid={`message-bubble-${message.role}`}
      >
        {text}
        {message.role === 'assistant' &&
          Array.isArray(message.tool_calls) &&
          message.tool_calls.length > 0 && (
            <div className="mt-2 flex flex-col gap-2">
              {message.tool_calls.map((tc, i) => (
                <ToolCallCard
                  key={tc.id ?? String(i)}
                  id={String(tc.id ?? i)}
                  name={String(tc.name ?? 'tool')}
                  arguments={parseArgs(tc.arguments)}
                />
              ))}
            </div>
          )}
      </Card>
    </div>
  );
}

function parseArgs(raw: unknown): Record<string, unknown> {
  if (raw == null) return {};
  if (typeof raw === 'object') return raw as Record<string, unknown>;
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return { _raw: raw };
    }
  }
  return {};
}
