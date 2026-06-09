// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<RowNormalizerPipeline>` — typed normalizer-pipeline row
 * (feat_query_normalizer_typed_pipeline FR-6).
 *
 * An ordered on/off multi-select of the six `NormalizerStep` values
 * (rendered in STEP_ORDER via `NORMALIZER_STEP_VALUES`). Toggling a step
 * updates `spec.steps`, preserving STEP_ORDER and never producing
 * duplicates (toggle, not add). The live cardinality preview is `2^N`.
 * An empty `steps` row is flagged incomplete (parallels the categorical
 * `__placeholder__` sentinel) — the backend's `min_length=1` is the
 * authoritative gate.
 *
 * Mirrors `<RowCategorical>`'s row chrome; the choice editor is replaced
 * by a step toggle list whose labels come from the glossary.
 */

import * as React from 'react';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Label } from '@/components/ui/label';
import {
  NORMALIZER_STEP_GLOSSARY_KEYS,
  NORMALIZER_STEP_VALUES,
  type NormalizerStepValue,
} from '@/lib/enums';
import { glossary } from '@/lib/glossary';

export interface RowNormalizerPipelineProps {
  paramName: string;
  steps: NormalizerStepValue[];
  onChange: (next: NormalizerStepValue[]) => void;
}

export function RowNormalizerPipeline({
  paramName,
  steps,
  onChange,
}: RowNormalizerPipelineProps): React.ReactElement {
  const selected = new Set(steps);

  function toggle(step: NormalizerStepValue, checked: boolean): void {
    const next = new Set(selected);
    if (checked) {
      next.add(step);
    } else {
      next.delete(step);
    }
    // Re-emit in STEP_ORDER so the serialized spec is deterministic and
    // duplicate-free by construction.
    onChange(NORMALIZER_STEP_VALUES.filter((s) => next.has(s)));
  }

  const isEmpty = steps.length === 0;

  return (
    <div className="space-y-2" data-testid={`cs-row-${paramName}-steps`}>
      <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
        Normalizer pipeline
        <InfoTooltip glossaryKey="search_space.normalizer_pipeline.row" />
      </p>
      <div className="space-y-1.5">
        {NORMALIZER_STEP_VALUES.map((step) => (
          <label
            key={step}
            className="flex items-center gap-2 text-sm"
            data-testid={`cs-row-${paramName}-step-${step}`}
          >
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-border accent-primary"
              checked={selected.has(step)}
              onChange={(e) => toggle(step, e.target.checked)}
              data-testid={`cs-row-${paramName}-step-${step}-checkbox`}
            />
            <span>{glossary[NORMALIZER_STEP_GLOSSARY_KEYS[step]].short}</span>
          </label>
        ))}
      </div>
      {isEmpty && (
        <p
          role="alert"
          aria-live="polite"
          className="text-sm text-destructive"
          data-testid={`cs-row-error-${paramName}-steps`}
        >
          steps: select at least one step
        </p>
      )}
      <Label className="sr-only" htmlFor={`cs-row-${paramName}-steps`}>
        Normalizer pipeline steps for {paramName}
      </Label>
    </div>
  );
}
