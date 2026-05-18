import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { UseQueryResult } from '@tanstack/react-query';

import { EntitySelect, type EntityStatus } from '@/components/common/entity-select';
import type { ApiError } from '@/lib/api-errors';

/**
 * Unit tests for the EntitySelect primitive (chore_form_dropdown_primitive Story 1.1).
 *
 * The primitive consumes `useEntities()` as a value, so tests inject a
 * synchronous fake hook rather than wiring up `QueryClientProvider` + msw.
 * Modal-level integration tests (Stories 2.1-2.4) exercise the primitive
 * through real TanStack hooks; this file pins primitive-internal behavior.
 */

interface Fixture {
  id: string;
  name: string;
  health?: EntityStatus;
}

function buildHook(
  data: Fixture[] | undefined,
  opts: { isLoading?: boolean; isError?: boolean; refetch?: () => void } = {},
) {
  const result = {
    data: data === undefined ? undefined : { data, next_cursor: null, has_more: false },
    isLoading: opts.isLoading ?? false,
    isError: opts.isError ?? false,
    refetch: opts.refetch ?? vi.fn(),
  };
  return () => result as unknown as UseQueryResult<{ data: Fixture[] }, ApiError>;
}

const FIXTURES_THREE: Fixture[] = [
  { id: 'e1', name: 'Alpha' },
  { id: 'e2', name: 'Bravo' },
  { id: 'e3', name: 'Charlie' },
];

describe('EntitySelect — baseline rendering', () => {
  it('renders the placeholder when value is undefined and data is loaded', () => {
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(FIXTURES_THREE)}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        placeholder="Pick one"
        data-testid="es-test"
      />,
    );
    const trigger = screen.getByTestId('es-test');
    expect(trigger.tagName).toBe('BUTTON');
    expect(trigger).toHaveTextContent('Pick one');
  });

  it('passes id through to the trigger button', () => {
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(FIXTURES_THREE)}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        id="cs-cluster"
        data-testid="cs-cluster"
      />,
    );
    expect(screen.getByTestId('cs-cluster')).toHaveAttribute('id', 'cs-cluster');
  });

  it('renders the selected entity label when value matches a loaded id', () => {
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(FIXTURES_THREE)}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value="e2"
        onChange={vi.fn()}
        data-testid="es-selected"
      />,
    );
    expect(screen.getByTestId('es-selected')).toHaveTextContent('Bravo');
  });

  it('fires onChange with the selected entity id on click', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(FIXTURES_THREE)}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={onChange}
        data-testid="es-click"
      />,
    );
    await user.click(screen.getByTestId('es-click'));
    await user.click(await screen.findByRole('option', { name: /charlie/i }));
    expect(onChange).toHaveBeenCalledWith('e3');
  });
});

describe('EntitySelect — loading state (FR-2)', () => {
  it('renders a disabled trigger with the default loading placeholder', () => {
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(undefined, { isLoading: true })}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        data-testid="es-loading"
      />,
    );
    const trigger = screen.getByTestId('es-loading');
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveTextContent('Loading…');
  });

  it('honors a custom loadingPlaceholder', () => {
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(undefined, { isLoading: true })}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        loadingPlaceholder="Fetching clusters…"
        data-testid="es-loading-custom"
      />,
    );
    expect(screen.getByTestId('es-loading-custom')).toHaveTextContent('Fetching clusters…');
  });
});

describe('EntitySelect — error state (FR-3)', () => {
  it('renders a disabled trigger plus a Retry button that calls refetch()', async () => {
    const refetch = vi.fn();
    const user = userEvent.setup();
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(undefined, { isError: true, refetch })}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        data-testid="es-error"
      />,
    );
    const trigger = screen.getByTestId('es-error');
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveTextContent(/Failed to load/);
    const retry = screen.getByRole('button', { name: /retry/i });
    await user.click(retry);
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe('EntitySelect — empty state (FR-4)', () => {
  it('renders the default "No options" placeholder when no emptyState provided', () => {
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook([])}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        data-testid="es-empty-default"
      />,
    );
    const trigger = screen.getByTestId('es-empty-default');
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveTextContent('No options');
  });

  it('renders the configured emptyState message + CTA Link', () => {
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook([])}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        emptyState={{
          message: 'No clusters registered',
          cta: { label: 'Register a cluster', href: '/clusters' },
        }}
        data-testid="es-empty-cta"
      />,
    );
    expect(screen.getByTestId('es-empty-cta')).toHaveTextContent('No clusters registered');
    const cta = screen.getByRole('link', { name: 'Register a cluster' });
    expect(cta).toHaveAttribute('href', '/clusters');
  });
});

