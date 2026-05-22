import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';

// Mock the existing useClusters hook so we control returned cluster data.
// Forwarding params lets tests assert the FR-2 contract that the banner
// calls useClusters with { sort: 'name:asc', limit: 200 }.
const mockUseClusters = vi.fn();
vi.mock('@/lib/api/clusters', () => ({
  useClusters: (params: unknown) => mockUseClusters(params),
}));

// Mock the safe-localStorage wrapper so we don't depend on jsdom's storage.
const mockGet = vi.fn();
const mockSet = vi.fn();
vi.mock('@/lib/safe-local-storage', () => ({
  safeLocalStorageGet: (key: string) => mockGet(key),
  safeLocalStorageSet: (key: string, value: string) => mockSet(key, value),
}));

// Imported AFTER mocks so the mocked modules are wired in.
import { DemoDataBanner } from '@/components/dashboard/demo-data-banner';

const DISMISS_KEY = 'relyloop.home-first-run-demo-nudge.dismissed';

function clusterRow(name: string) {
  return {
    id: `id-${name}`,
    name,
    engine_type: 'elasticsearch',
    environment: 'prod',
    base_url: 'http://elasticsearch:9200',
    auth_kind: 'es_basic',
    target_filter: null,
    created_at: '2026-05-21T00:00:00Z',
    health_check: {
      status: 'green',
      version: '9.0.0',
      checked_at: '2026-05-21T00:00:00Z',
      error: null,
    },
  };
}

function renderBanner() {
  return render(
    <TooltipProvider>
      <DemoDataBanner />
    </TooltipProvider>,
  );
}

describe('<DemoDataBanner />', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockSet.mockReset();
    mockUseClusters.mockReset();
    // Default: localStorage returns null (not dismissed); set true returns true.
    mockGet.mockReturnValue(null);
    mockSet.mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders when demos>0 + not dismissed', async () => {
    mockUseClusters.mockReturnValue({
      data: { data: [clusterRow('acme-products-prod'), clusterRow('my-own-cluster')] },
      isError: false,
    });
    renderBanner();
    expect(await screen.findByTestId('demo-data-banner')).toBeInTheDocument();
    expect(screen.getByText("You're set up with demo data.")).toBeInTheDocument();
    // Body contains the present demo slug as a <code>.
    expect(screen.getByText('acme-products-prod')).toBeInTheDocument();
    // Non-demo cluster name is NOT in the body.
    expect(screen.queryByText('my-own-cluster')).not.toBeInTheDocument();
    // FR-2 contract: the banner fetches with sort=name:asc, limit=200.
    expect(mockUseClusters).toHaveBeenCalledWith({ sort: 'name:asc', limit: 200 });
  });

  it('returns null when no demo slugs are present', async () => {
    mockUseClusters.mockReturnValue({
      data: { data: [clusterRow('my-own-cluster'), clusterRow('another')] },
      isError: false,
    });
    const { container } = renderBanner();
    // Wait a microtask for the mount effect to run.
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="demo-data-banner"]')).toBeNull();
  });

  it('returns null when localStorage dismissal is set to "1"', async () => {
    mockGet.mockReturnValue('1');
    mockUseClusters.mockReturnValue({
      data: { data: [clusterRow('acme-products-prod')] },
      isError: false,
    });
    const { container } = renderBanner();
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="demo-data-banner"]')).toBeNull();
  });

  it('Dismiss click updates state AND writes localStorage', async () => {
    const user = userEvent.setup();
    mockUseClusters.mockReturnValue({
      data: { data: [clusterRow('acme-products-prod')] },
      isError: false,
    });
    renderBanner();
    const banner = await screen.findByTestId('demo-data-banner');
    expect(banner).toBeInTheDocument();
    await user.click(screen.getByTestId('demo-data-banner-dismiss'));
    expect(mockSet).toHaveBeenCalledWith(DISMISS_KEY, '1');
    expect(screen.queryByTestId('demo-data-banner')).not.toBeInTheDocument();
  });

  it('survives safeLocalStorageGet returning null AND safeLocalStorageSet returning false (throwing-storage analogue)', async () => {
    mockGet.mockReturnValue(null); // emulates throwing-getItem path returning null
    mockSet.mockReturnValue(false); // emulates QuotaExceededError on write
    mockUseClusters.mockReturnValue({
      data: { data: [clusterRow('acme-products-prod')] },
      isError: false,
    });
    const user = userEvent.setup();
    renderBanner();
    const banner = await screen.findByTestId('demo-data-banner');
    expect(banner).toBeInTheDocument();
    await user.click(screen.getByTestId('demo-data-banner-dismiss'));
    // Banner still unmounts even though the write returned false — component
    // state is the source of truth for visibility.
    expect(screen.queryByTestId('demo-data-banner')).not.toBeInTheDocument();
  });

  it('returns null when the clusters query errors', async () => {
    mockUseClusters.mockReturnValue({
      data: undefined,
      isError: true,
    });
    const { container } = renderBanner();
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="demo-data-banner"]')).toBeNull();
  });

  it('AC-9: CTA has href="/studies" and clicking it does NOT modify localStorage', async () => {
    mockUseClusters.mockReturnValue({
      data: { data: [clusterRow('acme-products-prod')] },
      isError: false,
    });
    renderBanner();
    const cta = await screen.findByTestId('demo-data-banner-cta');
    expect(cta.getAttribute('href')).toBe('/studies');
    // Click without preventing default — Link doesn't actually navigate in jsdom,
    // but should not invoke any localStorage side effects either way.
    await userEvent.setup().click(cta);
    expect(mockSet).not.toHaveBeenCalled();
  });
});
