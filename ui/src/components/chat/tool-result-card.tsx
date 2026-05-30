// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { Card } from '@/components/ui/card';

export interface ToolResultCardProps {
  id: string;
  name: string;
  result?: unknown;
  error?: string;
  detail?: string;
}

export function ToolResultCard({ id, name, result, error, detail }: ToolResultCardProps) {
  const [open, setOpen] = useState(false);
  const isError = error != null;
  return (
    <Card
      className={`p-3 ${isError ? 'border-red-200 bg-red-50/40' : 'border-emerald-200 bg-emerald-50/40'}`}
      data-testid="tool-result-card"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left text-sm font-medium"
        data-testid="tool-result-card-header"
      >
        <span>
          Tool result · <code className="font-mono">{name}</code>
          {isError && <span className="ml-2 text-xs text-red-700">[{error}]</span>}
        </span>
        <span className="text-xs text-muted-foreground">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <pre
          className="mt-2 max-h-48 overflow-auto rounded bg-white p-2 text-xs"
          data-testid="tool-result-card-body"
        >
          {isError ? (detail ?? error) : JSON.stringify(result, null, 2)}
        </pre>
      )}
      <span className="sr-only">{id}</span>
    </Card>
  );
}
