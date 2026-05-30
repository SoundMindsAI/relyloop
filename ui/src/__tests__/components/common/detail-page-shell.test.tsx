// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { UseQueryResult } from '@tanstack/react-query';

import { DetailPageShell } from '@/components/common/detail-page-shell';
import { ApiError } from '@/lib/api-errors';

/**
 * Unit tests for the DetailPageShell primitive
 * (chore_detail_page_shell_primitive).
 *
 * The primitive accepts `query: UseQueryResult<T, ApiError>` directly, so
 * tests synthesize a query object rather than wiring up QueryClientProvider
 * + msw. Page-level integration tests under `src/__tests__/app/<entity>/[id]/`
 * call the real TanStack hook in their own scope; this file pins
 * primitive-internal behavior.
 */

interface Fixture {
  id: string;
  name: string;
}

interface QueryStub {
  isPending: boolean;
  isError?: boolean;
  error?: ApiError;
  data?: Fixture;
}

function buildQuery(state: QueryStub): UseQueryResult<Fixture, ApiError> {
  const stub = {
    isPending: state.isPending,
    isError: state.isError ?? false,
    error: state.error ?? null,
    data: state.data,
  };
  return stub as unknown as UseQueryResult<Fixture, ApiError>;
}

describe('<DetailPageShell>', () => {
  it('renders the loading placeholder when query.isPending', () => {
    render(
      <DetailPageShell
        query={buildQuery({ isPending: true })}
        entityLabel="study"
        notFoundErrorCode="STUDY_NOT_FOUND"
      >
        {() => <div data-testid="body">body</div>}
      </DetailPageShell>,
    );
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByTestId('body')).not.toBeInTheDocument();
  });

  it('renders the not-found EmptyState when errorCode matches notFoundErrorCode', () => {
    const error = new ApiError({
      status: 404,
      errorCode: 'STUDY_NOT_FOUND',
      message: 'no such study',
      retryable: false,
    });
    render(
      <DetailPageShell
        query={buildQuery({ isPending: false, isError: true, error })}
        entityLabel="study"
        notFoundErrorCode="STUDY_NOT_FOUND"
      >
        {() => <div data-testid="body">body</div>}
      </DetailPageShell>,
    );
    expect(screen.getByText('Study not found')).toBeInTheDocument();
    expect(screen.getByText('The study may have been deleted.')).toBeInTheDocument();
    expect(screen.queryByTestId('body')).not.toBeInTheDocument();
  });

  it('renders the unreachable EmptyState when errorCode does not match (network / 5xx)', () => {
    const error = new ApiError({
      status: 0,
      errorCode: 'SERVICE_UNAVAILABLE',
      message: 'connection refused',
      retryable: true,
    });
    render(
      <DetailPageShell
        query={buildQuery({ isPending: false, isError: true, error })}
        entityLabel="study"
        notFoundErrorCode="STUDY_NOT_FOUND"
      >
        {() => <div data-testid="body">body</div>}
      </DetailPageShell>,
    );
    expect(screen.getByText('Backend unreachable')).toBeInTheDocument();
    expect(screen.getByText('Refresh after re-launching the API.')).toBeInTheDocument();
  });

  it('invokes children with data when query resolves', () => {
    const data: Fixture = { id: 's-1', name: 'My Study' };
    render(
      <DetailPageShell
        query={buildQuery({ isPending: false, isError: false, data })}
        entityLabel="study"
        notFoundErrorCode="STUDY_NOT_FOUND"
      >
        {(study) => <div data-testid="body">{study.name}</div>}
      </DetailPageShell>,
    );
    expect(screen.getByTestId('body')).toHaveTextContent('My Study');
  });

  it('uses entityTitle override for the not-found title when provided', () => {
    const error = new ApiError({
      status: 404,
      errorCode: 'JUDGMENT_LIST_NOT_FOUND',
      message: 'no such list',
      retryable: false,
    });
    render(
      <DetailPageShell
        query={buildQuery({ isPending: false, isError: true, error })}
        entityLabel="judgment list"
        entityTitle="Judgment list"
        notFoundErrorCode="JUDGMENT_LIST_NOT_FOUND"
      >
        {() => <div>body</div>}
      </DetailPageShell>,
    );
    expect(screen.getByText('Judgment list not found')).toBeInTheDocument();
    expect(screen.getByText('The judgment list may have been deleted.')).toBeInTheDocument();
  });

  it('uses notFoundMessage override when provided', () => {
    const error = new ApiError({
      status: 404,
      errorCode: 'CLUSTER_NOT_FOUND',
      message: 'no such cluster',
      retryable: false,
    });
    render(
      <DetailPageShell
        query={buildQuery({ isPending: false, isError: true, error })}
        entityLabel="cluster"
        notFoundErrorCode="CLUSTER_NOT_FOUND"
        notFoundMessage="The cluster has been archived."
      >
        {() => <div>body</div>}
      </DetailPageShell>,
    );
    expect(screen.getByText('The cluster has been archived.')).toBeInTheDocument();
    expect(screen.queryByText('The cluster may have been deleted.')).not.toBeInTheDocument();
  });

  it('uses unreachableMessage override when provided', () => {
    const error = new ApiError({
      status: 0,
      errorCode: 'SERVICE_UNAVAILABLE',
      message: 'connection refused',
      retryable: true,
    });
    render(
      <DetailPageShell
        query={buildQuery({ isPending: false, isError: true, error })}
        entityLabel="study"
        notFoundErrorCode="STUDY_NOT_FOUND"
        unreachableMessage="API is restarting; try again shortly."
      >
        {() => <div>body</div>}
      </DetailPageShell>,
    );
    expect(screen.getByText('API is restarting; try again shortly.')).toBeInTheDocument();
  });

  it('renders nothing when query.data is undefined but state is not pending or error', () => {
    const { container } = render(
      <DetailPageShell
        query={buildQuery({ isPending: false, isError: false })}
        entityLabel="study"
        notFoundErrorCode="STUDY_NOT_FOUND"
      >
        {() => <div data-testid="body">body</div>}
      </DetailPageShell>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
