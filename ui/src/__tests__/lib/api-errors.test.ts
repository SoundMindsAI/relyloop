import { describe, expect, it } from 'vitest';

import { ApiError, isApiError, toToastMessage } from '@/lib/api-errors';

describe('ApiError', () => {
  it('captures status / errorCode / message / retryable / requestId', () => {
    const err = new ApiError({
      status: 409,
      errorCode: 'CLUSTER_NAME_TAKEN',
      message: 'A cluster named "prod" already exists',
      retryable: false,
      requestId: 'abc-123',
    });
    expect(err.status).toBe(409);
    expect(err.errorCode).toBe('CLUSTER_NAME_TAKEN');
    expect(err.retryable).toBe(false);
    expect(err.requestId).toBe('abc-123');
    expect(err.message).toBe('A cluster named "prod" already exists');
    expect(err.name).toBe('ApiError');
  });

  it('defaults requestId to null when omitted', () => {
    const err = new ApiError({
      status: 500,
      errorCode: 'INTERNAL_ERROR',
      message: 'boom',
      retryable: false,
    });
    expect(err.requestId).toBeNull();
  });
});

describe('isApiError', () => {
  it('recognizes ApiError instances', () => {
    const err = new ApiError({
      status: 422,
      errorCode: 'VALIDATION_ERROR',
      message: 'bad',
      retryable: false,
    });
    expect(isApiError(err)).toBe(true);
  });

  it('rejects plain Error instances', () => {
    expect(isApiError(new Error('plain'))).toBe(false);
  });

  it('rejects non-error values', () => {
    expect(isApiError(null)).toBe(false);
    expect(isApiError(undefined)).toBe(false);
    expect(isApiError({ status: 500, errorCode: 'X' })).toBe(false);
    expect(isApiError('error')).toBe(false);
  });
});

describe('toToastMessage', () => {
  it('formats ApiError as [error_code] message', () => {
    const err = new ApiError({
      status: 503,
      errorCode: 'SERVICE_UNAVAILABLE',
      message: 'Backend down',
      retryable: true,
    });
    expect(toToastMessage(err)).toBe('[SERVICE_UNAVAILABLE] Backend down');
  });

  it('returns plain Error.message for non-ApiError', () => {
    expect(toToastMessage(new Error('boom'))).toBe('boom');
  });

  it('returns "Unknown error" for non-Error values', () => {
    expect(toToastMessage(null)).toBe('Unknown error');
    expect(toToastMessage(undefined)).toBe('Unknown error');
    expect(toToastMessage(42)).toBe('Unknown error');
    expect(toToastMessage('string')).toBe('Unknown error');
  });
});
