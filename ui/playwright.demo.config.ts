// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Playwright config for RelyLoop walkthrough guides.
 *
 * Separate from `playwright.config.ts` (the regression e2e config) because:
 *  - Demo runs use slow-mo + video for human-watchable artifacts
 *  - Viewport is locked at 1440×960 so screenshots are stable across machines
 *  - `outputDir` lands under `test-results/demo-artifacts/` so the regular e2e
 *    artifacts directory stays uncluttered
 *  - Guides write PNGs directly to `ui/public/guides/<NN_slug>/` so Next.js
 *    serves them with no copy step
 *
 * Run:
 *   cd ui
 *   pnpm playwright test -c playwright.demo.config.ts --project=chromium
 *
 * The full `make up` stack must be running first (UI at :3000, API at :8000).
 */
import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:3000';
const API_BASE_URL = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

export default defineConfig({
  testDir: './tests/e2e/guides',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  outputDir: 'test-results/demo-artifacts',
  timeout: 60_000,
  use: {
    baseURL: BASE_URL,
    extraHTTPHeaders: { Accept: 'application/json' },
    viewport: { width: 1440, height: 960 },
    video: 'on',
    trace: 'retain-on-failure',
    launchOptions: { slowMo: 60 },
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          slowMo: 60,
          // --disable-extensions prevents browser extensions (e.g. Notion Web
          // Clipper, password managers) from injecting overlays into
          // screenshots. Critical for stable visual output across machines.
          args: ['--disable-extensions'],
        },
      },
    },
  ],
  metadata: { apiBaseUrl: API_BASE_URL },
});
