// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<RowNumeric>` — paired `low` / `high` numeric inputs (Story 2.1, FR-3).
 *
 * No local debounce. Calls parent `onChange` synchronously on every
 * keystroke; calls `onBlurFlush` on blur. The parent `<SearchSpaceBuilder>`
 * owns the single 200ms debounce boundary per FR-3.
 *
 * Row error (`low >= high` for float, `low > high` for int) renders
 * inline beneath the inputs.
 */

import * as React from 'react';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface RowNumericProps {
  paramName: string;
  paramType: 'float' | 'int';
  low: number | undefined;
  high: number | undefined;
  onChange: (next: { low: number | undefined; high: number | undefined }) => void;
  onBlurFlush: () => void;
}

export function RowNumeric({
  paramName,
  paramType,
  low,
  high,
  onChange,
  onBlurFlush,
}: RowNumericProps): React.ReactElement {
  const step = paramType === 'int' ? '1' : 'any';

  function parseNumber(raw: string): number | undefined {
    if (raw === '') return undefined;
    const n = Number(raw);
    return Number.isNaN(n) ? undefined : n;
  }

  const rowError = computeRowError(paramType, low, high);

  return (
    <>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor={`cs-row-${paramName}-low`}>Low</Label>
          <Input
            id={`cs-row-${paramName}-low`}
            data-testid={`cs-row-${paramName}-low`}
            type="number"
            step={step}
            value={low ?? ''}
            onChange={(e) => onChange({ low: parseNumber(e.target.value), high })}
            onBlur={onBlurFlush}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`cs-row-${paramName}-high`}>High</Label>
          <Input
            id={`cs-row-${paramName}-high`}
            data-testid={`cs-row-${paramName}-high`}
            type="number"
            step={step}
            value={high ?? ''}
            onChange={(e) => onChange({ low, high: parseNumber(e.target.value) })}
            onBlur={onBlurFlush}
          />
        </div>
      </div>
      {rowError !== null && (
        <p
          role="alert"
          aria-live="polite"
          className="text-sm text-destructive"
          data-testid={`cs-row-error-${paramName}`}
        >
          {rowError}
        </p>
      )}
    </>
  );
}

function computeRowError(
  paramType: 'float' | 'int',
  low: number | undefined,
  high: number | undefined,
): string | null {
  if (low === undefined || high === undefined) return null;
  if (paramType === 'float') {
    return low >= high ? 'low must be < high' : null;
  }
  return low > high ? 'low must be ≤ high' : null;
}
