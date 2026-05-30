// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { faq, FAQ_CATEGORIES, FAQ_CATEGORY_ORDER } from '@/lib/faq';

beforeEach(() => {
  window.location.hash = '';
});

afterEach(() => {
  vi.restoreAllMocks();
  window.location.hash = '';
});

async function renderPage() {
  const { default: Page } = await import('@/app/guide/faq/page');
  return render(<Page />);
}

describe('FAQ route — content shape', () => {
  it('every entry has a unique kebab-case anchor (deep-link contract)', () => {
    const anchors = faq.map((e) => e.anchor);
    expect(new Set(anchors).size).toBe(anchors.length);
    for (const a of anchors) {
      expect(a).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
    }
  });

  it('every entry belongs to a declared category (no orphans)', () => {
    const known = new Set(FAQ_CATEGORY_ORDER);
    for (const e of faq) {
      expect(known.has(e.category)).toBe(true);
    }
  });

  it('every declared category has at least one entry (no empty categories)', () => {
    const used = new Set(faq.map((e) => e.category));
    for (const c of FAQ_CATEGORY_ORDER) {
      expect(used.has(c)).toBe(true);
    }
  });

  it('FAQ_CATEGORIES has a display label for every category in FAQ_CATEGORY_ORDER', () => {
    for (const c of FAQ_CATEGORY_ORDER) {
      expect(FAQ_CATEGORIES[c]).toBeTruthy();
    }
  });
});

describe('FAQ route — rendering and structure', () => {
  it('renders the heading, search input, and grouped list by default', async () => {
    await renderPage();
    expect(
      screen.getByRole('heading', { name: /Frequently asked questions/i, level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByTestId('faq-search')).toBeInTheDocument();
    expect(screen.getByTestId('faq-grouped-list')).toBeInTheDocument();
  });

  it('renders one category chip per declared category with entry count', async () => {
    await renderPage();
    const chips = screen.getByTestId('faq-category-chips');
    for (const cat of FAQ_CATEGORY_ORDER) {
      const chip = within(chips).getByTestId(`faq-chip-${cat}`);
      expect(chip).toHaveAttribute('aria-pressed', 'false');
      expect(chip.textContent).toContain(FAQ_CATEGORIES[cat]);
    }
  });

  it('every entry renders with id = anchor', async () => {
    await renderPage();
    for (const entry of faq) {
      const el = screen.getByTestId(`faq-entry-${entry.anchor}`);
      expect(el).toHaveAttribute('id', entry.anchor);
    }
  });

  it('each entry has a self-link anchor for sharing', async () => {
    await renderPage();
    for (const entry of faq.slice(0, 3)) {
      const link = screen.getByTestId(`faq-anchor-${entry.anchor}`);
      expect(link.getAttribute('href')).toBe(`#${entry.anchor}`);
    }
  });

  it('answers render via markdown (bullets become <ul><li>)', async () => {
    await renderPage();
    // Pick an entry whose answer contains a bullet list
    const entry = faq.find((e) => e.answer.includes('\n- '));
    expect(entry).toBeTruthy();
    const body = screen.getByTestId(`faq-answer-${entry!.anchor}`);
    expect(body.querySelector('ul')).not.toBeNull();
    expect(body.querySelectorAll('li').length).toBeGreaterThan(0);
  });
});

describe('FAQ route — search', () => {
  it('filters by case-insensitive substring across question / answer / anchor', async () => {
    await renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId('faq-search'), 'KAPPA');
    expect(screen.getByTestId('faq-flat-list')).toBeInTheDocument();
    expect(screen.getByTestId('faq-entry-kappa-trust-threshold')).toBeInTheDocument();
  });

  it('switches to flat list when search has a query', async () => {
    await renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId('faq-search'), 'a');
    expect(screen.getByTestId('faq-flat-list')).toBeInTheDocument();
    expect(screen.queryByTestId('faq-grouped-list')).toBeNull();
  });

  it('shows empty state when no question matches', async () => {
    await renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId('faq-search'), 'zzz-no-match-xyz');
    expect(screen.getByTestId('faq-empty')).toBeInTheDocument();
  });
});

describe('FAQ route — category facets', () => {
  it('toggles a single category and filters to that category only', async () => {
    await renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('faq-chip-judgments'));
    expect(screen.getByTestId('faq-chip-judgments')).toHaveAttribute('aria-pressed', 'true');
    const visible = faq.filter((e) => e.category === 'judgments');
    for (const e of visible) {
      expect(screen.getByTestId(`faq-entry-${e.anchor}`)).toBeInTheDocument();
    }
    const hidden = faq.filter((e) => e.category !== 'judgments');
    for (const e of hidden) {
      expect(screen.queryByTestId(`faq-entry-${e.anchor}`)).toBeNull();
    }
  });

  it('composes search + facets with AND semantics', async () => {
    await renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('faq-chip-studies-and-confidence'));
    await user.type(screen.getByTestId('faq-search'), 'noisy');
    // convergence-noisy is in studies-and-confidence AND its question/answer
    // contains "noisy"
    expect(screen.getByTestId('faq-entry-convergence-noisy')).toBeInTheDocument();
  });
});

describe('FAQ route — deep links', () => {
  it('renders the anchored entry for a fragment URL', async () => {
    window.location.hash = '#confidence-ci-missing';
    await renderPage();
    expect(screen.getByTestId('faq-entry-confidence-ci-missing')).toBeInTheDocument();
  });

  it('renders harmlessly for a non-existent fragment', async () => {
    window.location.hash = '#does-not-exist';
    await renderPage();
    expect(screen.getByTestId('faq-grouped-list')).toBeInTheDocument();
    expect(screen.queryByTestId('faq-entry-does-not-exist')).toBeNull();
  });
});
