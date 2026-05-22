'use client';

/**
 * Small "Demo" chip rendered next to demo-named cluster rows
 * (feat_home_first_run_demo_nudge FR-4 + FR-5).
 *
 * Used by clusters-table only — the create-study modal and proposals
 * fk-select dropdown render `(Demo)` as a text suffix instead, because
 * shadcn `<SelectItem>` and native `<select>` don't accept JSX badges
 * usefully.
 */

import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

const TOOLTIP_TEXT =
  "Pre-loaded by 'make up' or 'make seed-demo'. Has realistic queries + judgments + a winning study. Safe to delete with 'make seed-demo FORCE=1' to start over.";

export function DemoBadge(): React.ReactElement {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/*
          tabIndex={0} makes the Badge keyboard-focusable so the tooltip
          is reachable via Tab navigation. role="img" + aria-label gives
          screen readers a semantically correct announcement without
          misclassifying the static visual indicator as a button.
        */}
        <Badge
          variant="secondary"
          role="img"
          aria-label="Demo cluster"
          tabIndex={0}
          data-testid="demo-badge"
          className="ml-2 cursor-help focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        >
          Demo
        </Badge>
      </TooltipTrigger>
      <TooltipContent side="top">{TOOLTIP_TEXT}</TooltipContent>
    </Tooltip>
  );
}
