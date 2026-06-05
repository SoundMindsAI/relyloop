// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_query_normalization_tuning FR-6 — digest analyzer-redundancy advisory.
 *
 * Covers AC-8 (visible when ES + lowercasing choice + overlapping analyzer),
 * AC-9 (hidden for Solr), AC-10 (hidden for `none`), plus the loading/error
 * (schema undefined) and whitespace-analyzer false-positive guards.
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';

import { DigestPanel, shouldShowNormalizerAdvisory } from '@/components/studies/digest-panel';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { Schema } from '@/lib/api/clusters';
import type { DigestResponse } from '@/lib/api/digests';
import { glossary } from '@/lib/glossary';

function wrap(node: ReactNode) {
  return render(<TooltipProvider delayDuration={0}>{node}</TooltipProvider>);
}

function digestWith(queryNormalizer: string): DigestResponse {
  return {
    id: 'd1',
    study_id: 'st1',
    narrative: 'Tuning lifted ndcg@10.',
    parameter_importance: {},
    recommended_config: { query_normalizer: queryNormalizer, title_boost: 1.5 },
    suggested_followups: [],
    generated_by: 'openai:gpt-4o-2024-08-06',
    generated_at: '2026-05-24T00:00:00Z',
  };
}

const STANDARD_SCHEMA: Schema = {
  name: 'products',
  fields: [{ name: 'title', type: 'text', analyzer: 'standard' }],
};

const TESTID = 'digest-normalizer-advisory';

function renderPanel(props: {
  digest: DigestResponse;
  engineType?: 'elasticsearch' | 'opensearch' | 'solr';
  schema?: Schema;
}) {
  wrap(
    <DigestPanel
      digest={props.digest}
      baselineMetric={0.4}
      bestMetric={0.5}
      pendingProposal={null}
      engineType={props.engineType}
      schema={props.schema}
    />,
  );
}

describe('DigestPanel — normalizer advisory (FR-6)', () => {
  it('AC-8: visible for ES + lowercasing choice + overlapping analyzer', () => {
    renderPanel({
      digest: digestWith('lowercase+trim'),
      engineType: 'elasticsearch',
      schema: STANDARD_SCHEMA,
    });
    const advisory = screen.getByTestId(TESTID);
    expect(advisory).toHaveTextContent(glossary['digest.normalizer_advisory'].long);
  });

  it('AC-9: hidden for Solr', () => {
    renderPanel({
      digest: digestWith('lowercase'),
      engineType: 'solr',
      schema: STANDARD_SCHEMA,
    });
    expect(screen.queryByTestId(TESTID)).toBeNull();
  });

  it('AC-10: hidden for none choice', () => {
    renderPanel({
      digest: digestWith('none'),
      engineType: 'elasticsearch',
      schema: STANDARD_SCHEMA,
    });
    expect(screen.queryByTestId(TESTID)).toBeNull();
  });

  it('hidden while schema is undefined (loading / error / 404)', () => {
    renderPanel({
      digest: digestWith('lowercase+trim'),
      engineType: 'elasticsearch',
      schema: undefined,
    });
    expect(screen.queryByTestId(TESTID)).toBeNull();
  });

  it('hidden for a whitespace-only analyzer (false-positive guard)', () => {
    renderPanel({
      digest: digestWith('lowercase+trim'),
      engineType: 'elasticsearch',
      schema: {
        name: 'products',
        fields: [{ name: 'title', type: 'text', analyzer: 'whitespace' }],
      },
    });
    expect(screen.queryByTestId(TESTID)).toBeNull();
  });
});

describe('shouldShowNormalizerAdvisory predicate', () => {
  it('true for a custom analyzer name containing "lowercase"', () => {
    expect(
      shouldShowNormalizerAdvisory(
        { query_normalizer: 'lowercase+trim+expand_contractions' },
        'opensearch',
        {
          name: 'p',
          fields: [{ name: 'title', type: 'text', analyzer: 'my_custom_lowercase_pipe' }],
        },
      ),
    ).toBe(true);
  });

  it('true for a custom analyzer with mixed-case "Lowercase" (case-insensitive)', () => {
    expect(
      shouldShowNormalizerAdvisory({ query_normalizer: 'lowercase' }, 'elasticsearch', {
        name: 'p',
        fields: [{ name: 'title', type: 'text', analyzer: 'MyCustomLowercaseAnalyzer' }],
      }),
    ).toBe(true);
  });

  it('false when engineType is undefined', () => {
    expect(
      shouldShowNormalizerAdvisory({ query_normalizer: 'lowercase' }, undefined, STANDARD_SCHEMA),
    ).toBe(false);
  });

  it('false when the only text field has no analyzer', () => {
    expect(
      shouldShowNormalizerAdvisory({ query_normalizer: 'lowercase' }, 'elasticsearch', {
        name: 'p',
        fields: [{ name: 'title', type: 'text', analyzer: null }],
      }),
    ).toBe(false);
  });

  it('false when query_normalizer is absent from recommended_config', () => {
    expect(
      shouldShowNormalizerAdvisory({ title_boost: 1.5 }, 'elasticsearch', STANDARD_SCHEMA),
    ).toBe(false);
  });
});
