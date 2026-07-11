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
// Capability-shaped, not entity-named: a fresh (or non-demo) install has no
// "prod-es" cluster or "trial 47", so entity-named chips would send the agent
// after things that don't exist. These describe what the agent can do and let
// it resolve the user's actual data.
const EXAMPLE_PROMPTS: readonly string[] = [
  'Summarize one of my clusters',
  'Run a study to optimize NDCG@10',
  'Explain why a trial was pruned',
  'Open a PR for my latest proposal',
  'Generate judgments for one of my query sets',
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
