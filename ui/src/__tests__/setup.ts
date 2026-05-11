import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { setupServer } from 'msw/node';

/**
 * msw server shared across the test suite. Individual tests register
 * handlers via `server.use(http.get(...))` and the global `afterEach`
 * resets the handler list to empty so tests are independent.
 *
 * Tests that need to assert on request headers (e.g., `X-Request-ID`
 * injection) inspect `request.headers` inside their msw handlers.
 */
export const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
