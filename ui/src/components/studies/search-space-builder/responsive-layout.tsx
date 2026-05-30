// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<ResponsiveLayout>` — split/tab responsive Step-4 layout (Story 3.1, FR-8).
 *
 * ≥1024px (Tailwind `lg:`): split view — builder LEFT, textarea RIGHT
 * via `lg:grid-cols-2`. <1024px: tab toggle "Builder | JSON" with
 * Builder active by default; tab state resets on every mount (per
 * spec §4 anti-pattern: do not persist builder UI state across modal
 * closes).
 *
 * The textarea stays in the DOM at every viewport. The inactive tab on
 * narrow viewports gets `className="hidden"` (CSS `display: none`), NOT
 * conditional rendering. This preserves React Hook Form's `register`
 * reference and keeps `getByTestId('cs-search-space')` resolving in
 * existing modal tests.
 */

import * as React from 'react';

export interface ResponsiveLayoutProps {
  builder: React.ReactNode;
  textarea: React.ReactNode;
}

export function ResponsiveLayout({ builder, textarea }: ResponsiveLayoutProps): React.ReactElement {
  const [activeTab, setActiveTab] = React.useState<'builder' | 'json'>('builder');

  return (
    <div className="space-y-3">
      {/* Tab toggle: only visible <1024px (hidden at lg: breakpoint). */}
      <div
        className="lg:hidden flex gap-2 border-b border-border"
        role="tablist"
        data-testid="cs-builder-tab-toggle"
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'builder'}
          onClick={() => setActiveTab('builder')}
          data-testid="cs-builder-tab-builder"
          className={
            activeTab === 'builder'
              ? 'border-b-2 border-primary px-3 py-1.5'
              : 'px-3 py-1.5 text-muted-foreground'
          }
        >
          Builder
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'json'}
          onClick={() => setActiveTab('json')}
          data-testid="cs-builder-tab-json"
          className={
            activeTab === 'json'
              ? 'border-b-2 border-primary px-3 py-1.5'
              : 'px-3 py-1.5 text-muted-foreground'
          }
        >
          JSON
        </button>
      </div>

      {/* Split-view at ≥1024px; tabbed below. CSS `hidden` on inactive
          tab (NOT conditional rendering) preserves the textarea's
          RHF register binding + existing test selectors. */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div
          className={activeTab === 'json' ? 'hidden lg:block' : 'lg:block'}
          data-testid="cs-builder-slot-builder"
        >
          {builder}
        </div>
        <div
          className={activeTab === 'builder' ? 'hidden lg:block' : 'lg:block'}
          data-testid="cs-builder-slot-json"
        >
          {textarea}
        </div>
      </div>
    </div>
  );
}
