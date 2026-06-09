// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<RowTypeSelector>` — type discriminator selector (Story 2.1, FR-2).
 *
 * Wraps shadcn `<Select>` with the 3-option array
 * `['float', 'int', 'categorical'] as const`. Source-of-truth comment
 * directly above the array points at the backend Pydantic discriminated
 * union. The parity test at
 * `param-spec-discriminator.parity.test.tsx` reads the backend file at
 * runtime and asserts the array matches one-for-one.
 *
 * On type-switch:
 *   1. Stash the prior spec under its current type via `stashSet`.
 *   2. Look up the target type's stashed spec via `stashGet`.
 *   3. Fall back to `defaultSpecForType(nextType)` (target-type-only;
 *      never `simpleFormSpec(declaredType)` — that would return the
 *      wrong discriminator).
 */

import * as React from 'react';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

import { defaultSpecForType, stashGet, stashSet } from './stash';
import type { ParamSpec, ParamType, StashMap } from './types';

// Values must match backend/app/domain/study/search_space.py ParamSpec discriminator
// (FloatParam.type, IntParam.type, CategoricalParam.type, NormalizerPipelineParam.type
// Literal["..."]), in declaration order.
// Parity is enforced by ui/src/__tests__/components/studies/search-space-builder/
// param-spec-discriminator.parity.test.tsx (reads the backend file at runtime).
const TYPE_VALUES = ['float', 'int', 'categorical', 'normalizer_pipeline'] as const;
export type RowTypeSelectorValue = (typeof TYPE_VALUES)[number];

// Compile-time guard: any change to ParamSpec.type in
// search-space-defaults.ts that doesn't update TYPE_VALUES fails the
// builds — `RowTypeSelectorValue` must equal `ParamType` exactly.
const _typeValueParity: ParamType extends RowTypeSelectorValue
  ? RowTypeSelectorValue extends ParamType
    ? true
    : false
  : false = true;
void _typeValueParity;

export const ROW_TYPE_VALUES: readonly RowTypeSelectorValue[] = TYPE_VALUES;

export interface RowTypeSelectorProps {
  paramName: string;
  /** Current row spec (undefined when row is empty/unset). */
  spec: ParamSpec | undefined;
  /** Stash ref shared by all rows in the builder. */
  stashRef: React.MutableRefObject<StashMap>;
  /** Propagate the new spec to the builder (which schedules the write). */
  onSpecChange: (paramName: string, next: ParamSpec) => void;
}

export function RowTypeSelector({
  paramName,
  spec,
  stashRef,
  onSpecChange,
}: RowTypeSelectorProps): React.ReactElement {
  const currentType: RowTypeSelectorValue = spec?.type ?? 'float';

  function handleChange(nextStr: string): void {
    const nextType = nextStr as RowTypeSelectorValue;
    if (nextType === currentType) return;

    // (1) Stash prior spec under its current type.
    if (spec) {
      stashSet(stashRef.current, paramName, spec.type, spec);
    }

    // (2) Restore from stash for the target type, or (3) fall back to defaults.
    const stashed = stashGet(stashRef.current, paramName, nextType);
    const nextSpec = stashed ?? defaultSpecForType(nextType);

    onSpecChange(paramName, nextSpec);
  }

  return (
    <Select value={currentType} onValueChange={handleChange}>
      <SelectTrigger
        id={`cs-row-${paramName}-type`}
        data-testid={`cs-row-${paramName}-type`}
        className="w-40"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {TYPE_VALUES.map((t) => (
          <SelectItem key={t} value={t}>
            {t}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
