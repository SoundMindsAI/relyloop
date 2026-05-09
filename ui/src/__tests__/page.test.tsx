import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import HomePage from '@/app/page';

describe('HomePage (placeholder)', () => {
  it('renders the heading "RelyLoop is running"', () => {
    render(<HomePage />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('RelyLoop is running');
  });

  it('renders a docs link pointing at the public repo', () => {
    render(<HomePage />);
    const link = screen.getByRole('link', { name: /docs/i });
    expect(link).toHaveAttribute('href', 'https://github.com/SoundMindsAI/relyloop/tree/main/docs');
  });
});
