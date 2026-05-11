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

// jsdom doesn't ship Element.scrollIntoView / PointerEvent / hasPointerCapture.
// Radix-UI primitives (Select, Popover) call these on focus/keydown when
// scrolling items into view; without the stubs they throw inside an effect
// that React 19 surfaces as an unhandled error in vitest.
if (typeof Element !== 'undefined') {
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
  if (!(Element.prototype as unknown as { hasPointerCapture?: unknown }).hasPointerCapture) {
    (Element.prototype as unknown as { hasPointerCapture: () => boolean }).hasPointerCapture = () =>
      false;
  }
  if (
    !(Element.prototype as unknown as { releasePointerCapture?: unknown }).releasePointerCapture
  ) {
    (Element.prototype as unknown as { releasePointerCapture: () => void }).releasePointerCapture =
      () => {};
  }
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
