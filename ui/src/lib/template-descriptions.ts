// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Static client-side description map + cheatsheet URL resolver for the
 * runnable [template library](../../samples/templates/) (`chore_template_library_expansion` FR-7).
 *
 * Source: samples/templates/README.md + samples/templates/solr/README.md.
 *
 * Keys are the **recommended registration names** documented in those
 * READMEs. An operator who follows the README's `--name <slug>` convention
 * sees a one-line "when to use" summary inline under the Step-3 picker.
 * If the registered template `name` has no entry here, the picker renders
 * nothing — graceful miss per FR-7 (NEVER show a wrong summary).
 */

import { type EngineType, ENGINE_TYPE_VALUES } from '@/lib/enums';

// Recommended registration names (one per runnable library template) plus
// the one-line "when to use" summary. If you rename a recommended slug,
// update the corresponding README's "Recommended registration name" line
// in lockstep — those two strings ARE the contract.
export const TEMPLATE_DESCRIPTIONS: Readonly<Record<string, string>> = {
  // ES / OpenSearch — samples/templates/README.md
  'multi-match-basic-v1':
    'Fast lexical baseline (best_fields multi_match). Use as the starting point before reaching for decay, boosting, or rescoring.',
  'function-score-decay-v1':
    'function_score with a gauss decay over a numeric/date field. Use when freshness or proximity should boost lexical relevance.',
  'bool-boosted-v1':
    'bool must/should/filter with tunable minimum_should_match. Use when you need explicit clause-level control over recall vs precision.',
  'rescore-phrase-v1':
    'Fast lexical first pass + match_phrase rescore over the top-N hits. Use when exact-phrase matches should be promoted within the top-N.',
  // Solr — samples/templates/solr/README.md
  'edismax-basic-v1':
    'Apache Solr edismax lexical baseline with tunable tie / mm / ps. The canonical Solr starting point.',
  'boost-decay-v1':
    'Apache Solr edismax + recency boost via recip(ms(NOW, field), m, a, b). Use when recency should boost lexical edismax matches.',
} as const;

/**
 * Return the one-line summary for a template registered under `name`,
 * or `null` if there's no map entry (operator used a different name).
 * The Step-3 picker degrades gracefully when this returns null.
 */
export function descriptionFor(name: string | null | undefined): string | null {
  if (!name) return null;
  return TEMPLATE_DESCRIPTIONS[name] ?? null;
}

// Values must match backend/app/adapters/registry.py SUPPORTED_ENGINE_TYPES.
// (Also paired with ENGINE_TYPE_VALUES in @/lib/enums; the import below is
// the runtime type guard.)
const CHEATSHEET_URL_BY_ENGINE: Readonly<Record<EngineType, string>> = {
  elasticsearch:
    'https://github.com/SoundMindsAI/relyloop/blob/main/docs/06_vendor_docs/elasticsearch-tunable-params.md',
  opensearch:
    'https://github.com/SoundMindsAI/relyloop/blob/main/docs/06_vendor_docs/opensearch-tunable-params.md',
  solr: 'https://github.com/SoundMindsAI/relyloop/blob/main/docs/06_vendor_docs/solr-tunable-params.md',
};

/**
 * Resolve the engine-appropriate tunable-params cheatsheet URL.
 *
 * Returns `null` if the engine_type is not one of the three supported
 * values (defense in depth — the call site already has the type narrowed
 * via the cluster row, so this is just a runtime guard).
 */
export function cheatsheetUrlFor(engineType: string | null | undefined): string | null {
  if (!engineType) return null;
  if (!(ENGINE_TYPE_VALUES as readonly string[]).includes(engineType)) return null;
  return CHEATSHEET_URL_BY_ENGINE[engineType as EngineType] ?? null;
}
