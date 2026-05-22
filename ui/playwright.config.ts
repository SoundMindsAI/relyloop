/**
 * Playwright config for RelyLoop UI E2E.
 *
 * Tests run against the real backend at `localhost:8000` and the real
 * UI at `localhost:3000`. Both must be running (operator runs `make up`
 * before invoking `pnpm test:e2e`). CI starts the stack via the docker
 * compose service containers in `.github/workflows/pr.yml`.
 *
 * Chromium-only by default (fastest). Add `firefox` / `webkit` projects
 * if cross-browser coverage is needed later.
 */
import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:3000';
const API_BASE_URL = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

export default defineConfig({
  testDir: './tests/e2e',
  // Match only Playwright's .spec.ts extension. The .test.ts files under
  // tests/e2e/ (chore_e2e_test_rows_isolation Story 1.2) are vitest tests
  // for the cleanup machinery — vitest owns them via vitest.config.ts.
  testMatch: ['**/*.spec.ts'],
  // Walkthrough guides run under playwright.demo.config.ts (slow-mo, video,
  // 1440×960 viewport) — exclude them from regression runs so they don't
  // overwrite canonical guide PNGs at unexpected viewport sizes.
  testIgnore: ['**/guides/**'],
  fullyParallel: false, // single backend stack — keep specs serial to avoid data races
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  // chore_e2e_test_rows_isolation Story 1.2:
  //   globalSetup clears stale cleanup artifacts before each run.
  //   globalTeardown drains the per-worker JSONL cleanup registry against
  //     the live backend via the new /api/v1/_test/* DELETE endpoints.
  //   cleanup-reporter verifies the cleanup-summary.json invariants in onEnd.
  globalSetup: './tests/e2e/global-setup.ts',
  globalTeardown: './tests/e2e/global-teardown.ts',
  reporter: [
    process.env.CI ? ['github'] : ['list'],
    ['./tests/e2e/cleanup-reporter.ts'],
  ],
  timeout: 30_000,
  use: {
    baseURL: BASE_URL,
    extraHTTPHeaders: {
      Accept: 'application/json',
    },
    trace: process.env.CI ? 'on-first-retry' : 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // We do NOT start servers from playwright — the operator/CI controls the
  // stack via `make up`. This keeps the config simple and avoids
  // Playwright trying to manage Docker.
  metadata: {
    apiBaseUrl: API_BASE_URL,
  },
});
