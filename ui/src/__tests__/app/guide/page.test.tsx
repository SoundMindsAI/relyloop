import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import GuideCatalogPage from '@/app/guide/page';
import { DOC_REGISTRY, GUIDE_REGISTRY } from '@/components/guides/guide-types';
import { glossary } from '@/lib/glossary';

describe('Guide catalog page', () => {
  it('renders three sections: long-form docs, walkthroughs, and glossary', () => {
    render(<GuideCatalogPage />);
    expect(screen.getByTestId('doc-section')).toBeInTheDocument();
    expect(screen.getByTestId('walkthrough-section')).toBeInTheDocument();
    expect(screen.getByTestId('glossary-section')).toBeInTheDocument();
  });

  it('preserves every existing DOC_REGISTRY + GUIDE_REGISTRY tile (no regression)', () => {
    render(<GuideCatalogPage />);
    for (const doc of DOC_REGISTRY) {
      expect(screen.getByTestId(`doc-card-${doc.slug}`)).toBeInTheDocument();
    }
    for (const guide of GUIDE_REGISTRY) {
      expect(screen.getByTestId(`guide-card-${guide.id}`)).toBeInTheDocument();
    }
  });

  it('renders the glossary card linking to /guide/glossary with dynamic count', () => {
    render(<GuideCatalogPage />);
    const card = screen.getByTestId('glossary-card');
    expect(card.tagName).toBe('A');
    expect(card.getAttribute('href')).toBe('/guide/glossary');
    const totalCount = Object.keys(glossary).length;
    const categoryCount = new Set(Object.keys(glossary).map((k) => k.split('.')[0])).size;
    expect(card.textContent).toContain(`${totalCount} terms`);
    expect(card.textContent).toContain(`${categoryCount} categories`);
  });
});
