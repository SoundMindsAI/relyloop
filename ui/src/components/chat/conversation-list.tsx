'use client';

import Link from 'next/link';

import { Card } from '@/components/ui/card';
import type { ConversationSummary } from '@/lib/api/conversations';

export interface ConversationListProps {
  rows: ConversationSummary[];
}

function formatCount(count: number): string {
  if (count === 0) return 'Empty';
  if (count === 1) return '1 message';
  return `${count} messages`;
}

function formatRelative(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function ConversationList({ rows }: ConversationListProps) {
  return (
    <ul className="divide-y" data-testid="conversation-list">
      {rows.map((row) => (
        <li key={row.id}>
          <Link
            href={`/chat/${row.id}`}
            className="flex flex-col gap-1 px-4 py-3 hover:bg-muted/50"
            data-testid="conversation-row"
          >
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-medium">
                {row.title?.trim() ? (
                  row.title
                ) : (
                  <span className="text-muted-foreground">Untitled</span>
                )}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatRelative(row.created_at)}
              </span>
            </div>
            <span className="text-xs text-muted-foreground">{formatCount(row.message_count)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function ConversationListCard({ rows }: ConversationListProps) {
  return (
    <Card className="overflow-hidden p-0">
      <ConversationList rows={rows} />
    </Card>
  );
}
