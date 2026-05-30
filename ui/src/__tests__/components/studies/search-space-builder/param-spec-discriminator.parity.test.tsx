// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Source-of-truth parity test (Story 2.1, FR-2, AC-2).
 *
 * Reads `backend/app/domain/study/search_space.py` at runtime and asserts
 * the frontend's `ROW_TYPE_VALUES` array matches the Pydantic discriminator
 * `Literal["..."]` values one-for-one.
 *
 * This is the dedicated source-of-truth gate for `ParamSpec.type` wire
 * values. The values live in a discriminated union (FloatParam, IntParam,
 * CategoricalParam) rather than `ui/src/lib/enums.ts`, so the
 * `form-select-discipline.test.tsx` lint guard doesn't catch drift. This
 * test does.
 *
 * If a future spec adds a fourth `ParamSpec` variant, this test fails
 * until both the backend Literal and the frontend `ROW_TYPE_VALUES`
 * array are updated in the same PR.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { ROW_TYPE_VALUES } from '@/components/studies/search-space-builder/row-type-selector';

const BACKEND_PATH = join(process.cwd(), '..', 'backend/app/domain/study/search_space.py');

describe('ParamSpec discriminator parity', () => {
  it('frontend ROW_TYPE_VALUES matches backend Literal values in order', () => {
    const backendSrc = readFileSync(BACKEND_PATH, 'utf-8');

    // Match `type: Literal["..."]` (whitespace-flexible) inside the
    // FloatParam / IntParam / CategoricalParam class bodies.
    const matches = [...backendSrc.matchAll(/type:\s*Literal\[\s*"([^"]+)"\s*\]/g)].map(
      (m) => m[1] as string,
    );

    // The backend file declares the three discriminators in this order:
    expect(matches).toEqual(['float', 'int', 'categorical']);

    // The frontend array MUST match character-for-character + ordering.
    expect([...ROW_TYPE_VALUES]).toEqual(matches);
  });
});
