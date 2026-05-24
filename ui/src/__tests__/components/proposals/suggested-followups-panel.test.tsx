import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import {
  type FollowupItem,
  SuggestedFollowupsPanel,
} from '@/components/proposals/suggested-followups-panel';
import { TooltipProvider } from '@/components/ui/tooltip';

// Mock the useTemplate hook so the per-card swap-target fetches return
// deterministic data without TanStack Query firing real network calls.
vi.mock('@/lib/api/query-templates', () => ({
  useTemplate: vi.fn(),
}));
// Re-import after mock so the test body controls the implementation.
import { useTemplate } from '@/lib/api/query-templates';
const mockedUseTemplate = vi.mocked(useTemplate);

// feat_digest_executable_followups Story 5.1 — covers all 6 rows in the
// legacy-parity table plus the kind-discriminated card markup.

const VALID_SEARCH_SPACE = {
  params: {
    title_boost: { type: 'float' as const, low: 0.5, high: 2.0, log: false },
  },
};

const NARROW: FollowupItem = {
  kind: 'narrow',
  rationale: 'narrow around the winner',
  search_space: VALID_SEARCH_SPACE,
};

const WIDEN: FollowupItem = {
  kind: 'widen',
  rationale: 'widen because winner hit edge',
  search_space: VALID_SEARCH_SPACE,
};

const TEXT: FollowupItem = {
  kind: 'text',
  rationale: 'add brand-disambiguation queries',
  search_space: null,
};

const SWAP_TARGET_A_ID = '01931e8a-aaaa-7890-abcd-aaaaaaaaaaaa';
const SWAP_TARGET_B_ID = '01931e8a-bbbb-7890-abcd-bbbbbbbbbbbb';

const SWAP_TEMPLATE_A: FollowupItem = {
  kind: 'swap_template',
  rationale: 'swap to template A for phrase_slop coverage',
  template_id: SWAP_TARGET_A_ID,
  search_space: VALID_SEARCH_SPACE,
};

const SWAP_TEMPLATE_B: FollowupItem = {
  kind: 'swap_template',
  rationale: 'swap to template B for a richer field-boost set',
  template_id: SWAP_TARGET_B_ID,
  search_space: VALID_SEARCH_SPACE,
};

function _mockTemplateOk(declaredParams: Record<string, string>) {
  return {
    data: {
      id: 'test-tpl',
      name: 'test-template',
      version: 1,
      declared_params: declaredParams,
    },
    isLoading: false,
    error: null,
  } as unknown as ReturnType<typeof useTemplate>;
}

function _mockTemplateLoading() {
  return {
    data: undefined,
    isLoading: true,
    error: null,
  } as unknown as ReturnType<typeof useTemplate>;
}

function _mockTemplateError() {
  return {
    data: undefined,
    isLoading: false,
    error: new Error('boom'),
  } as unknown as ReturnType<typeof useTemplate>;
}

function renderPanel(props: Partial<React.ComponentProps<typeof SuggestedFollowupsPanel>> = {}) {
  const onRun = props.onRun ?? vi.fn();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    onRun,
    ...render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <SuggestedFollowupsPanel followups={[NARROW, WIDEN, TEXT]} onRun={onRun} {...props} />
        </TooltipProvider>
      </QueryClientProvider>,
    ),
  };
}

