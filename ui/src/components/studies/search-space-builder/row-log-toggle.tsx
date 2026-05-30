// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<RowLogToggle>` — log-scale checkbox for float rows (Story 2.2, FR-4).
 *
 * Native `<input type="checkbox">` with `aria-disabled` gating — NEVER
 * the native `disabled` attribute (which would block the check-off
 * transition too). The onChange handler refuses the `false → true`
 * transition when `low <= 0`; the `true → false` transition is always
 * honored. Row error renders on (a) blocked-click attempt OR (b) the
 * row's stored state is `log: true` AND `low <= 0`.
 *
 * Pattern: matches ui/src/components/common/data-table-column-visibility.tsx:61
 * (native checkbox + Popover) — no shadcn Switch primitive added.
 */

import * as React from 'react';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Label } from '@/components/ui/label';

export interface RowLogToggleProps {
  paramName: string;
  log: boolean;
  low: number | undefined;
  /** Per-row `attemptedInvalidLogEnable` flag from parent (Story 2.2). */
  attemptedInvalidLogEnable: boolean;
  onAttemptedInvalidLogEnable: () => void;
  onClearAttemptedInvalidLogEnable: () => void;
  onChange: (log: boolean) => void;
}

export function RowLogToggle({
  paramName,
  log,
  low,
  attemptedInvalidLogEnable,
  onAttemptedInvalidLogEnable,
  onClearAttemptedInvalidLogEnable,
  onChange,
}: RowLogToggleProps): React.ReactElement {
  const lowInvalid = typeof low !== 'number' || low <= 0;
  const showRowError = (log === true && lowInvalid) || attemptedInvalidLogEnable;

  function handleChange(e: React.ChangeEvent<HTMLInputElement>): void {
    const next = e.target.checked;
    if (next && lowInvalid) {
      // Refuse the false → true transition; row error surfaces via the flag.
      onAttemptedInvalidLogEnable();
      return;
    }
    // Valid transition — clear the flag and propagate.
    onClearAttemptedInvalidLogEnable();
    onChange(next);
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <input
          id={`cs-row-${paramName}-log`}
          data-testid={`cs-row-${paramName}-log`}
          type="checkbox"
          checked={log === true}
          // aria-disabled (NOT native `disabled` — native disabled would
          // block the check-off path too, contradicting spec FR-4).
          aria-disabled={lowInvalid || undefined}
          title={lowInvalid ? 'Log scale requires low > 0' : undefined}
          onChange={handleChange}
          className="h-4 w-4 rounded border-border"
        />
        <Label htmlFor={`cs-row-${paramName}-log`}>Log scale</Label>
        <InfoTooltip glossaryKey="study.search_space.log" />
      </div>
      {showRowError && (
        <p
          role="alert"
          aria-live="polite"
          className="text-sm text-destructive"
          data-testid={`cs-row-error-${paramName}-log`}
        >
          Log scale requires low &gt; 0
        </p>
      )}
    </div>
  );
}
