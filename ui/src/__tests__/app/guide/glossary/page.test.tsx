// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { glossary } from '@/lib/glossary';

const TOTAL = Object.keys(glossary).length;
const CATEGORIES = Array.from(new Set(Object.keys(glossary).map((k) => k.split('.')[0]))).sort();

beforeEach(() => {
  // Always reset hash before each test so the deep-link useEffect doesn't fire.
  window.location.hash = '';
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.resetModules();
  window.location.hash = '';
});

async function renderPage() {
  const { default: Page } = await import('@/app/guide/glossary/page');
  return render(<Page />);
}

describe('Glossary route — rendering and structure', () => {
  it('renders the page heading, search input, and the full entry list by default', async () => {
    await renderPage();
    expect(screen.getByRole('heading', { name: 'Glossary', level: 1 })).toBeInTheDocument();
    const search = screen.getByTestId('glossary-search');
    expect(search).toBeInTheDocument();
    expect(search).toHaveAttribute('aria-label', 'Search glossary');
    expect(search.getAttribute('placeholder')).toMatch(/Search \d+ terms…/);
    expect(screen.getByTestId('glossary-grouped-list')).toBeInTheDocument();
  });

  it('renders one category chip per top-level key prefix with entry count', async () => {
    await renderPage();
    const chips = screen.getByTestId('glossary-category-chips');
    for (const cat of CATEGORIES) {
      const chip = within(chips).getByTestId(`glossary-chip-${cat}`);
      expect(chip).toHaveAttribute('aria-pressed', 'false');
      expect(chip.textContent).toMatch(/\(\d+\)/);
    }
  });

  it('renders each glossary entry with id = key (anchor target for deep links)', async () => {
    await renderPage();
    for (const key of Object.keys(glossary).slice(0, 5)) {
      const entry = screen.getByTestId(`glossary-entry-${key}`);
      expect(entry).toBeInTheDocument();
      expect(entry).toHaveAttribute('id', key);
    }
  });

  it('renders short and long content according to entry shape', async () => {
    await renderPage();
    // study.metric is long-only; should render its body via markdown
    const longOnly = screen.getByTestId('glossary-entry-study.metric');
    expect(within(longOnly).getByTestId('glossary-entry-study.metric-long')).toBeInTheDocument();
    // The long body lists each metric on its own bullet; pick a phrase
    // unique to one bullet (NDCG entry: "rewards placing relevant docs").
    expect(within(longOnly).getByText(/Rewards placing relevant docs/i)).toBeInTheDocument();

    // study.search_space is dual — both short and long appear
    const dual = screen.getByTestId('glossary-entry-study.search_space');
    expect(dual.textContent).toMatch(/parameters the study will tune/i);
    expect(within(dual).getByTestId('glossary-entry-study.search_space-long')).toBeInTheDocument();
  });
});

describe('Glossary route — search', () => {
  it('filters by case-insensitive substring across key / short / long', async () => {
    await renderPage();
    const user = userEvent.setup();
    const search = screen.getByTestId('glossary-search');
    await user.type(search, 'NDCG');
    // study.metric.ndcg has the key match
    expect(screen.getByTestId('glossary-entry-study.metric.ndcg')).toBeInTheDocument();
    // study.metric mentions "NDCG" in its long body
    expect(screen.getByTestId('glossary-entry-study.metric')).toBeInTheDocument();
    // Unrelated entries are removed from the DOM
    expect(screen.queryByTestId('glossary-entry-cluster.auth_kind')).toBeNull();
  });

  it('switches to flat list (no group headers) when search has a query', async () => {
    await renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId('glossary-search'), 'a');
    expect(screen.getByTestId('glossary-flat-list')).toBeInTheDocument();
    expect(screen.queryByTestId('glossary-grouped-list')).toBeNull();
  });

  it('shows the empty state when no entry matches', async () => {
    await renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId('glossary-search'), 'zzz-no-match-xyz');
    expect(screen.getByTestId('glossary-empty')).toBeInTheDocument();
    expect(screen.getByText('No terms match.')).toBeInTheDocument();
  });

  it('clearing the search restores the full list', async () => {
    await renderPage();
    const user = userEvent.setup();
    const search = screen.getByTestId('glossary-search');
    await user.type(search, 'ndcg');
    expect(screen.queryByTestId('glossary-entry-cluster.auth_kind')).toBeNull();
    await user.clear(search);
    expect(screen.getByTestId('glossary-entry-cluster.auth_kind')).toBeInTheDocument();
  });
});

describe('Glossary route — category facets', () => {
  it('toggles a single category and filters to that prefix only', async () => {
    await renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('glossary-chip-confidence'));
    expect(screen.getByTestId('glossary-chip-confidence')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('glossary-entry-confidence.ci_95')).toBeInTheDocument();
    // study.* entries are removed
    expect(screen.queryByTestId('glossary-entry-study.metric')).toBeNull();
  });

  it('toggling all chips off restores the full list (zero-selected == no facet filter)', async () => {
    await renderPage();
    const user = userEvent.setup();
    const chip = screen.getByTestId('glossary-chip-confidence');
    await user.click(chip);
    expect(screen.queryByTestId('glossary-entry-study.metric')).toBeNull();
    await user.click(chip);
    expect(screen.getByTestId('glossary-entry-study.metric')).toBeInTheDocument();
  });

  it('composes search + facets with AND semantics', async () => {
    await renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('glossary-chip-study'));
    await user.type(screen.getByTestId('glossary-search'), 'metric');
    // study.metric matches (study category + 'metric' keyword)
    expect(screen.getByTestId('glossary-entry-study.metric')).toBeInTheDocument();
    // confidence.per_query_outcomes mentions "metric" but is in confidence category — excluded
    expect(screen.queryByTestId('glossary-entry-confidence.per_query_outcomes')).toBeNull();
  });
});

describe('Glossary route — deep-link anchors', () => {
  it('clears active search/facet filters when the URL has a fragment so anchored entry is visible', async () => {
    // Set hash BEFORE first render so the useEffect can read it on mount.
    window.location.hash = '#study.metric.ndcg';
    await renderPage();
    // Filters should reset to defaults; full grouped list rendered.
    expect(screen.getByTestId('glossary-grouped-list')).toBeInTheDocument();
    expect(screen.getByTestId('glossary-entry-study.metric.ndcg')).toBeInTheDocument();
    // Search input should be empty.
    expect((screen.getByTestId('glossary-search') as HTMLInputElement).value).toBe('');
  });

  it('renders harmlessly for a non-existent fragment', async () => {
    window.location.hash = '#does.not.exist';
    await renderPage();
    expect(screen.getByTestId('glossary-grouped-list')).toBeInTheDocument();
    expect(screen.queryByTestId('glossary-entry-does.not.exist')).toBeNull();
  });
});

describe('Glossary route — counts', () => {
  it('the placeholder reports the total entry count', async () => {
    await renderPage();
    expect(
      (screen.getByTestId('glossary-search') as HTMLInputElement).getAttribute('placeholder'),
    ).toBe(`Search ${TOTAL} terms…`);
  });

  it('the chip counts sum to the total entry count', async () => {
    await renderPage();
    const chips = screen.getByTestId('glossary-category-chips');
    const counts = within(chips)
      .getAllByRole('button')
      .map((b) => {
        const m = b.textContent?.match(/\((\d+)\)/);
        return m ? Number(m[1]) : 0;
      });
    const sum = counts.reduce((a, b) => a + b, 0);
    expect(sum).toBe(TOTAL);
  });
});
