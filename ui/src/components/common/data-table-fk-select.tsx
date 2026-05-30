// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * FK-select dropdown for `<DataTable>` (feat_data_table_primitive Story 2.3 / FR-5).
 *
 * Generalizes the existing `cluster-filter-select.tsx` pattern for FK
 * filters where the allowed values load asynchronously (e.g. `cluster_id`
 * on proposals, `template_id` on proposals). Uses native `<select>` to
 * match the existing project pattern (no new Radix dep).
 */

export interface DataTableFkSelectProps {
  /** Column id — used in `data-testid` + the `<label>` `htmlFor`. */
  columnId: string;
  /**
   * The hook the consumer's column-config supplies; matches the
   * `cluster-filter-select.tsx` precedent (returns `{ data, isLoading }`
   * where `data` is `{ id, label }[]`).
   */
  useOptions: () => {
    data: { id: string; label: string }[];
    isLoading: boolean;
  };
  value: string | null;
  onChange: (next: string | null) => void;
  /** Default `"All <columnId>"`. */
  placeholder?: string;
  /** Disables the select when the underlying table query is fetching. */
  isLoading?: boolean;
}

export function DataTableFkSelect({
  columnId,
  useOptions,
  value,
  onChange,
  placeholder,
  isLoading: isTableLoading = false,
}: DataTableFkSelectProps) {
  const { data, isLoading: areOptionsLoading } = useOptions();
  const placeholderText = placeholder ?? `All ${columnId}`;
  const selectId = `fk-select-${columnId}`;
  const disabled = isTableLoading || areOptionsLoading;
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={selectId} className="text-sm">
        {columnId}
      </label>
      <select
        id={selectId}
        className="rounded-md border border-gray-200 bg-white px-2 py-1 text-sm"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={disabled}
        data-testid={selectId}
      >
        <option value="">{areOptionsLoading ? '(loading…)' : placeholderText}</option>
        {data.map((opt) => (
          <option key={opt.id} value={opt.id}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
