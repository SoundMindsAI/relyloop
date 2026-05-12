'use client';

import { useRouter } from 'next/navigation';
import { Suspense, useState } from 'react';

import { ConversationListCard } from '@/components/chat/conversation-list';
import { CursorPaginator } from '@/components/common/cursor-paginator';
import { EmptyState } from '@/components/common/empty-state';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useConversations, useCreateConversation } from '@/lib/api/conversations';

function ChatPageInner() {
  const router = useRouter();
  const [pageSize, setPageSize] = useState(50);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursorStack[cursorStack.length - 1];

  const query = useConversations({ cursor, limit: pageSize });
  const createMut = useCreateConversation();

  const handleNew = async () => {
    const result = await createMut.mutateAsync({ title: null });
    router.push(`/chat/${result.id}`);
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Chat</h1>
        <Button onClick={handleNew} disabled={createMut.isPending} data-testid="new-conversation">
          {createMut.isPending ? 'Creating…' : 'New conversation'}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Conversations</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {query.isPending ? (
            <div className="px-4 py-8 text-sm text-muted-foreground">Loading conversations…</div>
          ) : query.isError ? (
            <EmptyState title="Backend unreachable" message={query.error.message} />
          ) : query.data.data.length === 0 ? (
            <EmptyState
              title="No conversations yet"
              message="Start a new chat to ask the agent about a cluster, run a study, or open a PR."
            />
          ) : (
            <>
              <ConversationListCard rows={query.data.data} />
              <div className="border-t px-4 py-3">
                <CursorPaginator
                  pageSize={pageSize}
                  onPageSizeChange={(n) => {
                    setPageSize(n);
                    setCursorStack([undefined]);
                  }}
                  onPrev={
                    cursorStack.length > 1 ? () => setCursorStack((s) => s.slice(0, -1)) : undefined
                  }
                  hasMore={query.data.has_more}
                  onNext={() => {
                    if (query.data.next_cursor != null) {
                      setCursorStack((s) => [...s, query.data.next_cursor as string]);
                    }
                  }}
                  totalCount={query.data.totalCount}
                />
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <ChatPageInner />
    </Suspense>
  );
}
