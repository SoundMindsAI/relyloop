// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<AddCustomParam>` — non-actionable affordance pointing users at the
 * template detail page to add new tunable params (Story 2.4, FR-10).
 *
 * Uses shadcn Popover (NOT Tooltip) because Popover is designed to hold
 * interactive focusable children (`<Link>` inside the content). Surface
 * opens on hover OR keyboard focus per FR-10/AC-8; controlled `open`
 * state via `onMouseEnter`/`onMouseLeave`/`onFocus`/`onBlur` to satisfy
 * the hover-OR-focus contract (Radix Popover's default is click-only).
 *
 * The button uses `aria-disabled="true"` and an `onClick` no-op, NOT the
 * native `disabled` attribute — keeps the button focusable so the
 * Popover content is keyboard-discoverable.
 *
 * Suppressed entirely when `templateId` is undefined (transient/404
 * fetch state per FR-10 + AC-11).
 */

import Link from 'next/link';
import * as React from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

export interface AddCustomParamProps {
  templateId: string;
}

export function AddCustomParam({ templateId }: AddCustomParamProps): React.ReactElement {
  const [open, setOpen] = React.useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="cs-add-custom-param"
          aria-disabled="true"
          onClick={(e) => e.preventDefault()}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={(e) => {
            if (!(e.currentTarget as HTMLElement).contains(document.activeElement)) {
              setOpen(false);
            }
          }}
          onFocus={() => setOpen(true)}
          onBlur={(e) => {
            const next = e.relatedTarget as HTMLElement | null;
            if (!next || !next.closest('[data-radix-popper-content-wrapper]')) {
              setOpen(false);
            }
          }}
          className="text-sm text-muted-foreground border border-dashed border-border rounded px-3 py-1.5 hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          + Add custom param
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="max-w-xs space-y-2"
        side="top"
        align="start"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <p className="text-sm">
          Tunable params come from the template&rsquo;s <code>declared_params</code>. To tune a new
          one, edit the template.
        </p>
        <Link
          href={`/templates/${templateId}`}
          data-testid="cs-row-add-custom-link"
          className="text-sm text-primary underline inline-block"
          onBlur={() => setOpen(false)}
        >
          Edit template
        </Link>
      </PopoverContent>
    </Popover>
  );
}
