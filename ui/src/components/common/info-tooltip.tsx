// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { Info } from 'lucide-react';
import * as React from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { glossary, type ShortGlossaryKey } from '@/lib/glossary';

type InfoTooltipProps =
  | { glossaryKey: ShortGlossaryKey; asChild?: false; learnMoreHref?: string }
  | {
      glossaryKey: ShortGlossaryKey;
      asChild: true;
      children: React.ReactNode;
      learnMoreHref?: string;
    };

/**
 * Renders a label-adjacent help affordance backed by an entry in the shared
 * `glossary` source-of-truth file.
 *
 * Two modes (chosen automatically by the presence of `learnMoreHref`):
 *
 *  1. **Tooltip mode (default)** — when `learnMoreHref` is absent. Used for
 *     21 of 23 Phase 1 placements: hover/keyboard-focus opens a Radix
 *     `Tooltip`, dismisses on ESC / blur / mouseout. The tooltip body is
 *     non-interactive (the standard Radix tooltip pattern intentionally
 *     prevents focus from entering its content).
 *
 *  2. **Popover mode** — when `learnMoreHref` is present. Switches to a
 *     Radix `Popover` so the contained interactive "Learn more" link is
 *     keyboard-focusable (Gemini Code Assist a11y finding on PR #416 —
 *     accepted). Opens on click / Enter / Space, dismisses on click-
 *     outside / ESC. Same trigger icon + dimensions as Tooltip mode so
 *     placement next to labels is visually consistent.
 *
 * `asChild` is supported only in Tooltip mode (the 2 existing asChild
 * callers are read-only text triggers — none of them need `learnMoreHref`).
 *
 * The `glossaryKey` prop is typed as `ShortGlossaryKey`, which narrows to
 * glossary entries that include a `short` field — so a long-only entry
 * cannot be passed at compile time.
 *
 * Optional `learnMoreHref` prop (`chore_template_library_expansion` FR-7):
 * the caller supplies the href because the glossary entry is engine-
 * agnostic while the cheatsheet URL depends on context (e.g. the modal
 * call site reads `selectedCluster.engine_type` and resolves the right
 * cheatsheet via `cheatsheetUrlFor`).
 */
export function InfoTooltip(props: InfoTooltipProps): React.ReactElement | null {
  const entry = glossary[props.glossaryKey];
  // Belt-and-braces: type narrowing makes both checks unreachable at compile
  // time, but guard against runtime bad keys (e.g., a downstream caller using
  // `as never` to bypass the type).
  if (!entry || !('short' in entry)) return null;
  const ariaLabel =
    'ariaLabel' in entry && entry.ariaLabel !== undefined ? entry.ariaLabel : 'More information';
  const bodyTestId = `tooltip-body-${props.glossaryKey}`;
  const learnMoreHref = props.learnMoreHref;

  // Popover mode — when learnMoreHref is set, switch to a focus-trapping
  // Popover so keyboard users can reach the link. asChild is intentionally
  // ignored here (no caller combines asChild + learnMoreHref today).
  if (learnMoreHref) {
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={ariaLabel}
            data-testid={`tooltip-trigger-${props.glossaryKey}`}
            className="inline-flex h-6 w-6 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </PopoverTrigger>
        <PopoverContent data-testid={bodyTestId} className="text-sm">
          <span>{entry.short}</span>{' '}
          <a
            href={learnMoreHref}
            target="_blank"
            rel="noreferrer noopener"
            data-testid={`tooltip-learn-more-${props.glossaryKey}`}
            className="underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Learn more
          </a>
        </PopoverContent>
      </Popover>
    );
  }

  // Tooltip mode (default) — non-interactive content, hover/focus only.
  return (
    <Tooltip>
      {props.asChild ? (
        <TooltipTrigger asChild>{props.children}</TooltipTrigger>
      ) : (
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={ariaLabel}
            data-testid={`tooltip-trigger-${props.glossaryKey}`}
            className="inline-flex h-6 w-6 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </TooltipTrigger>
      )}
      <TooltipContent data-testid={bodyTestId}>{entry.short}</TooltipContent>
    </Tooltip>
  );
}
