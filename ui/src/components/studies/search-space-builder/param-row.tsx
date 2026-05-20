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

import { RowLogToggle } from './row-log-toggle';
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

/**
 * Holds the per-row `attemptedInvalidLogEnable` flag for the log toggle
 * (Story 2.2). Lives in a small inner component so its `useState` is
 * scoped per row + auto-cleared when the row unmounts. The flag is
 * auto-cleared when `low > 0` via the effect below.
 */
function FloatLogControl({
  paramName,
  spec,
  onSpecChange,
}: {
  paramName: string;
  spec: ParamSpec & { type: 'float' };
  onSpecChange: (paramName: string, next: ParamSpec) => void;
}): React.ReactElement {
  const [attempted, setAttempted] = React.useState(false);

  // Derived auto-clear: when `low` becomes valid (> 0), the flag is
  // effectively false regardless of the underlying state. This avoids
  // the setState-in-effect anti-pattern.
  const lowValid = typeof spec.low === 'number' && spec.low > 0;
  const effectiveAttempted = attempted && !lowValid;

  return (
    <RowLogToggle
      paramName={paramName}
      log={spec.log === true}
      low={spec.low}
      attemptedInvalidLogEnable={effectiveAttempted}
      onAttemptedInvalidLogEnable={() => setAttempted(true)}
      onClearAttemptedInvalidLogEnable={() => setAttempted(false)}
      onChange={(nextLog) => onSpecChange(paramName, { ...spec, log: nextLog })}
    />
  );
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

      {/* Log row (Story 2.2): editable toggle for float rows only.
          Holds per-row `attemptedInvalidLogEnable` state so the row error
          fires after a refused click even when `log` stays `false`. */}
      {spec?.type === 'float' && (
        <FloatLogControl paramName={paramName} spec={spec} onSpecChange={onSpecChange} />
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
