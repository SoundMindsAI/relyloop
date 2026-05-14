import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { GuideViewer } from '@/components/guides/guide-viewer';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const METADATA = {
  title: 'Test guide',
  description: 'A two-slide test guide',
  order: 99,
  tags: ['test'],
  estimated_time: '1 minute',
  screenshots: [
    { file: '01-first.png', caption: 'First slide caption' },
    { file: '02-second.png', caption: 'Second slide caption' },
  ],
};

beforeEach(() => {
  // jsdom fetch resolves against http://localhost — register handlers
  // on both the relative path (used by the component) and the absolute URL.
  server.use(
    http.get('http://localhost/guides/test_guide/metadata.json', () => HttpResponse.json(METADATA)),
    http.get('/guides/test_guide/metadata.json', () => HttpResponse.json(METADATA)),
  );
});

afterEach(() => vi.clearAllMocks());

describe('<GuideViewer>', () => {
  it('renders the first slide after loading metadata', async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);

    await waitFor(() => expect(screen.getByTestId('guide-title')).toHaveTextContent('Test guide'));
    expect(screen.getByTestId('guide-slide-caption')).toHaveTextContent('First slide caption');
    expect(screen.getByTestId('guide-counter')).toHaveTextContent('1 / 2');
  });

  it('navigates forward + backward with the prev/next buttons', async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByTestId('guide-slide-caption')).toHaveTextContent('First slide caption'),
    );
    // Prev is disabled on the first slide.
    expect(screen.getByTestId('guide-prev')).toBeDisabled();

    fireEvent.click(screen.getByTestId('guide-next'));
    expect(screen.getByTestId('guide-slide-caption')).toHaveTextContent('Second slide caption');
    expect(screen.getByTestId('guide-counter')).toHaveTextContent('2 / 2');
    // Next is disabled on the last slide.
    expect(screen.getByTestId('guide-next')).toBeDisabled();

    fireEvent.click(screen.getByTestId('guide-prev'));
    expect(screen.getByTestId('guide-slide-caption')).toHaveTextContent('First slide caption');
  });

  it('navigates with arrow keys', async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getByTestId('guide-slide-caption')).toHaveTextContent('First slide caption'),
    );

    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(screen.getByTestId('guide-slide-caption')).toHaveTextContent('Second slide caption');

    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    expect(screen.getByTestId('guide-slide-caption')).toHaveTextContent('First slide caption');
  });

  it('surfaces a fetch error when metadata is missing', async () => {
    server.use(
      http.get('http://localhost/guides/missing_guide/metadata.json', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
      http.get('/guides/missing_guide/metadata.json', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    );

    wrap(<GuideViewer guideId="missing_guide" open={true} onOpenChange={vi.fn()} />);

    await waitFor(() => expect(screen.getByTestId('guide-error')).toBeVisible());
    expect(screen.getByTestId('guide-error')).toHaveTextContent(/HTTP 404/);
  });

  it('does not fetch when open=false', async () => {
    let fetchCount = 0;
    server.use(
      http.get('http://localhost/guides/test_guide/metadata.json', () => {
        fetchCount += 1;
        return HttpResponse.json(METADATA);
      }),
    );
    wrap(<GuideViewer guideId="test_guide" open={false} onOpenChange={vi.fn()} />);
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchCount).toBe(0);
  });
});
