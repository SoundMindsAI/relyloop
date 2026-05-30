// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<RowCategorical>` — categorical chip input (Story 2.3, FR-5).
 *
 * Enter or comma commits the current draft as a chip. × on a chip
 * removes it. Type coercion:
 *   "true"/"false" → boolean
 *   /^-?\d+(\.\d+)?$/ → number
 *   else → string
 *
 * **No auto-deduplication** per FR-5: Pydantic `CategoricalParam.choices`
 * only enforces `min_length=1`, not uniqueness. A textarea-supplied
 * `{"choices": ["AUTO", "AUTO"]}` is wire-valid and the round-trip
 * invariant (§4) requires preserving duplicates. The builder MAY render
 * an amber UI-only warning on duplicate adds but MUST NOT auto-remove.
 */

import * as React from 'react';

import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';

type Choice = string | number | boolean;

export interface RowCategoricalProps {
  paramName: string;
  choices: Choice[];
  onChange: (next: Choice[]) => void;
}

function coerce(raw: string): Choice {
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  // Use Number()/isNaN to accept the same numeric formats JSON.parse does
  // (decimals, scientific notation, leading-dot, negative). Guard against
  // empty string because Number('') is 0, not NaN.
  if (raw !== '' && !Number.isNaN(Number(raw))) return Number(raw);
  return raw;
}

function isDuplicate(choices: readonly Choice[], value: Choice): boolean {
  return choices.some((c) => typeof c === typeof value && c === value);
}

function displayValue(value: Choice): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function RowCategorical({
  paramName,
  choices,
  onChange,
}: RowCategoricalProps): React.ReactElement {
  const [draft, setDraft] = React.useState('');
  const [duplicateWarning, setDuplicateWarning] = React.useState<string | null>(null);

  function commit(): void {
    const raw = draft.trim();
    if (raw === '') return;
    const value = coerce(raw);
    if (isDuplicate(choices, value)) {
      setDuplicateWarning(
        `Duplicate value '${displayValue(value)}' — Optuna will treat them as one trial`,
      );
      // STILL push the duplicate per FR-5 (no auto-dedup); warning only.
    } else {
      setDuplicateWarning(null);
    }
    onChange([...choices, value]);
    setDraft('');
  }

  function removeAt(idx: number): void {
    onChange(choices.filter((_, i) => i !== idx));
    setDuplicateWarning(null);
  }

  const choicesEmpty = choices.length === 0;

  return (
    <div className="space-y-2" data-testid={`cs-row-${paramName}-choices`}>
      <div className="flex flex-wrap gap-1.5">
        {choices.map((c, idx) => (
          <Badge
            key={`${idx}-${typeof c}-${String(c)}`}
            variant="secondary"
            className="gap-1"
            data-testid={`cs-row-${paramName}-chip-${idx}`}
          >
            <span className="font-mono text-xs">{displayValue(c)}</span>
            <button
              type="button"
              onClick={() => removeAt(idx)}
              aria-label={`Remove choice ${displayValue(c)}`}
              className="text-muted-foreground hover:text-foreground"
            >
              ×
            </button>
          </Badge>
        ))}
      </div>
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            commit();
          }
        }}
        data-testid={`cs-row-${paramName}-choices-input`}
        placeholder="Type a value and press Enter…"
      />
      {choicesEmpty && (
        <p
          role="alert"
          aria-live="polite"
          className="text-sm text-destructive"
          data-testid={`cs-row-error-${paramName}-choices`}
        >
          choices: at least 1 choice required
        </p>
      )}
      {duplicateWarning !== null && (
        <p
          className="text-sm text-amber-700 dark:text-amber-400"
          data-testid={`cs-row-${paramName}-duplicate-warning`}
        >
          {duplicateWarning}
        </p>
      )}
    </div>
  );
}
