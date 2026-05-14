/**
 * Structured-error helpers for the RelyLoop API client.
 *
 * The backend's error envelope (per docs/01_architecture/api-conventions.md) is:
 *   { "detail": { "error_code": "<MACHINE_READABLE>", "message": "<human>", "retryable": <bool> } }
 *
 * We translate it into a typed `ApiError` so callers can branch on `error_code`
 * without re-parsing the response body. Network failures become `ApiError` with
 * `errorCode = "SERVICE_UNAVAILABLE"` and `status = 0`.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string;
  readonly retryable: boolean;
  readonly requestId: string | null;
  /**
   * The raw `detail` object from the backend envelope. Most error codes ship
   * with just `{error_code, message, retryable}` but a few (e.g.
   * `QUERY_HAS_JUDGMENTS`) extend the detail with structured fields the
   * frontend consumes directly (`judgment_lists`, `overflow_count`).
   * Callers that need those structured fields cast `detail` to the
   * specific envelope type.
   */
  readonly detail: Record<string, unknown> | null;

  constructor(args: {
    status: number;
    errorCode: string;
    message: string;
    retryable: boolean;
    requestId?: string | null;
    detail?: Record<string, unknown> | null;
  }) {
    super(args.message);
    this.name = 'ApiError';
    this.status = args.status;
    this.errorCode = args.errorCode;
    this.retryable = args.retryable;
    this.requestId = args.requestId ?? null;
    this.detail = args.detail ?? null;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/**
 * Formats an error for display in a toast notification. Keeps `error_code` in
 * the rendered string so operators can grep backend logs for the same code.
 */
export function toToastMessage(err: unknown): string {
  if (isApiError(err)) {
    return `[${err.errorCode}] ${err.message}`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return 'Unknown error';
}
