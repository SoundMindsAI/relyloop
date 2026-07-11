// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ariaSortForColumn } from '@/components/common/data-table-sort-header';
import { MessageStream } from '@/components/chat/message-stream';
import { ResponsiveLayout } from '@/components/studies/search-space-builder/responsive-layout';

describe('chat stream is a live region', () => {
  it('MessageStream root is role=log aria-live=polite so streaming is announced', () => {
    render(<MessageStream messages={[]} />);
    const region = screen.getByTestId('message-stream');
    expect(region).toHaveAttribute('role', 'log');
    expect(region).toHaveAttribute('aria-live', 'polite');
  });
});

describe('search-space builder tab widget ARIA', () => {
  function renderTabs() {
    return render(<ResponsiveLayout builder={<div>BUILDER</div>} textarea={<div>JSON</div>} />);
  }

  it('tabs reference their panels and panels reference their tabs', () => {
    renderTabs();
    const builderTab = screen.getByTestId('cs-builder-tab-builder');
    expect(builderTab).toHaveAttribute('role', 'tab');
    expect(builderTab).toHaveAttribute('aria-controls', 'cs-builder-panel-builder');

    const builderPanel = screen.getByTestId('cs-builder-slot-builder');
    expect(builderPanel).toHaveAttribute('role', 'tabpanel');
    expect(builderPanel).toHaveAttribute('aria-labelledby', 'cs-builder-tab-builder');
  });

  it('ArrowRight moves the active tab (roving selection)', () => {
    renderTabs();
    const builderTab = screen.getByTestId('cs-builder-tab-builder');
    expect(builderTab).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(builderTab, { key: 'ArrowRight' });
    expect(screen.getByTestId('cs-builder-tab-json')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('cs-builder-tab-builder')).toHaveAttribute('aria-selected', 'false');
  });
});

describe('ariaSortForColumn', () => {
  it('maps active direction to the aria-sort token for the matching column', () => {
    expect(ariaSortForColumn('name:asc', 'name')).toBe('ascending');
    expect(ariaSortForColumn('name:desc', 'name')).toBe('descending');
    expect(ariaSortForColumn('other:asc', 'name')).toBe('none');
    expect(ariaSortForColumn(null, 'name')).toBe('none');
  });
});
