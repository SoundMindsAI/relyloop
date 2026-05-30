'use client';

/**
 * Small chip rendered next to demo-named cluster rows.
 *
 * Two variants:
 *
 * - `"default"` ("Demo") — feat_home_first_run_demo_nudge FR-4 + FR-5.
 *   Used by clusters-table only — the create-study modal and proposals
 *   fk-select dropdown render `(Demo)` as a text suffix instead, because
 *   shadcn `<SelectItem>` and native `<select>` don't accept JSX badges
 *   usefully.
 *
 * - `"synthetic-ubi"` ("Synthetic demo data") —
 *   feat_demo_ubi_study_comparison Story 3.2 / FR-7. Rendered on the
 *   five surfaces where the operator would otherwise be unable to
 *   distinguish synthetic demo UBI from real user behavior (cluster
 *   detail near `<UbiRungBadge>`, UBI judgment-list header, UBI study
 *   header, and next to method-picker UBI options on the demo cluster).
 *   Always gated on `isDemoSyntheticUbiClusterName(...)` at the call
 *   site; never appears on production clusters or on
 *   `news-search-staging` (rung_0 demo).
 */

import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

const TOOLTIP_TEXT =
  "Pre-loaded by 'make up' or 'make seed-demo'. Has realistic queries + judgments + a winning study. Safe to delete with 'make seed-demo FORCE=1' to start over.";

// Source-of-truth: ui/src/lib/glossary.ts `ubi_synthetic_demo_data`.
// Kept inline (not imported from glossary at runtime) so the badge can
// render without a hook; the glossary test asserts the two stay aligned.
const SYNTHETIC_UBI_TOOLTIP =
  'This UBI data was fabricated by the demo reseed to demonstrate the UBI path; it is not real user behavior.';

export type DemoBadgeVariant = 'default' | 'synthetic-ubi';

interface DemoBadgeProps {
  variant?: DemoBadgeVariant;
}

export function DemoBadge({ variant = 'default' }: DemoBadgeProps = {}): React.ReactElement {
  if (variant === 'synthetic-ubi') {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant="secondary"
            role="img"
            aria-label="Synthetic demo data"
            tabIndex={0}
            data-testid="demo-badge-synthetic-ubi"
            className="ml-2 cursor-help focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
          >
            Synthetic demo data
          </Badge>
        </TooltipTrigger>
        <TooltipContent side="top">{SYNTHETIC_UBI_TOOLTIP}</TooltipContent>
      </Tooltip>
    );
  }
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
