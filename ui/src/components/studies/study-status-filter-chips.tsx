'use client';
import { Button } from '@/components/ui/button';
import { STUDY_STATUS_VALUES } from '@/lib/enums';

const ALL = 'all' as const;
const CHIP_VALUES = [ALL, ...STUDY_STATUS_VALUES] as const;
type ChipValue = (typeof CHIP_VALUES)[number];

export interface StudyStatusFilterChipsProps {
  value: string | null;
  onChange: (value: string | null) => void;
}

function isChipValue(v: string): v is ChipValue {
  return (CHIP_VALUES as readonly string[]).includes(v);
}

export function StudyStatusFilterChips({ value, onChange }: StudyStatusFilterChipsProps) {
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
            data-testid={`status-chip-${chip}`}
            data-active={isActive ? 'true' : 'false'}
            onClick={() => onChange(chip === ALL ? null : chip)}
          >
            {chip}
          </Button>
        );
      })}
    </div>
  );
}
