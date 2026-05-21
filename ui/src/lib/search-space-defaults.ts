/**
 * Step-4 auto-fill heuristic for the create-study wizard
 * (chore_create_study_wizard_polish, spec FR-1).
 *
 * Pure-function module. No I/O, no React, no DOM. Consumed by
 * `create-study-modal.tsx`'s Step-3 → Step-4 transition effect.
 *
 * Source-of-truth for the cardinality estimator:
 *   backend/app/domain/study/search_space.py:177-196 (`estimate_cardinality`).
 * The Python parity test at
 *   backend/tests/unit/domain/test_search_space_cardinality_parity.py
 * consumes the same JSON fixture as
 *   ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts
 * so any drift between the two implementations surfaces in one of the
 * two tests.
 */

/**
 * Wire-format ParamSpec — mirrors backend
 * `backend/app/domain/study/search_space.py` discriminated union over
 * FloatParam / IntParam / CategoricalParam.
 */
export type ParamSpec =
  | { type: 'float'; low: number; high: number; log?: boolean }
  | { type: 'int'; low: number; high: number }
  | { type: 'categorical'; choices: (string | number | boolean)[] };

/** Wire-format SearchSpace JSON — matches backend `SearchSpace`. */
export type SearchSpaceJson = { params: Record<string, ParamSpec> };

/**
 * Return shape of `buildStarterSearchSpace` (feat_agent_propose_search_space
 * Story 1.2). Pairs the validated search-space JSON with cap-aware-fallback
 * metadata so the agent's `propose_search_space` tool can populate
 * `grounding.cap_aware_fallback_param_names` without duplicating fallback
 * logic at the tool layer. The Python sibling at
 * `backend/app/domain/study/search_space_defaults.py` returns the equivalent
 * `StarterSearchSpace` dataclass and the TS↔Python parity fixture asserts
 * byte-identical output for the `space` field.
 */
export type StarterSearchSpace = {
  space: SearchSpaceJson;
  capAwareFallbackParamNames: string[];
};

/**
 * Naming-convention heuristic table (spec FR-1 §7).
 *
 * Names are tested top-to-bottom; the first matching rule wins.
 * Reflects ES/OpenSearch query-DSL convention; engine-aware defaults are
 * deliberately out of scope (decision log 2026-05-19, spec §19).
 */
export const HEURISTIC_RULES: ReadonlyArray<{ match: RegExp; spec: ParamSpec }> = [
  // field-boost-like (prefix) → log-uniform float in [0.5, 10.0]
  { match: /^(field_boost|boost_)/, spec: { type: 'float', low: 0.5, high: 10.0, log: true } },
  // field-boost-like (standalone `boost` OR `<field>_boost` suffix — ES multi_match
  // per-field convention). Pairs with the prefix rule above so all four common
  // boost-naming variants (`boost`, `boost_<x>`, `field_boost_<x>`, `<x>_boost`)
  // produce the same log-uniform [0.5, 10] range.
  { match: /^(boost|.+_boost)$/, spec: { type: 'float', low: 0.5, high: 10.0, log: true } },
  // tie-breaker / weight → uniform float in [0.0, 1.0]
  { match: /^(tie_breaker|.*_weight)$/, spec: { type: 'float', low: 0.0, high: 1.0 } },
  // slop / min_should_match / *_size → small int in [0, 5]
  { match: /^(slop|min_should_match|.*_size)$/, spec: { type: 'int', low: 0, high: 5 } },
  // fuzziness → categorical AUTO + integer-as-string choices
  {
    match: /^fuzziness$/,
    spec: { type: 'categorical', choices: ['AUTO', '0', '1', '2'] },
  },
];

/** Fall-through default when no naming-convention rule matches. */
const DEFAULT_FALLBACK: ParamSpec = { type: 'float', low: 0.0, high: 1.0 };

/**
 * Simple-form `declared_params` value → ParamSpec mapping (spec FR-1).
 *
 * Only consulted for names that did NOT match `HEURISTIC_RULES`. The
 * `'string'` case emits a degenerate single-choice categorical with a
 * `__placeholder__` sentinel — the modal renders a non-blocking amber
 * warning so the user replaces it before submitting (spec FR-1, AC-1).
 *
 * Exported (`feat_create_study_search_space_builder` Story 2.1) so the
 * builder can seed initial spec values for declared-but-unset rows. Note
 * that this is NOT used for the cross-type stash fallback — type-switch
 * uses target-type-only `defaultSpecForType(nextType)` defaults instead.
 */
export function simpleFormSpec(typeName: string): ParamSpec | null {
  switch (typeName) {
    case 'int':
      return { type: 'int', low: 0, high: 5 };
    case 'float':
      return { type: 'float', low: 0.0, high: 1.0 };
    case 'bool':
      return { type: 'categorical', choices: [true, false] };
    case 'string':
      return { type: 'categorical', choices: ['__placeholder__'] };
    default:
      return null;
  }
}

/**
 * Per-param cardinality contribution.
 *
 * Float counted as 100 (matches the Python source-of-truth at
 * `backend/app/domain/study/search_space.py:191`); Int counted as
 * `high - low + 1`; Categorical counted as `len(choices)`.
 *
 * Extracted from `estimateCardinality()`'s loop body in
 * `feat_create_study_search_space_builder` Story 2.3 so the builder
 * can render per-row contribution counters that match the total.
 */
