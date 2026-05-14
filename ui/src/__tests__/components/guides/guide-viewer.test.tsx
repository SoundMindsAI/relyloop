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
  video: 'walkthrough.webm',
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

afterEach(() => {
  vi.clearAllMocks();
  // Reset preferences so tests don't leak state across cases.
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem('relyloop.guide-viewer.fullscreen');
    window.localStorage.removeItem('relyloop.guide-viewer.text-size');
  }
});

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

  it('fullscreen toggle flips data-fullscreen + persists to localStorage', async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('guide-viewer')).toBeVisible());
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-fullscreen', 'false');

    fireEvent.click(screen.getByTestId('guide-fullscreen'));
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-fullscreen', 'true');
    expect(window.localStorage.getItem('relyloop.guide-viewer.fullscreen')).toBe('1');

    fireEvent.click(screen.getByTestId('guide-fullscreen'));
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-fullscreen', 'false');
    expect(window.localStorage.getItem('relyloop.guide-viewer.fullscreen')).toBe('0');
  });

  it('text-size toggle cycles sm → base → lg → sm and persists', async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('guide-viewer')).toBeVisible());
    // Default is base (medium).
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-text-size', 'base');

    fireEvent.click(screen.getByTestId('guide-text-size'));
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-text-size', 'lg');
    expect(window.localStorage.getItem('relyloop.guide-viewer.text-size')).toBe('lg');

    fireEvent.click(screen.getByTestId('guide-text-size'));
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-text-size', 'sm');

    fireEvent.click(screen.getByTestId('guide-text-size'));
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-text-size', 'base');
  });

  it('hydrates fullscreen + text-size from localStorage on mount', async () => {
    window.localStorage.setItem('relyloop.guide-viewer.fullscreen', '1');
    window.localStorage.setItem('relyloop.guide-viewer.text-size', 'lg');

    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('guide-viewer')).toBeVisible());
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-fullscreen', 'true');
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-text-size', 'lg');
  });

  it('caption announces slide position to screen readers via sr-only prefix', async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('guide-slide-caption')).toBeVisible());
    const caption = screen.getByTestId('guide-slide-caption');
    expect(caption).toHaveAttribute('aria-live', 'polite');
    // Sr-only span contains "Slide N of M: " prefix.
    expect(caption.textContent).toMatch(/^Slide 1 of 2: First slide caption$/);
  });

  it('View full image link points at the raw PNG and opens in a new tab', async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('guide-view-full')).toBeVisible());
    const link = screen.getByTestId('guide-view-full');
    expect(link).toHaveAttribute('href', '/guides/test_guide/01-first.png');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('renders Slides / Video toggle when metadata.video is set; default is Slides', async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('guide-mode-toggle')).toBeVisible());
    expect(screen.getByTestId('guide-mode-slides')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('guide-mode-video')).toHaveAttribute('aria-pressed', 'false');
    // Slide content visible, video container hidden.
    expect(screen.getByTestId('guide-slide-image')).toBeVisible();
    expect(screen.queryByTestId('guide-video')).toBeNull();
  });

  it('switches to Video mode and renders <video> with the right src', async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('guide-mode-video')).toBeVisible());

    fireEvent.click(screen.getByTestId('guide-mode-video'));
    expect(screen.getByTestId('guide-mode-video')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('guide-mode-slides')).toHaveAttribute('aria-pressed', 'false');
    const video = screen.getByTestId('guide-video') as HTMLVideoElement;
    expect(video).toBeVisible();
    expect(video).toHaveAttribute('src', '/guides/test_guide/walkthrough.webm');
    // Slide UI is hidden in video mode.
    expect(screen.queryByTestId('guide-slide-image')).toBeNull();
    expect(screen.queryByTestId('guide-prev')).toBeNull();
    expect(screen.queryByTestId('guide-next')).toBeNull();
  });

  it('hides the Slides / Video toggle when metadata.video is absent', async () => {
    const metaWithoutVideo = { ...METADATA };
    delete (metaWithoutVideo as { video?: string }).video;
    server.use(
      http.get('http://localhost/guides/no_video_guide/metadata.json', () =>
        HttpResponse.json(metaWithoutVideo),
      ),
      http.get('/guides/no_video_guide/metadata.json', () => HttpResponse.json(metaWithoutVideo)),
    );
    wrap(<GuideViewer guideId="no_video_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('guide-slide-image')).toBeVisible());
    expect(screen.queryByTestId('guide-mode-toggle')).toBeNull();
  });

  it("'f' keyboard shortcut toggles fullscreen", async () => {
    wrap(<GuideViewer guideId="test_guide" open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('guide-viewer')).toBeVisible());

    fireEvent.keyDown(window, { key: 'f' });
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-fullscreen', 'true');

    fireEvent.keyDown(window, { key: 'F' });
    expect(screen.getByTestId('guide-viewer')).toHaveAttribute('data-fullscreen', 'false');
  });
});
