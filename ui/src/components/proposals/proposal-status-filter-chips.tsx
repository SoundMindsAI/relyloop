'use client';
import { Button } from '@/components/ui/button';
import { PROPOSAL_STATUS_VALUES, type ProposalStatus } from '@/lib/enums';

const ALL = 'all' as const;
const CHIP_VALUES = [ALL, ...PROPOSAL_STATUS_VALUES] as const;
type ChipValue = (typeof CHIP_VALUES)[number];

export interface ProposalStatusFilterChipsProps {
  value: string | null;
  onChange: (value: ProposalStatus | null) => void;
}

function isChipValue(v: string): v is ChipValue {
  return (CHIP_VALUES as readonly string[]).includes(v);
}

export function ProposalStatusFilterChips({ value, onChange }: ProposalStatusFilterChipsProps) {
  const active: ChipValue = value && isChipValue(value) ? value : ALL;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Status filter">
      {CHIP_VALUES.map((chip) => {
        const isActive = chip === active;
        return (
          <Button
            key={chip}
            type="button"
            variant={isActive ? 'default' : 'outline'}
            size="sm"
            data-testid={`proposal-status-chip-${chip}`}
            data-active={isActive ? 'true' : 'false'}
            onClick={() => onChange(chip === ALL ? null : (chip as ProposalStatus))}
          >
            {chip}
          </Button>
        );
      })}
    </div>
  );
}
