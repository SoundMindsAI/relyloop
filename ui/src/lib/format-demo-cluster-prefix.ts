// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// Plural-aware copy helper for the home-page demo-data banner.
//
// Spec FR-3 commits the final body sentence verbatim across all K-variants
// (1 / 2-3 / 4 demos present). Only the prefix verb agrees (is/are).
// Returns the parts so the banner JSX can wrap each slug in <code>
// without re-parsing.

export interface DemoClusterCopyParts {
  readonly prefix: string;
  readonly slugs: readonly string[];
  readonly suffix: string;
}

const PLURAL_BODY =
  'are pre-loaded with realistic queries, judgments, a winning completed study, and a pending proposal. Run your own optimization against any of them.';
const SINGULAR_BODY =
  'is pre-loaded with realistic queries, judgments, a winning completed study, and a pending proposal. Run your own optimization against any of them.';

export function formatDemoClusterPrefix(slugs: readonly string[]): DemoClusterCopyParts {
  if (slugs.length === 1) {
    return { prefix: 'One sample cluster — ', slugs, suffix: ' — ' + SINGULAR_BODY };
  }
  if (slugs.length === 4) {
    return { prefix: 'Four sample clusters — ', slugs, suffix: ' — ' + PLURAL_BODY };
  }
  // K=2 or K=3
  return { prefix: `${slugs.length} sample clusters — `, slugs, suffix: ' — ' + PLURAL_BODY };
}
