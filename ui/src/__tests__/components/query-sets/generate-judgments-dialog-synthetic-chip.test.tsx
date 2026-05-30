/**
 * Story 3.2 / FR-7 surface #1 — three-branch synthetic-data chip gating on
 * the GenerateJudgmentsDialog method picker.
 *
 * The chip renders inside Radix `<SelectItem>`, which only mounts in a
 * portal when the dropdown is open — brittle to drive in jsdom. We mock
 * the Radix select primitives to render their children inline so the
 * chip-gating logic (`UBI_METHODS.has(method) && cluster.data &&
 * isDemoSyntheticUbiClusterName(cluster.name)`) is asserted directly,
 * and mock `useCluster` to control the cluster name per branch.
 *
 * Branches:
 *  (a) synthetic-UBI demo cluster (acme-products-prod) → chip on each
 *      of the 3 UBI options (ctr_threshold, dwell_time, hybrid_ubi_llm).
 *  (b) demo cluster without synthetic UBI (news-search-staging) → no chip.
 *  (c) non-demo cluster → no chip.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import * as React from 'react';
import { describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';

// Mock useCluster so each test controls cluster.data.name. Other hooks the
// dialog pulls from this module aren't used by the chip path; keep the mock
// minimal + typed loosely.
const mockUseCluster = vi.fn();
vi.mock('@/lib/api/clusters', () => ({
  useCluster: (id: string) => mockUseCluster(id),
}));

// Stub the UBI hooks — readiness drives the picker default but the chip
// path only depends on cluster.name + the static UBI_METHODS set.
vi.mock('@/lib/api/ubi', () => ({
  useUbiReadiness: () => ({ data: undefined }),
  useGenerateJudgmentsFromUbi: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('@/lib/api/judgments', () => ({
  useGenerateJudgments: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('@/lib/api/query-templates', () => ({
  useTemplates: () => ({ data: { data: [] } }),
}));

// Render the Radix select primitives' children inline so <SelectItem>
// content (and its chip) is in the DOM without opening a portal.
vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectValue: () => <span />,
}));

// Import AFTER mocks so the dialog picks up the mocked modules.
import { GenerateJudgmentsDialog } from '@/components/query-sets/generate-judgments-dialog';

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <GenerateJudgmentsDialog open onOpenChange={() => {}} clusterId="c-1" querySetId="qs-1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe('<GenerateJudgmentsDialog> — synthetic-data chip (FR-7 surface #1)', () => {
  it('(a) renders the chip on every UBI option for a synthetic-UBI demo cluster', () => {
    mockUseCluster.mockReturnValue({ data: { name: 'acme-products-prod' } });
    renderDialog();
    // 3 UBI methods (ctr_threshold, dwell_time, hybrid_ubi_llm) each get a chip.
    expect(screen.getAllByTestId('demo-badge-synthetic-ubi')).toHaveLength(3);
  });

  it('(b) renders no chip for news-search-staging (demo cluster, no synthetic UBI)', () => {
    mockUseCluster.mockReturnValue({ data: { name: 'news-search-staging' } });
    renderDialog();
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });

  it('(c) renders no chip for a non-demo cluster', () => {
    mockUseCluster.mockReturnValue({ data: { name: 'production-real-cluster' } });
    renderDialog();
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });

  it('renders no chip while cluster data is still loading (undefined)', () => {
    mockUseCluster.mockReturnValue({ data: undefined });
    renderDialog();
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });
});
