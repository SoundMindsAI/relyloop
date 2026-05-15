'use client';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { Button } from '@/components/ui/button';

// Client-side filter only — backend has no ?source= param.
// Source is derived from proposal.study_id (non-null = study; null = manual).
// These values DO NOT belong in ui/src/lib/enums.ts (that file is the canonical
// allowlist for wire values only).
const SOURCE_VALUES = ['all', 'study', 'manual'] as const;
export type ProposalSourceFilterValue = (typeof SOURCE_VALUES)[number];

export interface ProposalSourceFilterChipsProps {
  value: ProposalSourceFilterValue;
  onChange: (value: ProposalSourceFilterValue) => void;
}

export function ProposalSourceFilterChips({ value, onChange }: ProposalSourceFilterChipsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Source filter">
      <InfoTooltip glossaryKey="proposal.source_filter" />
      {SOURCE_VALUES.map((chip) => {
        const isActive = chip === value;
        return (
          <Button
            key={chip}
            type="button"
            variant={isActive ? 'default' : 'outline'}
            size="sm"
            data-testid={`proposal-source-chip-${chip}`}
            data-active={isActive ? 'true' : 'false'}
            onClick={() => onChange(chip)}
          >
            {chip}
          </Button>
        );
      })}
    </div>
  );
}
