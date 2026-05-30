// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { MarkdownDoc } from '@/components/guides/markdown-doc';

const SAMPLE_MARKDOWN = `# Welcome

This is a [relative link](../01_architecture/optimization.md) and an
[absolute link](https://example.com/foo). Also a [parent ref](../../README.md).

## Subheading

- bullet one
- bullet two
`;

function wrap(node: ReactNode) {
  return render(<>{node}</>);
}

beforeEach(() => {
  // Register handlers for both URL shapes — jsdom resolves the relative
  // path against window.location which can vary by test runner config.
  const sampleResp = () =>
    HttpResponse.text(SAMPLE_MARKDOWN, { headers: { 'Content-Type': 'text/markdown' } });
  server.use(
    http.get('/docs/sample.md', sampleResp),
    http.get('http://localhost/docs/sample.md', sampleResp),
    http.get('http://localhost:3000/docs/sample.md', sampleResp),
    http.get('/docs/tutorial-first-study.md', sampleResp),
    http.get('http://localhost/docs/tutorial-first-study.md', sampleResp),
  );
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem('relyloop.guide-viewer.text-size');
  }
});

afterEach(() => vi.clearAllMocks());

describe('<MarkdownDoc>', () => {
  it('renders the markdown content after fetch', async () => {
    wrap(<MarkdownDoc file="sample.md" title="Sample doc" />);

    expect(screen.getByText('Sample doc')).toBeVisible();
    // Loading state first
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Welcome' })).toBeVisible();
    });
    expect(screen.getByText('bullet one')).toBeVisible();
    expect(screen.getByText('bullet two')).toBeVisible();
  });

  it('rewrites repo-relative links to GitHub blob URLs', async () => {
    wrap(<MarkdownDoc file="sample.md" title="Sample" />);

    await waitFor(() => expect(screen.getByRole('link', { name: 'relative link' })).toBeVisible());

    const relLink = screen.getByRole('link', { name: 'relative link' });
    expect(relLink).toHaveAttribute(
      'href',
      'https://github.com/SoundMindsAI/relyloop/blob/main/docs/01_architecture/optimization.md',
    );

    // `../../README.md` from docs/08_guides/ resolves up two levels to the
    // repo root (README.md, not docs/README.md).
    const parentLink = screen.getByRole('link', { name: 'parent ref' });
    expect(parentLink).toHaveAttribute(
      'href',
      'https://github.com/SoundMindsAI/relyloop/blob/main/README.md',
    );
  });

  it('leaves absolute URLs unchanged', async () => {
    wrap(<MarkdownDoc file="sample.md" title="Sample" />);
    await waitFor(() => expect(screen.getByRole('link', { name: 'absolute link' })).toBeVisible());
    expect(screen.getByRole('link', { name: 'absolute link' })).toHaveAttribute(
      'href',
      'https://example.com/foo',
    );
  });

  it('surfaces a fetch error when the markdown file is missing', async () => {
    const missingResp = () => HttpResponse.text('not found', { status: 404 });
    server.use(
      http.get('/docs/missing.md', missingResp),
      http.get('http://localhost/docs/missing.md', missingResp),
    );
    wrap(<MarkdownDoc file="missing.md" title="Missing" />);
    await waitFor(() => expect(screen.getByTestId('markdown-doc-error')).toBeVisible());
    expect(screen.getByTestId('markdown-doc-error')).toHaveTextContent(/HTTP 404/);
  });

  it('text-size toggle cycles sm → base → lg and persists to localStorage', async () => {
    wrap(<MarkdownDoc file="sample.md" title="Sample" />);
    await waitFor(() =>
      expect(screen.getByTestId('markdown-doc')).toHaveAttribute('data-text-size', 'base'),
    );

    fireEvent.click(screen.getByTestId('markdown-doc-text-size'));
    expect(screen.getByTestId('markdown-doc')).toHaveAttribute('data-text-size', 'lg');
    expect(window.localStorage.getItem('relyloop.guide-viewer.text-size')).toBe('lg');

    fireEvent.click(screen.getByTestId('markdown-doc-text-size'));
    expect(screen.getByTestId('markdown-doc')).toHaveAttribute('data-text-size', 'sm');
  });

  it('wide-column toggle flips data-wide attribute', async () => {
    wrap(<MarkdownDoc file="sample.md" title="Sample" />);
    await waitFor(() => expect(screen.getByTestId('markdown-doc')).toBeVisible());
    expect(screen.getByTestId('markdown-doc')).toHaveAttribute('data-wide', 'false');

    fireEvent.click(screen.getByTestId('markdown-doc-wide'));
    expect(screen.getByTestId('markdown-doc')).toHaveAttribute('data-wide', 'true');
  });

  it('hydrates text-size from localStorage on mount', async () => {
    window.localStorage.setItem('relyloop.guide-viewer.text-size', 'lg');
    wrap(<MarkdownDoc file="sample.md" title="Sample" />);
    await waitFor(() =>
      expect(screen.getByTestId('markdown-doc')).toHaveAttribute('data-text-size', 'lg'),
    );
  });

  it('View on GitHub link points at the source path under docs/08_guides/', async () => {
    wrap(<MarkdownDoc file="tutorial-first-study.md" title="Tutorial" />);
    await waitFor(() => expect(screen.getByTestId('markdown-doc-github')).toBeVisible());
    expect(screen.getByTestId('markdown-doc-github')).toHaveAttribute(
      'href',
      'https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/tutorial-first-study.md',
    );
  });
});
