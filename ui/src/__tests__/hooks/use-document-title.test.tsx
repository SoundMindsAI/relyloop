// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { useDocumentTitle } from '@/hooks/use-document-title';

function Titled({ title }: { title: string | null }) {
  useDocumentTitle(title);
  return null;
}

afterEach(() => {
  document.title = 'RelyLoop';
});

describe('useDocumentTitle', () => {
  it('sets "<title> · RelyLoop" and restores the previous title on unmount', () => {
    document.title = 'RelyLoop';
    const { unmount } = render(<Titled title="Studies" />);
    expect(document.title).toBe('Studies · RelyLoop');
    unmount();
    expect(document.title).toBe('RelyLoop');
  });

  it('leaves the title untouched when passed null (e.g. entity still loading)', () => {
    document.title = 'RelyLoop';
    render(<Titled title={null} />);
    expect(document.title).toBe('RelyLoop');
  });
});