export function estimateParamCardinality(spec: ParamSpec): number {
  if (spec.type === 'float') return 100;
  if (spec.type === 'int') {
    // Math.max(0, ...) guards against textarea-supplied inverted bounds
    // (low > high) producing a negative cardinality in the header counter.
    // The row error fires separately via <RowNumeric>'s bound check.
    return Math.max(0, spec.high - spec.low + 1);
  }
  // Optional chaining defends against runtime-malformed JSON where
  // `choices` is undefined despite the TypeScript discriminator.
  return spec.choices?.length ?? 0;
}

/**
 * TypeScript port of
 * `backend/app/domain/study/search_space.py:estimate_cardinality`.
 * Product of `estimateParamCardinality` across every param.
 *
 * Returns at least 1 (an empty space would have been rejected by
 * Pydantic's `min_length=1` on `params`).
 */
export function estimateCardinality(space: SearchSpaceJson): number {
  let total = 1;
  for (const spec of Object.values(space.params)) {
    total *= estimateParamCardinality(spec);
  }
  return total;
}

/**
 * Build a starter search space for a template's `declared_params` dict.
 *
 * Heuristic priority per spec FR-1:
 *   1. Try `HEURISTIC_RULES` (naming convention).
 *   2. Else fall back to simple-form mapping for `'int'/'float'/'bool'/'string'`.
 *   3. Else use `DEFAULT_FALLBACK` (uniform float 0..1).
 *
 * Cap-aware fallback (spec FR-1 "Cap-aware fallback"): if the candidate
 * space's cardinality exceeds 10⁶, narrow it by converting float params
 * to `{type: 'int', low: 0, high: 5}` in priority order:
 *
 *   1. Unmatched fall-through floats first (lexicographic order of name).
 *   2. Regex-matched floats only if still over cap (lexicographic).
 *
 * Categoricals (e.g. `fuzziness`) and ints are never converted.
 *
 * Emits `console.warn` whenever the cap-aware fallback fires.
 *
 * **Throws** `Error("empty declared_params: …")` when `declaredParams` is `{}`.
 *
 * **Throws** `Error("cap-aware fallback exhausted: …")` when even after
 * converting every float to `int[0, 5]` the cardinality is still > 10⁶
 * (e.g., 8 fall-through floats → `6⁸ = 1_679_616 > 10⁶`).
 *
 * Both throws match the Python sibling at
 * `backend/app/domain/study/search_space_defaults.py` which raises
 * `InvalidSearchSpaceError` under the same conditions; the parity test at
 * `ui/src/__tests__/lib/search-space-defaults.parity.test.ts` enforces
 * symmetric behavior.
 */
export function buildStarterSearchSpace(
  declaredParams: Record<string, string>,
): StarterSearchSpace {
  if (Object.keys(declaredParams).length === 0) {
    throw new Error('empty declared_params: at least one declared param is required');
  }

  const params: Record<string, ParamSpec> = {};
  // Track which param names got their spec from the regex table (vs. the
  // fall-through default) so cap-aware fallback can prefer to convert
  // fall-through floats first.
  const regexMatched = new Set<string>();

  for (const [name, typeName] of Object.entries(declaredParams)) {
    const matched = matchHeuristicRule(name);
    if (matched) {
      params[name] = clone(matched);
      regexMatched.add(name);
      continue;
    }
    const simple = simpleFormSpec(typeName);
    params[name] = simple ?? clone(DEFAULT_FALLBACK);
  }

  const candidate: SearchSpaceJson = { params };
  if (estimateCardinality(candidate) <= 1_000_000) {
    return { space: candidate, capAwareFallbackParamNames: [] };
  }

  // Cap-aware fallback. Convert fall-through floats first, then regex-matched
  // floats, both in lexicographic order, until cardinality ≤ 10⁶.
  const fallThroughFloats = Object.keys(params)
    .filter((n) => params[n]!.type === 'float' && !regexMatched.has(n))
    .sort();
  const regexFloats = Object.keys(params)
    .filter((n) => params[n]!.type === 'float' && regexMatched.has(n))
    .sort();

  const capAwareFallbackParamNames: string[] = [];
  for (const name of [...fallThroughFloats, ...regexFloats]) {
    params[name] = { type: 'int', low: 0, high: 5 };
    capAwareFallbackParamNames.push(name);
    if (estimateCardinality(candidate) <= 1_000_000) {
      break;
    }
  }

  if (capAwareFallbackParamNames.length > 0) {
    // eslint-disable-next-line no-console
    console.warn(
      `[search-space-defaults] cap-aware fallback fired: converted float param(s) ` +
        `${capAwareFallbackParamNames.map((n) => `'${n}'`).join(', ')} to int [0, 5] to stay ` +
        `under the 10^6 cardinality cap.`,
    );
  }

  if (estimateCardinality(candidate) > 1_000_000) {
    throw new Error(
      `cap-aware fallback exhausted: cardinality=${estimateCardinality(candidate)} > 10^6 ` +
        `for declared_params=${JSON.stringify(Object.keys(declaredParams).sort())}`,
    );
  }

  return { space: candidate, capAwareFallbackParamNames };
}

function matchHeuristicRule(name: string): ParamSpec | null {
  for (const { match, spec } of HEURISTIC_RULES) {
    if (match.test(name)) return spec;
  }
  return null;
}

function clone(spec: ParamSpec): ParamSpec {
  if (spec.type === 'categorical') {
    return { type: 'categorical', choices: [...spec.choices] };
  }
  return { ...spec };
}
