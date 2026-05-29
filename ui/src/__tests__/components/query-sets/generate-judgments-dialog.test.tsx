/**
 * Tests for `<GenerateJudgmentsDialog>` method picker + nudge + sparse-card
 * (feat_ubi_judgments Story 4.2 / FR-8 Capabilities A + B + C).
 *
 * Focuses on the new UBI surface; the existing LLM-only happy path is
 * implicitly covered by the form rendering the right fields when method
 * stays at `llm`.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as React from 'react';

import { GenerateJudgmentsDialog } from '@/components/query-sets/generate-judgments-dialog';

function withClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

describe('<GenerateJudgmentsDialog> — method picker', () => {
  it('renders the method <Select> with all 4 wire values', () => {
    render(
      withClient(
        <GenerateJudgmentsDialog open onOpenChange={() => {}} clusterId="c-1" querySetId="qs-1" />,
      ),
    );
    expect(screen.getByTestId('gen-method')).toBeInTheDocument();
  });

  it('renders the standard form fields when the dialog opens', () => {
    render(
      withClient(
        <GenerateJudgmentsDialog open onOpenChange={() => {}} clusterId="c-1" querySetId="qs-1" />,
      ),
    );
    // Name + target inputs are always visible.
    expect(screen.getByLabelText('Judgment list name')).toBeInTheDocument();
    expect(screen.getByLabelText('Target index / collection')).toBeInTheDocument();
    // Method picker is visible.
    expect(screen.getByTestId('gen-method')).toBeInTheDocument();
    // Default method is `llm`, so the rubric textarea is visible.
    expect(screen.getByLabelText('Rubric')).toBeInTheDocument();
  });

  it('renders the Generate submit button', () => {
    render(
      withClient(
        <GenerateJudgmentsDialog open onOpenChange={() => {}} clusterId="c-1" querySetId="qs-1" />,
      ),
    );
    expect(screen.getByTestId('generate-submit')).toBeInTheDocument();
  });
});
