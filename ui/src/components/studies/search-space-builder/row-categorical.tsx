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

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { NORMALIZER_GLOSSARY_KEYS, NORMALIZER_VALUES, type NormalizerValue } from '@/lib/enums';
import { glossary } from '@/lib/glossary';

type Choice = string | number | boolean;

/** Reserved non-render param consumed by the adapter (FR-2). Its create-study
 * row is a constrained <Select>, not the free-form chip input. */
const QUERY_NORMALIZER = 'query_normalizer';

export interface RowCategoricalProps {
  paramName: string;
  choices: Choice[];
  onChange: (next: Choice[]) => void;
}

function isNormalizerValue(c: Choice): c is NormalizerValue {
  return typeof c === 'string' && (NORMALIZER_VALUES as readonly string[]).includes(c);
}

/**
 * Constrained select for the reserved `query_normalizer` param (FR-7).
 *
 * The option universe is bounded by NORMALIZER_VALUES, but the *selectable*
 * set is the operator-declared `choices` subset. A single pick replaces the
 * param's choices with `[value]` (single-select reserved key). Stray choices
 * (not in NORMALIZER_VALUES — defense-in-depth; FR-2 enforces this
 * server-side) are filtered out with a console warning.
 */
function NormalizerSelect({
  choices,
  onChange,
}: {
  choices: Choice[];
  onChange: (next: Choice[]) => void;
}): React.ReactElement {
  // Values must match backend/app/domain/study/normalizers.py NORMALIZER_CHOICES
  // (via the NORMALIZER_VALUES re-export in @/lib/enums).
  const validChoices = choices.filter(isNormalizerValue);
  if (validChoices.length !== choices.length) {
    console.warn(
      `query_normalizer: ignoring choices outside NORMALIZER_VALUES: ${JSON.stringify(
        choices.filter((c) => !isNormalizerValue(c)),
      )}`,
    );
  }
  const current = validChoices.length === 1 ? validChoices[0] : undefined;
  return (
    <div className="space-y-2" data-testid={`cs-row-${QUERY_NORMALIZER}-choices`}>
      <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
        Query normalizer
        <InfoTooltip glossaryKey="search_space.query_normalizer.row" />
      </p>
      <Select value={current} onValueChange={(v) => onChange([v])}>
        <SelectTrigger data-testid={`cs-row-${QUERY_NORMALIZER}-select`}>
          <SelectValue placeholder="Pick a normalizer…" />
        </SelectTrigger>
        <SelectContent>
          {validChoices.map((c) => (
            <SelectItem key={c} value={c}>
              {glossary[NORMALIZER_GLOSSARY_KEYS[c]].short}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
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
  // Dispatcher only (no hooks here, so the conditional return is rules-of-hooks
  // safe). The reserved key gets a constrained <Select>; everything else keeps
  // the free-form chip input.
  if (paramName === QUERY_NORMALIZER) {
    return <NormalizerSelect choices={choices} onChange={onChange} />;
  }
  return <ChipInputCategorical paramName={paramName} choices={choices} onChange={onChange} />;
}

function ChipInputCategorical({
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
