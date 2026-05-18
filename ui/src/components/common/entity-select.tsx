'use client';

/**
 * Form-side FK dropdown primitive (chore_form_dropdown_primitive FR-1 through FR-6).
 *
 * Wraps the shadcn `<Select>` family for use inside form modals where the
 * options are loaded asynchronously via a TanStack listing hook (e.g.
 * `useClusters`, `useConfigRepos`, `useTemplates`). Peer to (NOT child of)
 * `data-table-fk-select.tsx`, which renders a native `<select>` for the
 * DataTable filter strip — the two primitives are intentionally kept apart
 * because their rendering families and hook shapes differ.
 *
 * Source-of-truth for `EntityStatus`: ui/src/lib/enums.ts HEALTH_STATUS_VALUES
 * (mirrors backend/app/api/v1/schemas.py HealthStatusValue). The backend wire
 * value `'unreachable'` is the caller's responsibility to map to `'unknown'`
 * in their `getStatus` callback — the primitive itself does not normalize.
 */

import Link from 'next/link';
import type { UseQueryResult } from '@tanstack/react-query';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { ApiError } from '@/lib/api-errors';

export type EntityStatus = 'green' | 'yellow' | 'red' | 'unknown';

export interface EntitySelectEmptyState {
  message: string;
  cta?: { label: string; href: string };
}

export interface EntitySelectListPage<T> {
  data: T[];
  next_cursor?: string | null;
  has_more?: boolean;
}

export interface EntitySelectProps<T> {
  useEntities: () => UseQueryResult<EntitySelectListPage<T>, ApiError>;
  getId: (entity: T) => string;
  getLabel: (entity: T) => string;
  value: string | undefined;
  onChange: (next: string | undefined) => void;
  getStatus?: (entity: T) => EntityStatus;
  inlineWarning?: (entity: T | undefined) => string | null;
  disabledIds?: ReadonlySet<string>;
  disabledReason?: (entity: T) => string | null;
  emptyState?: EntitySelectEmptyState;
  placeholder?: string;
  loadingPlaceholder?: string;
  id?: string;
  'data-testid'?: string;
}

const STATUS_PRECEDENCE: Record<EntityStatus, number> = {
  green: 0,
  yellow: 1,
  red: 2,
  unknown: 3,
};

const STATUS_COLOR: Record<EntityStatus, string> = {
  green: 'text-green-600',
  yellow: 'text-amber-600',
  red: 'text-red-600',
  unknown: 'text-muted-foreground',
};

export function EntitySelect<T>(props: EntitySelectProps<T>) {
  const {
    useEntities,
    getId,
    getLabel,
    value,
    onChange,
    getStatus,
    inlineWarning,
    disabledIds,
    disabledReason,
    emptyState,
    placeholder = 'Select…',
    loadingPlaceholder = 'Loading…',
    id,
  } = props;
  const dataTestId = props['data-testid'];

  const query = useEntities();
  const { data, isLoading, isError, refetch } = query;

  const entities = data?.data ? data.data.filter((entity) => getId(entity) != null) : [];

  const sortedEntities = getStatus
    ? [...entities]
        .map((entity, index) => ({ entity, index, status: getStatus(entity) }))
        .sort(
          (a, b) =>
            STATUS_PRECEDENCE[a.status] - STATUS_PRECEDENCE[b.status] || a.index - b.index,
        )
        .map(({ entity }) => entity)
    : entities;

  const selectedEntity =
    value === undefined ? undefined : entities.find((entity) => getId(entity) === value);

  if (isLoading) {
    return (
      <Select value="" onValueChange={() => {}} disabled>
        <SelectTrigger id={id} data-testid={dataTestId} disabled>
          <SelectValue placeholder={loadingPlaceholder} />
        </SelectTrigger>
      </Select>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-2">
        <Select value="" onValueChange={() => {}} disabled>
          <SelectTrigger id={id} data-testid={dataTestId} disabled>
            <SelectValue placeholder="Failed to load — click retry" />
          </SelectTrigger>
        </Select>
        <button
          type="button"
          onClick={() => {
            void refetch();
          }}
          className="text-xs underline"
          title="Click to retry loading the list."
        >
          Retry
        </button>
      </div>
    );
  }

  if (entities.length === 0) {
    const emptyMessage = emptyState?.message ?? 'No options';
    return (
      <div className="space-y-1">
        <Select value="" onValueChange={() => {}} disabled>
          <SelectTrigger id={id} data-testid={dataTestId} disabled>
            <SelectValue placeholder={emptyMessage} />
          </SelectTrigger>
        </Select>
        {emptyState?.cta && (
          <p className="text-xs">
            <Link href={emptyState.cta.href} className="underline">
              {emptyState.cta.label}
            </Link>
          </p>
        )}
      </div>
    );
  }

  const warning = inlineWarning ? inlineWarning(selectedEntity) : null;

  return (
    <div className="space-y-1">
      <Select
        value={value ?? ''}
        onValueChange={(v) => onChange(v || undefined)}
      >
        <SelectTrigger id={id} data-testid={dataTestId}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {sortedEntities.map((entity) => {
            const entityId = getId(entity);
            const isDisabled = disabledIds?.has(entityId) ?? false;
            const reason = isDisabled && disabledReason ? disabledReason(entity) : null;
            const status = getStatus ? getStatus(entity) : null;
            return (
              <SelectItem
                key={entityId}
                value={entityId}
                disabled={isDisabled}
                title={reason ?? undefined}
              >
                {status && (
                  <span aria-hidden="true" className={`${STATUS_COLOR[status]} mr-1`}>
                    ●
                  </span>
                )}
                {getLabel(entity)}
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>
      {warning && <p className="text-xs text-amber-600 mt-1">{warning}</p>}
    </div>
  );
}
