// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Button } from '@/components/ui/button';

/**
 * Example prompts shown on an empty conversation (no prior messages) to help
 * a brand-new user understand what the agent can do. Click a chip and it
 * fires `onSend` exactly as if the user had typed + Cmd+Enter.
 *
 * Per Phase 3 of feat_contextual_help_mvp2 — these are UI content, not help
 * copy, so they live in this component rather than `ui/src/lib/glossary.ts`
 * (glossary is reserved for tooltip / popover help text).
 */
const EXAMPLE_PROMPTS: readonly string[] = [
  'Tell me about the prod-es cluster',
  'Run a study optimizing NDCG@10 for the product-search index',
  'Why did trial 47 get pruned?',
  'Open a PR for the latest proposal',
  'Generate judgments for the e-commerce query set',
];

export interface ExamplePromptsProps {
  onSend: (text: string) => void | Promise<void>;
  disabled?: boolean;
}

export function ExamplePrompts({ onSend, disabled }: ExamplePromptsProps) {
  return (
    <div
      className="rounded-md border border-dashed border-muted-foreground/30 p-4"
      data-testid="chat-example-prompts"
    >
      <p className="mb-3 text-sm text-muted-foreground">
        New here? Try one of these to get started:
      </p>
      <div className="flex flex-wrap gap-2">
        {EXAMPLE_PROMPTS.map((prompt, i) => (
          <Button
            key={`example-prompt-${i}`}
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => void onSend(prompt)}
            data-testid={`example-prompt-${i}`}
            className="text-left"
          >
            {prompt}
          </Button>
        ))}
      </div>
    </div>
  );
}
