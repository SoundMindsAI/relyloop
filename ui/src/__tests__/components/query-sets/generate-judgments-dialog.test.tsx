// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for `<GenerateJudgmentsDialog>` method picker + nudge + sparse-card
 * (feat_ubi_judgments Story 4.2 / FR-8 Capabilities A + B + C).
 *
 * Focuses on the new UBI surface; the existing LLM-only happy path is
 * implicitly covered by the form rendering the right fields when method
 * stays at `llm`.
 */
import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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

// feat_study_wizard_inline_judgment_generation Story 1.1 — defaultTarget prop.
describe('<GenerateJudgmentsDialog> — defaultTarget (lock + seed-on-open)', () => {
  it('AC-2: seeds the target field from defaultTarget and locks it read-only', async () => {
    render(
      withClient(
        <GenerateJudgmentsDialog
          open
          onOpenChange={() => {}}
          clusterId="c-1"
          querySetId="qs-1"
          defaultTarget="products"
        />,
      ),
    );
    const target = screen.getByTestId('gen-target');
    await waitFor(() => expect(target).toHaveValue('products'));
    expect(target).toHaveAttribute('readonly');
    expect(target).toHaveAttribute('aria-readonly', 'true');
  });

  it('AC-2: reopening with a new defaultTarget reflects the new value (not a stale seed)', async () => {
    const { rerender } = render(
      withClient(
        <GenerateJudgmentsDialog
          open
          onOpenChange={() => {}}
          clusterId="c-1"
          querySetId="qs-1"
          defaultTarget="products"
        />,
      ),
    );
    await waitFor(() => expect(screen.getByTestId('gen-target')).toHaveValue('products'));
    // Close, then reopen with a different target — the seed re-applies on open.
    rerender(
      withClient(
        <GenerateJudgmentsDialog
          open={false}
          onOpenChange={() => {}}
          clusterId="c-1"
          querySetId="qs-1"
          defaultTarget="docs-articles"
        />,
      ),
    );
    rerender(
      withClient(
        <GenerateJudgmentsDialog
          open
          onOpenChange={() => {}}
          clusterId="c-1"
          querySetId="qs-1"
          defaultTarget="docs-articles"
        />,
      ),
    );
    await waitFor(() => expect(screen.getByTestId('gen-target')).toHaveValue('docs-articles'));
  });

  it('AC-6: without defaultTarget the target field is empty and editable (backward-compatible)', () => {
    render(
      withClient(
        <GenerateJudgmentsDialog open onOpenChange={() => {}} clusterId="c-1" querySetId="qs-1" />,
      ),
    );
    const target = screen.getByTestId('gen-target');
    expect(target).toHaveValue('');
    expect(target).not.toHaveAttribute('readonly');
  });
});
