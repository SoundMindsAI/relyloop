/// <reference types="vitest" />
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
    include: [
      'src/**/*.test.{ts,tsx}',
      // chore_e2e_test_rows_isolation Story 1.2: vitest tests for the
      // Playwright cleanup machinery (cleanup-core.ts + global-teardown.ts)
      // live alongside the modules they test under tests/e2e/. Playwright
      // ignores *.test.ts (its spec extension is .spec.ts), so vitest is
      // the sole consumer.
      'tests/e2e/**/*.test.ts',
    ],
    // Pin the api-client base URL to a non-resolvable host so msw can
    // intercept requests safely. Without this, `apiClient` defaults to
    // http://localhost:8000 and (when the dev stack is running) tests
    // hit the real backend instead of the msw mock.
    env: {
      NEXT_PUBLIC_API_BASE_URL: 'http://api.test',
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
});