describe('<SuggestedFollowupsPanel />', () => {
  describe('legacy-parity (Story 5.1 §"Legacy behavior parity" table)', () => {
    it('row 1 — hides when followups is empty', () => {
      const onRun = vi.fn();
      render(
        <TooltipProvider>
          <SuggestedFollowupsPanel followups={[]} onRun={onRun} />
        </TooltipProvider>,
      );
      expect(screen.queryByTestId('suggested-followups-list')).toBeNull();
    });

    it('row 2 — preserves container data-testid="suggested-followups-list"', () => {
      renderPanel();
      expect(screen.getByTestId('suggested-followups-list')).toBeInTheDocument();
    });

    it('row 4 + AC-10 — no <a> or <Link> with /studies?hypothesis= href', () => {
      const { container } = renderPanel();
      const links = container.querySelectorAll('a[href*="/studies?hypothesis="]');
      expect(links.length).toBe(0);
    });

    it('row 5 — InfoTooltip on panel title is preserved', () => {
      renderPanel();
      expect(screen.getByText('Suggested follow-ups')).toBeInTheDocument();
    });

    it('row 6 — rationale text uses the small-text class on a <p>', () => {
      renderPanel();
      // Each rationale is rendered as a <p> with text-sm class.
      const paragraph = screen.getByText('narrow around the winner');
      expect(paragraph.tagName).toBe('P');
      expect(paragraph.className).toContain('text-sm');
    });
  });

  describe('kind-discriminated cards', () => {
    it('renders the Narrow badge + Run button on a narrow card', () => {
      renderPanel({ followups: [NARROW], onRun: vi.fn() });
      expect(screen.getByText('Narrow')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-run')).toBeInTheDocument();
    });

    it('renders the Widen badge + Run button on a widen card', () => {
      renderPanel({ followups: [WIDEN], onRun: vi.fn() });
      expect(screen.getByText('Widen')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-run')).toBeInTheDocument();
    });

    it('renders the Suggestion badge + NO Run button on a text card', () => {
      renderPanel({ followups: [TEXT], onRun: vi.fn() });
      expect(screen.getByText('Suggestion')).toBeInTheDocument();
      expect(screen.queryByTestId('followup-0-run')).toBeNull();
    });

    it('per-item data-testids land on every card', () => {
      renderPanel();
      // narrow at index 0
      expect(screen.getByTestId('followup-0-card')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-run')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-show-search-space')).toBeInTheDocument();
      // widen at index 1
      expect(screen.getByTestId('followup-1-card')).toBeInTheDocument();
      expect(screen.getByTestId('followup-1-run')).toBeInTheDocument();
      // text at index 2 — no run, no show-search-space
      expect(screen.getByTestId('followup-2-card')).toBeInTheDocument();
      expect(screen.queryByTestId('followup-2-run')).toBeNull();
      expect(screen.queryByTestId('followup-2-show-search-space')).toBeNull();
    });
  });

  describe('interactions', () => {
    it('clicking Run fires the onRun(index) callback', async () => {
      const user = userEvent.setup();
      const { onRun } = renderPanel();
      await user.click(screen.getByTestId('followup-1-run'));
      expect(onRun).toHaveBeenCalledTimes(1);
      expect(onRun).toHaveBeenCalledWith(1);
    });
  });

  describe('parent search-space diff (Story 5.2 F2)', () => {
    it('renders parent JSON block when parentSearchSpace is provided', () => {
      const { container } = renderPanel({
        parentSearchSpace: { params: { tie_breaker: { type: 'float', low: 0, high: 1 } } },
      });
      expect(
        container.querySelectorAll('[data-testid="followup-0-parent-search-space"]').length,
      ).toBe(1);
    });

    it('renders loading message when parentStudyLoading is true', () => {
      renderPanel({ parentStudyLoading: true });
      expect(screen.getByTestId('followup-0-search-space-loading')).toBeInTheDocument();
    });

    it('renders error message when parentStudyError is non-null', () => {
      renderPanel({ parentStudyError: new Error('boom') });
      expect(screen.getByTestId('followup-0-search-space-error')).toBeInTheDocument();
    });

    it('always renders proposed search-space block on narrow/widen', () => {
      renderPanel();
      expect(screen.getByTestId('followup-0-proposed-search-space')).toBeInTheDocument();
      expect(screen.getByTestId('followup-1-proposed-search-space')).toBeInTheDocument();
    });
  });

  describe('feat_digest_executable_followups_swap_template Story 3.2', () => {
    it('renders the Swap template badge + run button + declared-params + search-space data-testids', () => {
      mockedUseTemplate.mockReturnValue(
        _mockTemplateOk({ title_boost: 'float', phrase_slop: 'int' }),
      );
      renderPanel({
        followups: [SWAP_TEMPLATE_A],
        parentTemplate: {
          declared_params: { title_boost: 'float', tie_breaker: 'int' },
        },
      });
      expect(screen.getByText('Swap template')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-card')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-declared-params-diff')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-parent-declared-params')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-swap-declared-params')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-show-search-space')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-show-declared-params')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-run')).toBeInTheDocument();
    });

    it('renders the per-card loading state on the swap-target column when useTemplate is loading', () => {
      mockedUseTemplate.mockReturnValue(_mockTemplateLoading());
      renderPanel({
        followups: [SWAP_TEMPLATE_A],
        parentTemplate: { declared_params: { title_boost: 'float' } },
      });
      expect(screen.getByTestId('followup-0-swap-declared-params-loading')).toBeInTheDocument();
    });

    it('renders the per-card error state when the swap-target fetch errors', () => {
      mockedUseTemplate.mockReturnValue(_mockTemplateError());
      renderPanel({
        followups: [SWAP_TEMPLATE_A],
        parentTemplate: { declared_params: { title_boost: 'float' } },
      });
      expect(screen.getByTestId('followup-0-swap-declared-params-error')).toBeInTheDocument();
      // Run button stays enabled even when the comparison view fails to load.
      expect(screen.getByTestId('followup-0-run')).toBeInTheDocument();
    });

    it('Run button on swap_template card fires onRun(index)', async () => {
      mockedUseTemplate.mockReturnValue(
        _mockTemplateOk({ title_boost: 'float', phrase_slop: 'int' }),
      );
      const user = userEvent.setup();
      const { onRun } = renderPanel({
        followups: [TEXT, SWAP_TEMPLATE_A],
        parentTemplate: { declared_params: { title_boost: 'float' } },
      });
      await user.click(screen.getByTestId('followup-1-run'));
      expect(onRun).toHaveBeenCalledTimes(1);
      expect(onRun).toHaveBeenCalledWith(1);
    });

    it('multi-target case: two swap_template cards each fetch their own swap target', async () => {
      // First call → target A; second call → target B.
      mockedUseTemplate.mockImplementation((id: string | null | undefined) => {
        if (id === SWAP_TARGET_A_ID) {
          return _mockTemplateOk({ title_boost: 'float', phrase_slop: 'int' });
        }
        return _mockTemplateOk({ title_boost: 'float', bm25_b: 'float' });
      });
      renderPanel({
        followups: [SWAP_TEMPLATE_A, SWAP_TEMPLATE_B],
        parentTemplate: { declared_params: { title_boost: 'float' } },
      });
      await waitFor(() => {
        expect(screen.getByTestId('followup-0-swap-declared-params')).toBeInTheDocument();
        expect(screen.getByTestId('followup-1-swap-declared-params')).toBeInTheDocument();
      });
      // Both per-card useTemplate calls fired (one per distinct template id).
      const calledIds = mockedUseTemplate.mock.calls.map((c) => c[0]);
      expect(calledIds).toContain(SWAP_TARGET_A_ID);
      expect(calledIds).toContain(SWAP_TARGET_B_ID);
    });
  });
});
