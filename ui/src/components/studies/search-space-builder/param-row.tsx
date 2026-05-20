/**
 * `<ParamRow>` — single row in `<SearchSpaceBuilder>`.
 *
 * Stories 1.2 + 2.1 surface: name chip + simple-form badge + editable
 * type selector + low/high spinners (float/int) + tooltip slots. Log
 * toggle arrives in Story 2.2; categorical chip-input + per-row
 * cardinality counter arrive in Story 2.3.
 *
 * Row identity comes from `templateBody.declared_params` keys per FR-1;
 * the parent wires `spec` from the parsed-JSON params dict, passing
 * `undefined` for declared keys absent from the JSON (empty/unset row).
 */

import * as React from 'react';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Label } from '@/components/ui/label';

import { RowNumeric } from './row-numeric';
import { RowTypeSelector } from './row-type-selector';
import type { ParamSpec, StashMap } from './types';

export interface ParamRowProps {
  paramName: string;
  declaredType: string;
  spec: ParamSpec | undefined;
  stashRef: React.MutableRefObject<StashMap>;
  onSpecChange: (paramName: string, next: ParamSpec) => void;
  onBlurFlush: () => void;
}

export function ParamRow({
  paramName,
  declaredType,
  spec,
  stashRef,
  onSpecChange,
  onBlurFlush,
}: ParamRowProps): React.ReactElement {
  return (
    <div
      data-testid={`cs-param-row-${paramName}`}
      className="rounded-md border border-border bg-card p-3 space-y-2"
    >
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

      <div className="space-y-1">
        <div className="flex items-center gap-1">
          <Label htmlFor={`cs-row-${paramName}-type`}>Type</Label>
          <InfoTooltip glossaryKey="study.search_space.param_spec" />
        </div>
        <RowTypeSelector
          paramName={paramName}
          spec={spec}
          stashRef={stashRef}
          onSpecChange={onSpecChange}
        />
      </div>

      {(spec?.type === 'float' || spec?.type === 'int') && (
        <RowNumeric
          paramName={paramName}
          paramType={spec.type}
          low={spec.low}
          high={spec.high}
          onChange={(next) => {
            if (spec.type === 'float') {
              onSpecChange(paramName, {
                ...spec,
                low: next.low ?? spec.low,
                high: next.high ?? spec.high,
              });
            } else {
              onSpecChange(paramName, {
                ...spec,
                low: next.low ?? spec.low,
                high: next.high ?? spec.high,
              });
            }
          }}
          onBlurFlush={onBlurFlush}
        />
      )}

      {/* Log row: rendered for float only. Editable toggle arrives in Story 2.2. */}
      {spec?.type === 'float' && (
        <div className="space-y-1">
          <div className="flex items-center gap-1">
            <Label>Log scale</Label>
            <InfoTooltip glossaryKey="study.search_space.log" />
          </div>
          <span
            data-testid={`cs-row-${paramName}-log-display`}
            className="text-xs text-muted-foreground"
          >
            {spec.log ? 'true' : 'false'}
          </span>
        </div>
      )}

      {/* Per-row cardinality slot — wired in Story 2.3. */}
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

      {/* Empty/unset row hint when spec is undefined. */}
      {spec === undefined && (
        <span
          data-testid={`cs-row-${paramName}-type-display`}
          className="text-xs text-muted-foreground"
        >
          unset
        </span>
      )}
    </div>
  );
}
