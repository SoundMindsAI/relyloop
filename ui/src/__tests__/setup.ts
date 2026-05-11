import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { setupServer } from 'msw/node';

// jsdom doesn't ship matchMedia. next-themes (used by ThemeProvider/Toaster)
// reads it to detect the OS color scheme; without this stub, ThemeProvider
// crashes in jsdom-based tests with "window.matchMedia is not a function".
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

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
