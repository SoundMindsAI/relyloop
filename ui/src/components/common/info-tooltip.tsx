'use client';
import { Info } from 'lucide-react';
import * as React from 'react';

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { glossary, type ShortGlossaryKey } from '@/lib/glossary';

type InfoTooltipProps =
  | { glossaryKey: ShortGlossaryKey; asChild?: false }
  | { glossaryKey: ShortGlossaryKey; asChild: true; children: React.ReactNode };

/**
 * Renders a label-adjacent help affordance backed by an entry in the shared
 * `glossary` source-of-truth file.
 *
 * Two modes:
 *
 *  1. Standalone (default — 21 of 23 Phase 1 placements): renders its own
 *     `<button type="button" aria-label=...>` containing a 14×14 lucide-react
 *     `<Info />` icon inside a 24×24 hit area. The tooltip body opens on
 *     hover or keyboard focus, dismisses on ESC / blur / mouseout. Used next
 *     to non-focusable text labels (form labels, table column headers, dl
 *     labels, section labels).
 *
 *  2. asChild mode (`asChild` prop set): the caller-supplied focusable child
 *     (a `<Button>`, `<Link>`, or any element with `tabIndex={0}`) becomes
 *     the tooltip trigger via Radix `TooltipTrigger asChild`. No extra icon
 *     is rendered. In this mode the wrapper does NOT set a `data-testid` on
 *     the trigger element (a DOM node can carry only one `data-testid` and
 *     the caller's existing testid wins); the tooltip body is still tagged
 *     with `data-testid={tooltip-body-${glossaryKey}}`.
 *
 * The `glossaryKey` prop is typed as `ShortGlossaryKey`, which narrows to
 * glossary entries that include a `short` field — so a long-only entry
 * cannot be passed at compile time.
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
