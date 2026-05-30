/**
 * Unit tests for ClusterDetailSummary's target_filter rendering
 * (chore_cluster_detail_show_target_filter — bundled into the guide-01 regen
 * PR after the visual audit surfaced the missing field).
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ClusterDetailSummary } from '@/components/clusters/cluster-detail-summary';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { ClusterDetail } from '@/lib/api/clusters';

const BASE_CLUSTER: ClusterDetail = {
  id: 'c-1',
  name: 'acme-products-prod',
  engine_type: 'elasticsearch',
  environment: 'prod',
  base_url: 'http://elasticsearch:9200',
  auth_kind: 'es_basic',
  engine_config: null,
  notes: null,
  target_filter: null,
  created_at: '2026-05-21T00:00:00Z',
  health_check: {
    status: 'green',
    version: '9.4.0',
    checked_at: '2026-05-21T00:00:00Z',
    error: null,
  },
};

describe('ClusterDetailSummary — target_filter', () => {
  it('renders the glob value when set', () => {
    render(
      <TooltipProvider>
        <ClusterDetailSummary cluster={{ ...BASE_CLUSTER, target_filter: 'products*' }} />
      </TooltipProvider>,
    );
    expect(screen.getByText('Target filter')).toBeInTheDocument();
    expect(screen.getByText('products*')).toBeInTheDocument();
  });

  it('renders an em-dash placeholder when null', () => {
    render(
      <TooltipProvider>
        <ClusterDetailSummary cluster={BASE_CLUSTER} />
      </TooltipProvider>,
    );
    expect(screen.getByText('Target filter')).toBeInTheDocument();
    // The dd contains a muted "—" span when target_filter is null.
    const targetFilterLabel = screen.getByText('Target filter');
    const dd = targetFilterLabel.parentElement?.querySelector('dd');
    expect(dd?.textContent).toBe('—');
  });
});

// ---------------------------------------------------------------------------
// Story 3.2 / FR-7 — synthetic-data chip on cluster detail (surface #3)
// ---------------------------------------------------------------------------

function renderWithTooltip(cluster: ClusterDetail) {
  return render(
    <TooltipProvider>
      <ClusterDetailSummary cluster={cluster} />
    </TooltipProvider>,
  );
}

describe('ClusterDetailSummary — synthetic-data chip (FR-7 surface #3)', () => {
  it('shows the chip when cluster is a synthetic-UBI demo (acme)', () => {
    renderWithTooltip({ ...BASE_CLUSTER, name: 'acme-products-prod' });
    expect(screen.getByTestId('demo-badge-synthetic-ubi')).toBeInTheDocument();
  });

  it('does NOT show the chip on news-search-staging (demo cluster, no synthetic UBI)', () => {
    renderWithTooltip({ ...BASE_CLUSTER, name: 'news-search-staging' });
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });

  it('does NOT show the chip on a production (non-demo) cluster', () => {
    renderWithTooltip({ ...BASE_CLUSTER, name: 'production-real-cluster' });
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });
});
