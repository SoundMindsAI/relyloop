'use client';

import { useState } from 'react';

import { Card } from '@/components/ui/card';

export interface ToolCallCardProps {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export function ToolCallCard({ id, name, arguments: args }: ToolCallCardProps) {
  const [open, setOpen] = useState(false);
  return (
    <Card className="border-blue-200 bg-blue-50/40 p-3" data-testid="tool-call-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left text-sm font-medium"
        data-testid="tool-call-card-header"
      >
        <span>
          Tool call · <code className="font-mono">{name}</code>
        </span>
        <span className="text-xs text-muted-foreground">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <pre
          className="mt-2 max-h-48 overflow-auto rounded bg-white p-2 text-xs"
          data-testid="tool-call-card-body"
        >
          {JSON.stringify(args, null, 2)}
        </pre>
      )}
      <span className="sr-only">{id}</span>
    </Card>
  );
}
