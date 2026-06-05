// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Best-trial parameter-table diff (feat_ubi_llm_study_comparison FR-5).
 *
 * Pure helper: merge two config dicts (`recommended_config` or trial `params`)
 * into one row per parameter key, flagged `=` (equal on both sides) or `Δ`
 * (differ, or present on only one side).
 */

export type ParamFlag = '=' | 'Δ';

export interface ParamDiffRow {
  key: string;
  /** `undefined` when the key is absent on the A side (renders as an em-dash). */
  aValue: unknown;
  /** `undefined` when the key is absent on the B side. */
  bValue: unknown;
  present: { a: boolean; b: boolean };
  flag: ParamFlag;
}

function stableEqual(a: unknown, b: unknown): boolean {
  // JSON-stable comparison so {x:1,y:2} === {y:2,x:1} would NOT collapse (key
  // order is preserved by JSON.stringify on the same object) — but scalar and
  // array equality work as expected, which covers every recommended_config
  // value shape (numbers, strings, bools, small arrays).
  if (a === b) return true;
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Merge `aConfig` (LLM) + `bConfig` (UBI) into sorted parameter rows. A key
 * present on only one side is always `Δ`; a key on both sides is `=` iff the
 * values are stably equal.
 */
export function partitionParamDiff(
  aConfig: Record<string, unknown> | null | undefined,
  bConfig: Record<string, unknown> | null | undefined,
): ParamDiffRow[] {
  const a = aConfig ?? {};
  const b = bConfig ?? {};
  const keys = Array.from(new Set([...Object.keys(a), ...Object.keys(b)])).sort();
  return keys.map((key) => {
    const inA = Object.prototype.hasOwnProperty.call(a, key);
    const inB = Object.prototype.hasOwnProperty.call(b, key);
    const equal = inA && inB && stableEqual(a[key], b[key]);
    return {
      key,
      aValue: inA ? a[key] : undefined,
      bValue: inB ? b[key] : undefined,
      present: { a: inA, b: inB },
      flag: equal ? '=' : 'Δ',
    };
  });
}
