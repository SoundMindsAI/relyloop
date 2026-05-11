import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import HomePage from '@/app/page';

describe('HomePage (welcome stub — Story 1.2)', () => {
  it('renders the welcome heading', () => {
    render(<HomePage />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Welcome to RelyLoop');
  });

  it('renders quick-link buttons to Studies / Clusters / Query Sets', () => {
    render(<HomePage />);
    expect(screen.getByRole('link', { name: /studies/i })).toHaveAttribute('href', '/studies');
    expect(screen.getByRole('link', { name: /clusters/i })).toHaveAttribute('href', '/clusters');
    expect(screen.getByRole('link', { name: /query sets/i })).toHaveAttribute(
      'href',
      '/query-sets',
    );
  });
});
