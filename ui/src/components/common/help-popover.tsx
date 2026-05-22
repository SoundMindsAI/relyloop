'use client';
import { Info } from 'lucide-react';
import * as React from 'react';
import ReactMarkdown from 'react-markdown';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { glossary, type LongGlossaryKey } from '@/lib/glossary';
import { MARKDOWN_DISALLOWED_ELEMENTS } from '@/lib/markdown-safety';

interface HelpPopoverProps {
  glossaryKey: LongGlossaryKey;
}

/**
 * Click-to-open contextual help affordance for explanations that don't fit
 * in a single tooltip line (multi-line guidance, side-by-side definitions,
 * interpretation rubrics).
 *
 * Renders the same 14×14 `<Info />` icon trigger as `InfoTooltip` standalone
 * mode (24×24 hit area, `aria-label` from the glossary entry, focus-visible
 * ring). Opens on click / Enter / Space, dismisses on click-outside / ESC.
 * Body is rendered through `react-markdown` with `disallowedElements`
 * filtering `<script> / <iframe> / <style>` — defense-in-depth alongside the
 * glossary content-time check.
 *
 * The `glossaryKey` prop is typed as `LongGlossaryKey`, which narrows to
 * entries that include a `long` field — a short-only entry cannot be passed
 * at compile time.
 */
export function HelpPopover({ glossaryKey }: HelpPopoverProps): React.ReactElement | null {
  const entry = glossary[glossaryKey];
  // Belt-and-braces — compile-time narrowing makes both checks unreachable.
  if (!entry || !('long' in entry)) return null;
  const ariaLabel =
    'ariaLabel' in entry && entry.ariaLabel !== undefined ? entry.ariaLabel : 'More information';
  const triggerTestId = `popover-trigger-${glossaryKey}`;
  const bodyTestId = `popover-body-${glossaryKey}`;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={ariaLabel}
          data-testid={triggerTestId}
          className="inline-flex h-6 w-6 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        data-testid={bodyTestId}
        className="prose prose-sm max-w-none motion-reduce:animate-none"
      >
        <ReactMarkdown disallowedElements={[...MARKDOWN_DISALLOWED_ELEMENTS]} unwrapDisallowed>
          {entry.long}
        </ReactMarkdown>
      </PopoverContent>
    </Popover>
  );
}
