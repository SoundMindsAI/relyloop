/**
 * `<ParamRow>` — single row in `<SearchSpaceBuilder>` (Story 1.2).
 *
 * Story 1.2 surface: read-only rendering of the row name + simple-form
 * badge + tooltip slots (`.param_spec` / `.log` / `.cardinality`). Type
 * selector, low/high inputs, log toggle, choices chip input, and
 * per-row cardinality counter arrive as swap-in controls in Stories 2.1–2.3.
 *
 * Row identity comes from `templateBody.declared_params` keys per FR-1;
 * the parent wires `spec` from the parsed-JSON params dict, passing
 * `undefined` for declared keys absent from the JSON (renders as
 * "empty/unset").
 */

import * as React from 'react';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Label } from '@/components/ui/label';

import type { ParamSpec } from './types';

export interface ParamRowProps {
  paramName: string;
  /** Simple-form type-name from `templateBody.declared_params[paramName]`. */
  declaredType: string;
  /**
   * Current spec for this row from the parsed-JSON params dict, or
   * `undefined` if the row is empty/unset (declared but not in JSON).
   */
  spec: ParamSpec | undefined;
}

export function ParamRow({ paramName, declaredType, spec }: ParamRowProps): React.ReactElement {
  return (
    <div
      data-testid={`cs-param-row-${paramName}`}
      className="rounded-md border border-border bg-card p-3 space-y-2"
    >
      {/* Name chip + simple-form badge */}
      <div className="flex items-center gap-2">
        <span
          className="font-mono text-xs px-1.5 py-0.5 rounded border border-border bg-background"
          data-testid={`cs-param-row-${paramName}-name`}
        >
          {paramName}
        </span>
        <span
          className="text-xs text-muted-foreground"
          data-testid={`cs-param-row-${paramName}-simpleform`}
        >
          {declaredType}
        </span>
      </div>

      {/* Type row: label + glossary tooltip + read-only type display.
          Story 2.1 swaps the read-only display for an editable <Select>. */}
      <div className="space-y-1">
        <div className="flex items-center gap-1">
          <Label htmlFor={`cs-row-${paramName}-type`}>Type</Label>
          <InfoTooltip glossaryKey="study.search_space.param_spec" />
        </div>
        <span
          id={`cs-row-${paramName}-type`}
          data-testid={`cs-row-${paramName}-type-display`}
          className="text-sm font-mono"
        >
          {spec?.type ?? 'unset'}
        </span>
      </div>

      {/* Log row: only rendered for float (Story 2.2 makes interactive).
          Glossary slot reserved here for FR-11 even when spec is unset. */}
      {(spec?.type === 'float' || (spec === undefined && declaredType === 'float')) && (
        <div className="space-y-1">
          <div className="flex items-center gap-1">
            <Label>Log scale</Label>
            <InfoTooltip glossaryKey="study.search_space.log" />
          </div>
          <span
            data-testid={`cs-row-${paramName}-log-display`}
            className="text-xs text-muted-foreground"
          >
            {spec?.type === 'float' ? (spec.log ? 'true' : 'false') : 'unset'}
          </span>
        </div>
      )}

      {/* Cardinality row: per-row counter slot. Story 2.3 swaps in the live
          `estimateParamCardinality(spec)` value. */}
      <div className="space-y-1">
        <div className="flex items-center gap-1">
          <Label>Cardinality</Label>
          <InfoTooltip glossaryKey="study.search_space.cardinality" />
        </div>
        <span
          data-testid={`cs-row-${paramName}-cardinality`}
          className="text-xs text-muted-foreground"
        >
          —
        </span>
      </div>
    </div>
  );
}
