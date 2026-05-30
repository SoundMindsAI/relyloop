// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Non-interactive placeholder card for `<SearchSpaceBuilder>` (Story 1.1).
 *
 * Four variants:
 *   - `parse-error` — `JSON.parse(value)` threw. `role="status"` per spec AC-12.
 *     The detailed exception still surfaces in CreateStudyModal's existing
 *     `cs-search-space-error` alert (no double-announce).
 *   - `transient` — `templateBody === null` due to network/server hiccup
 *     (template fetch in flight or returning 5xx). Adjacent Retry button
 *     in CreateStudyModal handles recovery.
 *   - `no-template` — no template selected yet (initial Step-4 mount or
 *     after the user cleared the textarea with no template). Soft hint.
 *   - `missing-params-hint` — parseable JSON but no `params:` wrapper.
 *     Rendered as a foot hint BELOW the declared-param rows (NOT a
 *     placeholder mode). See `<SearchSpaceBuilder>` placeholder cascade.
 */

import * as React from 'react';

type PlaceholderVariant = 'parse-error' | 'transient' | 'no-template' | 'missing-params-hint';

interface BuilderPlaceholderProps {
  variant: PlaceholderVariant;
}

const MESSAGES: Record<PlaceholderVariant, string> = {
  'parse-error': 'JSON has syntax errors — fix in the textarea to use the builder.',
  transient: "Couldn't load the template. Server-side validation will still catch typos on submit.",
  'no-template': 'Pick a template to populate the builder.',
  'missing-params-hint':
    'Wrap your JSON in a `params:` object — the rows above are empty because no `params` key was found.',
};

const TEST_IDS: Record<PlaceholderVariant, string> = {
  'parse-error': 'cs-search-space-builder-parse-error',
  transient: 'cs-search-space-builder-transient',
  'no-template': 'cs-search-space-builder-no-template',
  'missing-params-hint': 'cs-search-space-builder-missing-params-hint',
};

export function BuilderPlaceholder({ variant }: BuilderPlaceholderProps): React.ReactElement {
  return (
    <div
      role="status"
      aria-live="polite"
      className="text-sm text-muted-foreground border border-dashed border-border rounded p-3"
      data-testid={TEST_IDS[variant]}
    >
      {MESSAGES[variant]}
    </div>
  );
}