describe('EntitySelect — status indicator (FR-6)', () => {
  it('renders a colored dot per item when getStatus is provided', async () => {
    const user = userEvent.setup();
    const fixtures: Fixture[] = [
      { id: 'g', name: 'green-one', health: 'green' },
      { id: 'y', name: 'yellow-one', health: 'yellow' },
      { id: 'r', name: 'red-one', health: 'red' },
    ];
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(fixtures)}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        getStatus={(e) => e.health ?? 'unknown'}
        data-testid="es-status"
      />,
    );
    await user.click(screen.getByTestId('es-status'));
    // Each option should contain a bullet character and a colored span.
    const optGreen = await screen.findByRole('option', { name: /green-one/i });
    const optYellow = await screen.findByRole('option', { name: /yellow-one/i });
    const optRed = await screen.findByRole('option', { name: /red-one/i });
    expect(optGreen.querySelector('span[aria-hidden="true"]')).toHaveClass('text-green-600');
    expect(optYellow.querySelector('span[aria-hidden="true"]')).toHaveClass('text-amber-600');
    expect(optRed.querySelector('span[aria-hidden="true"]')).toHaveClass('text-red-600');
  });

  it('sorts entities green-first with stable order within tiers', async () => {
    const user = userEvent.setup();
    const fixtures: Fixture[] = [
      { id: '1', name: 'Alpha-red', health: 'red' },
      { id: '2', name: 'Bravo-green', health: 'green' },
      { id: '3', name: 'Charlie-yellow', health: 'yellow' },
      { id: '4', name: 'Delta-green', health: 'green' },
      { id: '5', name: 'Echo-red', health: 'red' },
    ];
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(fixtures)}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        getStatus={(e) => e.health ?? 'unknown'}
        data-testid="es-sort"
      />,
    );
    await user.click(screen.getByTestId('es-sort'));
    const options = await screen.findAllByRole('option');
    const labels = options.map((opt) => opt.textContent);
    // Expected order: greens first (Bravo, Delta — insertion order preserved),
    // then yellow (Charlie), then reds (Alpha, Echo — insertion order).
    expect(labels[0]).toMatch(/Bravo-green/);
    expect(labels[1]).toMatch(/Delta-green/);
    expect(labels[2]).toMatch(/Charlie-yellow/);
    expect(labels[3]).toMatch(/Alpha-red/);
    expect(labels[4]).toMatch(/Echo-red/);
  });

  it('does not render status dots when getStatus is omitted', async () => {
    const user = userEvent.setup();
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(FIXTURES_THREE)}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        data-testid="es-no-status"
      />,
    );
    await user.click(screen.getByTestId('es-no-status'));
    const option = await screen.findByRole('option', { name: /alpha/i });
    expect(option.querySelector('span[aria-hidden="true"]')).toBeNull();
  });

  it('renders inlineWarning under the trigger when selected entity yields non-null', () => {
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook([{ id: 'sick', name: 'staging-es', health: 'yellow' }])}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value="sick"
        onChange={vi.fn()}
        getStatus={(e) => e.health ?? 'unknown'}
        inlineWarning={(e) =>
          e && e.health !== 'green' ? `Selected cluster is currently ${e.health}.` : null
        }
        data-testid="es-warn"
      />,
    );
    expect(screen.getByText(/Selected cluster is currently yellow/)).toHaveClass('text-amber-600');
  });

  it('does not render inlineWarning when callback returns null', () => {
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook([{ id: 'ok', name: 'local-es', health: 'green' }])}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value="ok"
        onChange={vi.fn()}
        getStatus={(e) => e.health ?? 'unknown'}
        inlineWarning={(e) =>
          e && e.health !== 'green' ? `Selected cluster is currently ${e.health}.` : null
        }
        data-testid="es-warn-none"
      />,
    );
    expect(screen.queryByText(/Selected cluster is currently/)).toBeNull();
  });
});

describe('EntitySelect — disabled subset (FR-5)', () => {
  it('disables items in disabledIds and exposes the reason via title attribute', async () => {
    const user = userEvent.setup();
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(FIXTURES_THREE)}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={vi.fn()}
        disabledIds={new Set(['e2'])}
        disabledReason={() => 'Archived 2026-04-01'}
        data-testid="es-disabled"
      />,
    );
    await user.click(screen.getByTestId('es-disabled'));
    const disabledOpt = await screen.findByRole('option', { name: /bravo/i });
    expect(disabledOpt).toHaveAttribute('data-disabled');
    expect(disabledOpt).toHaveAttribute('title', 'Archived 2026-04-01');
  });

  it('does not fire onChange when a disabled item is clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <EntitySelect<Fixture>
        useEntities={buildHook(FIXTURES_THREE)}
        getId={(e) => e.id}
        getLabel={(e) => e.name}
        value={undefined}
        onChange={onChange}
        disabledIds={new Set(['e2'])}
        data-testid="es-disabled-click"
      />,
    );
    await user.click(screen.getByTestId('es-disabled-click'));
    const disabledOpt = await screen.findByRole('option', { name: /bravo/i });
    await user.click(disabledOpt);
    expect(onChange).not.toHaveBeenCalled();
  });
});
