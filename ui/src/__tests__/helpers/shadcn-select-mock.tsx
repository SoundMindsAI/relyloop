// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared vitest mock for the shadcn `<Select>` family.
 *
 * Radix (the engine behind shadcn `<Select>`) crashes inside jsdom + Dialog
 * because testing-library's `patchedFocus` shim recurses infinitely through
 * Radix's internal focus-trap. This helper replaces the Radix primitives
 * with a thin native `<select>` shim so modal tests can drive the form via
 * change events.
 *
 * Originally duplicated across `create-study-modal.test.tsx`,
 * `create-query-set-modal.test.tsx`, and `register-cluster-modal.test.tsx`;
 * extracted per `chore_extract_shadcn_select_test_mock`.
 *
 * ## Usage
 *
 * Top of any `*.test.tsx` that renders a component depending on
 * `@/components/ui/select`:
 *
 * ```ts
 * vi.mock('@/components/ui/select', async () => {
 *   const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
 *   return mockShadcnSelect();
 * });
 * ```
 *
 * The dynamic `import()` inside the factory sidesteps vitest's `vi.mock`
 * hoisting rule (which would otherwise put the `vi.mock` call above the
 * top-of-file `import` and leave the helper symbol unbound). The factory
 * itself is async and is only invoked when the SUT first imports the
 * mocked module — by which point all top-level imports have completed.
 *
 * ## What's mocked
 *
 * - `Select` → `<select>` element whose value pipes through `onValueChange`
 *   and whose `id` / `data-testid` are pulled from the inner `SelectTrigger`'s
 *   props (so existing `id="..."` / `data-testid="..."` attributes on the
 *   trigger keep working).
 * - `SelectTrigger` → returns null. The trigger's props are read by the
 *   `Select` mock via React.Children iteration.
 * - `SelectValue` → returns null. The native `<select>` renders its own
 *   selected-option label.
 * - `SelectContent` → fragment wrapper. Children render as native `<option>`.
 * - `SelectItem` → `<option value={value} disabled={disabled}>`.
 *
 * Captures `disabled` on both `Select` and `SelectItem` so the
 * Story 2.1/2.3-era tests for the `disabledIds` slot can assert it.
 */

import { type ReactNode } from 'react';

export const mockShadcnSelect = async () => {
  const React = (await import('react')) as typeof import('react');
  function SelectTrigger() {
    return null;
  }
  // Pull both `id` and `data-testid` off the inner `SelectTrigger` in a
  // single React.Children pass. Prefers reference equality on
  // `child.type === SelectTrigger` (robust against minifier name-mangling)
  // and falls back to the `.name === 'SelectTrigger'` string check for the
  // rare case where the SUT renders a wrapped/composed trigger.
  function findTriggerProps(children: ReactNode): {
    id: string | undefined;
    'data-testid': string | undefined;
  } {
    let id: string | undefined;
    let testId: string | undefined;
    React.Children.forEach(children, (child) => {
      if (
        React.isValidElement<{ id?: string; 'data-testid'?: string }>(child) &&
        (child.type === SelectTrigger ||
          (typeof child.type === 'function' &&
            (child.type as { name?: string }).name === 'SelectTrigger'))
      ) {
        id = child.props.id;
        testId = child.props['data-testid'];
      }
    });
    return { id, 'data-testid': testId };
  }
  return {
    Select: ({
      value,
      onValueChange,
      children,
      disabled,
    }: {
      value?: string;
      onValueChange?: (v: string) => void;
      children: ReactNode;
      disabled?: boolean;
    }) => (
      <select
        {...findTriggerProps(children)}
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => onValueChange?.(e.target.value)}
      >
        <option value="" />
        {children}
      </select>
    ),
    SelectTrigger,
    SelectValue: () => null,
    SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
    SelectItem: ({
      value,
      children,
      disabled,
    }: {
      value: string;
      children: ReactNode;
      disabled?: boolean;
    }) => (
      <option value={value} disabled={disabled}>
        {children}
      </option>
    ),
  };
};
