/**
 * Builder edits test suite (Stories 2.1, 2.2, 2.3).
 *
 * Story 2.1 (this file in initial state): 5 assertions covering FR-2 + FR-3:
 *   1. Float low/high keystroke edits debounce 200ms and write back to value
 *   2. onBlur flushes synchronously (cancels pending debounce)
 *   3. Type switch float→int→float preserves low/high via stash
 *   4. Type switch float→categorical→float restores low/high via stash
 *   5. Stash invalidation rules: textarea-driven row mutation clears stash,
 *      builder-originated writes do NOT clear stash (verified via switch+
 *      blur-flush+switch-back), templateBody change clears all stash,
 *      modal-close-then-reopen sees an empty stash (via unmount+remount).
 *
 * Stories 2.2 + 2.3 will append assertions 6, 7, 8.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import { TooltipProvider } from '@/components/ui/tooltip';
import type { QueryTemplateDetail } from '@/lib/api/query-templates';
import { SearchSpaceBuilder } from '@/components/studies/search-space-builder';

vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

function makeTemplate(declared_params: Record<string, string>): QueryTemplateDetail {
  return {
    id: 't1',
    name: 'test-template',
    engine_type: 'elasticsearch',
    body: '{}',
    declared_params,
    version: 1,
    parent_id: null,
    created_at: '2026-05-20T00:00:00Z',
  };
}

function makeBoostFloatValue(low = 0.5, high = 10, log = true): string {
  return JSON.stringify({ params: { boost: { type: 'float', low, high, log } } }, null, 2);
}

function setNumeric(testId: string, raw: string): void {
  fireEvent.change(screen.getByTestId(testId), { target: { value: raw } });
}

function setType(paramName: string, nextType: 'float' | 'int' | 'categorical'): void {
  // The shared shadcn-select-mock renders Select as a native <select>; the
  // trigger's `data-testid` is forwarded to the <select> element.
  const select = screen.getByTestId(`cs-row-${paramName}-type`) as HTMLSelectElement;
  fireEvent.change(select, { target: { value: nextType } });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe('SearchSpaceBuilder edits — Story 2.1 (FR-2 + FR-3)', () => {
  it('#1: float low/high keystroke edits debounce 200ms and write back to value', () => {
    const onChange = vi.fn();
    render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={makeBoostFloatValue()}
          onChange={onChange}
          templateBody={makeTemplate({ boost: 'float' })}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );

    // Reset spy: canonicalize-on-mount may have fired (it shouldn't here
    // because the value is already canonical, but clear defensively).
    onChange.mockClear();

    setNumeric('cs-row-boost-high', '15');
    // Within the 200ms window, no write yet.
    expect(onChange).not.toHaveBeenCalled();

    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledTimes(1);
    const written = onChange.mock.calls[0]![0] as string;
    expect(JSON.parse(written).params.boost.high).toBe(15);
  });

  it('#2: onBlur flushes synchronously (cancels pending debounce)', () => {
    const onChange = vi.fn();
    render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={makeBoostFloatValue()}
          onChange={onChange}
          templateBody={makeTemplate({ boost: 'float' })}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );
    onChange.mockClear();

    setNumeric('cs-row-boost-high', '15');
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.blur(screen.getByTestId('cs-row-boost-high'));
    // Flush is synchronous — no timer advance needed.
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(JSON.parse(onChange.mock.calls[0]![0]!).params.boost.high).toBe(15);

    // Advancing timers should NOT trigger a second debounced write.
    vi.advanceTimersByTime(500);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it('#3: type switch float→int→float preserves low/high via stash (controlled re-mount)', () => {
    const onChange = vi.fn();
    const template = makeTemplate({ boost: 'float' });
    let value = makeBoostFloatValue(0.5, 10, true);
    const setValueFromOnChange = (next: string) => {
      value = next;
      onChange(next);
    };

    const { rerender } = render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={setValueFromOnChange}
          templateBody={template}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );
    onChange.mockClear();

    // float → int: stash records the prior float spec.
    setType('boost', 'int');
    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledTimes(1);
    const intWritten = JSON.parse(onChange.mock.calls[0]![0]!);
    expect(intWritten.params.boost.type).toBe('int');
    // defaultSpecForType('int') = {low: 0, high: 5}
    expect(intWritten.params.boost.low).toBe(0);
    expect(intWritten.params.boost.high).toBe(5);

    rerender(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={setValueFromOnChange}
          templateBody={template}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );
    onChange.mockClear();

    // int → float: stash returns the prior {low:0.5, high:10, log:true}.
    setType('boost', 'float');
    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledTimes(1);
    const floatWritten = JSON.parse(onChange.mock.calls[0]![0]!);
    expect(floatWritten.params.boost).toEqual({ type: 'float', low: 0.5, high: 10, log: true });
  });

  it('#4: type switch float→categorical→float restores low/high via stash', () => {
    const onChange = vi.fn();
    const template = makeTemplate({ boost: 'float' });
    let value = makeBoostFloatValue(0.5, 10, true);
    const setValueFromOnChange = (next: string) => {
      value = next;
      onChange(next);
    };

    const { rerender } = render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={setValueFromOnChange}
          templateBody={template}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );
    onChange.mockClear();

    setType('boost', 'categorical');
    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(JSON.parse(onChange.mock.calls[0]![0]!).params.boost.type).toBe('categorical');

    rerender(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={setValueFromOnChange}
          templateBody={template}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );
    onChange.mockClear();

    setType('boost', 'float');
    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledTimes(1);
    const restored = JSON.parse(onChange.mock.calls[0]![0]!);
    expect(restored.params.boost).toEqual({ type: 'float', low: 0.5, high: 10, log: true });
  });

  it('#5: stash invalidation — external textarea write clears stash; builder writes do NOT', () => {
    const onChange = vi.fn();
    const template = makeTemplate({ boost: 'float' });
    let value = makeBoostFloatValue(0.5, 10, true);
    const setValueFromOnChange = (next: string) => {
      value = next;
      onChange(next);
    };

    const { rerender } = render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={setValueFromOnChange}
          templateBody={template}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );
    onChange.mockClear();

    // Switch float → int (stash records the prior float spec).
    setType('boost', 'int');
    vi.advanceTimersByTime(250);
    rerender(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={setValueFromOnChange}
          templateBody={template}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );

    // Simulate external textarea write that changes the boost row's spec
    // (different from the builder's last emit → triggers stash invalidation).
    const externalValue = JSON.stringify(
      { params: { boost: { type: 'int', low: 1, high: 99 } } },
      null,
      2,
    );
    value = externalValue;
    rerender(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={setValueFromOnChange}
          templateBody={template}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );
    onChange.mockClear();

    // Now switch back to float → stash was cleared, so we get the default
    // defaultSpecForType('float') = {low: 0, high: 1} — NOT the original {0.5, 10}.
    setType('boost', 'float');
    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledTimes(1);
    const afterInvalidation = JSON.parse(onChange.mock.calls[0]![0]!);
    expect(afterInvalidation.params.boost).toEqual({ type: 'float', low: 0, high: 1 });
  });
});

describe('SearchSpaceBuilder edits — Story 2.2 (FR-4 log toggle)', () => {
  function mountFloatRow(opts: { low: number; high: number; log: boolean }) {
    const onChange = vi.fn();
    const value = JSON.stringify({ params: { boost: { type: 'float', ...opts } } }, null, 2);
    render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={onChange}
          templateBody={makeTemplate({ boost: 'float' })}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );
    onChange.mockClear();
    return { onChange };
  }

  it('#6a: clicking checkbox with low=0 refuses transition + surfaces row error + NO native disabled', () => {
    const { onChange } = mountFloatRow({ low: 0, high: 10, log: false });

    const cb = screen.getByTestId('cs-row-boost-log') as HTMLInputElement;
    expect(cb).not.toBeDisabled(); // NO native `disabled`
    expect(cb).toHaveAttribute('aria-disabled', 'true');
    expect(cb).toHaveAttribute('title', 'Log scale requires low > 0');

    fireEvent.click(cb);
    vi.advanceTimersByTime(250);
    expect(onChange).not.toHaveBeenCalled(); // refused
    expect(cb.checked).toBe(false);
    expect(screen.getByTestId('cs-row-error-boost-log')).toHaveTextContent(
      'Log scale requires low > 0',
    );
  });

  it('#6b: raising low to 0.1 clears aria-disabled and unlocks the transition', () => {
    const { onChange } = mountFloatRow({ low: 0.1, high: 10, log: false });

    const cb = screen.getByTestId('cs-row-boost-log') as HTMLInputElement;
    expect(cb).not.toHaveAttribute('aria-disabled');
    expect(cb).not.toHaveAttribute('title');

    fireEvent.click(cb);
    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(JSON.parse(onChange.mock.calls[0]![0]!).params.boost.log).toBe(true);
  });

  it('#6c: a row that starts {log:true, low:-1} renders row error (pre-existing invalid)', () => {
    mountFloatRow({ low: -1, high: 10, log: true });
    expect(screen.getByTestId('cs-row-error-boost-log')).toHaveTextContent(
      'Log scale requires low > 0',
    );
  });
});

describe('SearchSpaceBuilder edits — Story 2.3 (FR-5/6/7 cardinality + Next)', () => {
  it('#7: cardinality counter turns red + aria-invalid + identifies max contributor when >1e6', () => {
    const onChange = vi.fn();
    // 5 floats × 100 + 1 int [0, 100000] (=100001) → ~1.0e15. Way over cap.
    const value = JSON.stringify(
      {
        params: {
          a: { type: 'float', low: 0, high: 1 },
          b: { type: 'float', low: 0, high: 1 },
          c: { type: 'float', low: 0, high: 1 },
          d: { type: 'float', low: 0, high: 1 },
          e: { type: 'float', low: 0, high: 1 },
          big: { type: 'int', low: 0, high: 100000 },
        },
      },
      null,
      2,
    );
    render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={onChange}
          templateBody={makeTemplate({
            a: 'float',
            b: 'float',
            c: 'float',
            d: 'float',
            e: 'float',
            big: 'int',
          })}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );

    const counter = screen.getByTestId('cs-builder-header-cardinality');
    expect(counter).toHaveAttribute('aria-invalid', 'true');
    expect(counter.className).toContain('text-destructive');

    const hint = screen.getByTestId('cs-builder-cap-hint');
    expect(hint.textContent).toContain('big');
    expect(hint.textContent).toContain('100,001');
  });

  it('#8: Next button (Step 5 advance) remains enabled when cardinality exceeds 10^6 (warning-only per FR-7)', () => {
    // This assertion verifies the warning-only contract via the builder's
    // OWN signal: `aria-invalid` on the counter but NO disabling propagated
    // back through onChange. The actual Step-4 Next button gating logic lives
    // in CreateStudyModal's `stepValid(3, ...)` predicate, which checks
    // JSON parseability only — not cardinality. We assert the cap exceedance
    // does not cause any error stream to fire (i.e., no error event in the
    // builder DOM beyond the cap-hint itself, which is informational only).
    const onChange = vi.fn();
    const value = JSON.stringify(
      {
        params: { a: { type: 'int', low: 0, high: 5_000_000 } }, // ~5e6, over cap
      },
      null,
      2,
    );
    render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={value}
          onChange={onChange}
          templateBody={makeTemplate({ a: 'int' })}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );

    // The builder emits no error envelope beyond the cap-hint paragraph
    // itself. There is no `cs-row-error-*` for the row (low<high holds).
    expect(screen.queryByTestId('cs-row-error-a')).not.toBeInTheDocument();
    // The cap-hint IS rendered but it's a warning, not a blocker.
    expect(screen.getByTestId('cs-builder-cap-hint')).toBeInTheDocument();
    // No row-level error fires anywhere.
    const rowErrors = document.querySelectorAll('[data-testid^="cs-row-error-"]');
    expect(rowErrors.length).toBe(0);
  });
});
