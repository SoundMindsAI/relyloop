// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_study_clone_narrow_bounds Story 1.1 — pure helper that rewrites a
 * cloned study's ``search_space`` JSON so each numeric ``low``/``high`` clamps
 * to ±``percent``% around the source study's winning param value.
 *
 * Spec reference: [feature_spec.md](../../../docs/00_overview/planned_features/feat_study_clone_narrow_bounds/feature_spec.md)
 * FR-9 (helper contract), FR-10 (clamp algorithm), FR-11 (winner outside bounds),
 * D-10 (negative-winner unordered min/max), D-11 (no-op leaves bytes exact —
 * detected by ``result.narrowed.length === 0`` in the caller).
 *
 * Pure helper: no React, no I/O, no async. Trivially unit-testable.
 *
 * Server-side ``SearchSpace.model_validate`` (backend/app/domain/study/search_space.py)
 * is the canonical validator. This helper mirrors every per-type constraint
 * so the rewritten JSON is guaranteed structurally valid:
 *
 *   - FloatParam: ``low < high``; if ``log === true``, ``low > 0``.
 *   - IntParam: ``low <= high`` (single-value ranges are valid).
 *   - CategoricalParam: untouched.
 */

const DEFAULT_PERCENT = 20;
const LOG_UNIFORM_FLOOR = 1e-12;

export type SkipReason =
  | 'categorical'
  | 'missing_winner'
  | 'non_numeric_winner'
  | 'degenerate_intersection'
  | 'log_uniform_zero_floor';

export interface NarrowBoundsResult {
  /** The rewritten search_space JSON (valid SearchSpace shape). */
  json: string;
  /**
   * Param names whose ``low``/``high`` were narrowed. Preserves
   * ``Object.entries`` insertion order from the input.
   */
  narrowed: string[];
  /** Params skipped (not narrowed), each with a reason. */
  skipped: { name: string; reason: SkipReason }[];
}

type FloatSpec = { type: 'float'; low: number; high: number; log?: boolean };
type IntSpec = { type: 'int'; low: number; high: number };
type CategoricalSpec = { type: 'categorical'; choices: unknown[] };
type ParamSpec = FloatSpec | IntSpec | CategoricalSpec;

interface SearchSpaceShape {
  params: Record<string, ParamSpec>;
  // The Pydantic model is ``model_config = ConfigDict(extra="forbid")`` — any
  // extra fields would fail server-side. We don't add or remove fields here.
}

/**
 * Rewrite ``spaceJson`` so each numeric param's ``low``/``high`` is clamped
 * to ±``percent``% around ``winnerParams[name]``.
 *
 * @param spaceJson - JSON-encoded ``SearchSpace`` (the textarea content).
 * @param winnerParams - Flat map from the source's ``recommended_config``
 *     (digest endpoint, ``dict[str, Any]`` on the wire).
 * @param percent - Clamp width (default 20).
 *
 * @throws {SyntaxError} If ``spaceJson`` is not parseable JSON. Structural
 *     issues (missing ``params``, unknown ``type`` values) are not validated
 *     here — the helper assumes a structurally-valid input and the
 *     server-side validator catches anything that slips through.
 *
 * @returns ``NarrowBoundsResult`` carrying the re-stringified JSON, the
 *     list of narrowed param names, and the list of skipped params with
 *     reasons (for caller toast messages and tests).
 */
export function narrowBoundsAroundWinner(
  spaceJson: string,
  winnerParams: Record<string, unknown>,
  percent: number = DEFAULT_PERCENT,
): NarrowBoundsResult {
  const parsed = JSON.parse(spaceJson) as SearchSpaceShape | null;
  // Defensive: valid JSON includes ``null``, ``[]``, ``{}``, etc. — anything
  // that doesn't carry ``params`` returns a no-op result rather than throwing
  // TypeError. The server-side ``SearchSpace.model_validate`` is the canonical
  // structural validator; this helper is the rewriter, not the validator.
  if (parsed === null || typeof parsed !== 'object' || !parsed.params) {
    return { json: spaceJson, narrowed: [], skipped: [] };
  }
  const narrowed: string[] = [];
  const skipped: { name: string; reason: SkipReason }[] = [];
  const p = percent / 100;

  for (const [name, spec] of Object.entries(parsed.params)) {
    if (spec.type === 'categorical') {
      skipped.push({ name, reason: 'categorical' });
      continue;
    }

    if (!(name in winnerParams)) {
      skipped.push({ name, reason: 'missing_winner' });
      continue;
    }

    const winner = winnerParams[name];
    if (typeof winner !== 'number') {
      skipped.push({ name, reason: 'non_numeric_winner' });
      continue;
    }
    // D-10 explicit zero-winner skip — applies to BOTH float and int types.
    // Without this guard, IntParam with winner=0 falls through to ``[0, 0]``
    // (because ``0 > 0`` is false), inconsistent with FloatParam where the
    // strict-inequality check catches it. The spec lock says winner=0 always
    // skips with degenerate_intersection — no positive-width range.
    if (winner === 0) {
      skipped.push({ name, reason: 'degenerate_intersection' });
      continue;
    }

    // D-10: negative-safe target range. For winner = 0, a === b === 0 →
    // zero-width target → naturally falls through to degenerate skip below.
    const a = winner * (1 - p);
    const b = winner * (1 + p);
    const targetLow = Math.min(a, b);
    const targetHigh = Math.max(a, b);

    // Clamp to the existing bounds. FR-11: if the target range and current
    // range don't intersect (winner outside current bounds AND ±p% disjoint),
    // newLow/newHigh becomes degenerate and we skip without producing an
    // invalid range.
    let newLow = Math.max(spec.low, targetLow);
    let newHigh = Math.min(spec.high, targetHigh);

    if (spec.type === 'float') {
      // Log-uniform floor: server-side FloatParam validator rejects log=true
      // with low<=0. Apply the floor BEFORE the degenerate check so we don't
      // misclassify the skip reason.
      if (spec.log === true) {
        newLow = Math.max(newLow, LOG_UNIFORM_FLOOR);
        if (newLow >= newHigh) {
          skipped.push({ name, reason: 'log_uniform_zero_floor' });
          continue;
        }
      }
      // Non-log float requires low < high (strict).
      if (newLow >= newHigh) {
        skipped.push({ name, reason: 'degenerate_intersection' });
        continue;
      }
      spec.low = newLow;
      spec.high = newHigh;
      narrowed.push(name);
      continue;
    }

    // IntParam: round outward to the nearest int that respects the bounds,
    // then validate low <= high (equality is valid — single-value range).
    if (spec.type === 'int') {
      newLow = Math.ceil(newLow);
      newHigh = Math.floor(newHigh);
      if (newLow > newHigh) {
        skipped.push({ name, reason: 'degenerate_intersection' });
        continue;
      }
      spec.low = newLow;
      spec.high = newHigh;
      narrowed.push(name);
      continue;
    }
  }

  return {
    json: JSON.stringify(parsed, null, 2),
    narrowed,
    skipped,
  };
}
