import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Safety-filter test for /guide/glossary.
 *
 * Lives in its own file because we mock `@/lib/glossary` to inject a
 * hostile entry, and `vi.doMock` registrations leak across tests in the
 * same file even with `vi.resetModules()` + `vi.restoreAllMocks()`. Isolating
 * this in its own file ensures the rest of the suite sees the real 109-entry
 * glossary.
 *
 * Real glossary content cannot carry `<script>`/`<iframe>`/`<style>` because
 * the existing parity test at `ui/src/__tests__/lib/glossary.test.ts`
 * forbids those strings — the only way to exercise the runtime
 * `disallowedElements` filter is with mocked content.
 */

beforeEach(() => {
  window.location.hash = '';
  vi.doMock('@/lib/glossary', () => ({
    glossary: {
      'test.malicious': {
        short: 'short safe text',
        long: '**bold** safe text. <script>alert(1)</script> after <iframe src="x"></iframe> end <style>body{color:red}</style>',
      },
    },
  }));
});

afterEach(() => {
  vi.doUnmock('@/lib/glossary');
  vi.resetModules();
  window.location.hash = '';
});

describe('Glossary route — markdown rendering safety', () => {
  it('does not render <script>, <iframe>, or <style> elements when long content contains them', async () => {
    const { default: Page } = await import('@/app/guide/glossary/page');
    const { container } = render(<Page />);
    expect(container.querySelectorAll('script').length).toBe(0);
    expect(container.querySelectorAll('iframe').length).toBe(0);
    expect(container.querySelectorAll('style').length).toBe(0);
  });

  it('preserves safe markdown formatting (bold) in the same hostile payload', async () => {
    const { default: Page } = await import('@/app/guide/glossary/page');
    render(<Page />);
    const entry = screen.getByTestId('glossary-entry-test.malicious');
    expect(entry).toBeInTheDocument();
    expect(entry.querySelector('strong')).not.toBeNull();
    expect(entry.querySelector('strong')?.textContent).toBe('bold');
  });
});
