// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

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
  // testIgnore patterns:
  //
  //   - **/guides/** — walkthrough guides run under playwright.demo.config.ts
  //     (slow-mo, video, 1440×960 viewport) — exclude from regression runs so
  //     they don't overwrite canonical guide PNGs at unexpected viewport sizes.
  //
  //   - Demo-data-dependent specs (CI-only) — these specs assert on data
  //     populated by `scripts/seed_meaningful_demos.py` (4 demo cluster
  //     scenarios with full study + judgment + proposal artifacts). The seed
  //     was removed from CI on 2026-05-28:
  //       1. The original 2 specs (`dashboard.spec.ts` + `dashboard-reseed.spec.ts`)
  //          were dropped because they had been the persistent flake source
  //          (`bug_smoke_dashboard_demo_state_locator_missing`,
  //          `bug_smoke_followup_clone_e2e_flakes`). See
  //          `chore_drop_demo_seed_from_ci/idea.md`.
  //       2. PR #291's CI-perf work added `RELYLOOP_SKIP_AUTO_SEED=1` to the
  //          smoke job, which removed install.sh's auto-seed-on-`make up`
  //          (~5min). The 4th CI run surfaced 6 more specs that depend on
  //          the demo data — added below. See
  //          `chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md`.
  //     Locally the operator runs `make up` (no RELYLOOP_SKIP_AUTO_SEED) which
  //     re-enables the auto-seed; `CI=` (unset) gates these specs IN locally.
  testIgnore: [
    '**/guides/**',
    ...(process.env.CI
      ? [
          // Original 2 from chore_drop_demo_seed_from_ci:
          '**/dashboard.spec.ts',
          '**/dashboard-reseed.spec.ts',
          // PR #291 4th-run surface: 6 specs that depend on demo data
          // (clusters/studies/targets from scripts/seed_meaningful_demos.py).
          // Each was failing the same way — empty data → assertion timeout.
          '**/auto-followup.spec.ts',
          '**/index-document-browser.spec.ts',
          '**/studies-create-builder.spec.ts',
          '**/studies-create-target-dropdown.spec.ts',
          //   - infra_smoke_reseed_runtime_budget (2026-06-02): demo-ubi.spec.ts
          //     drives a `POST /api/v1/_test/demo/reseed` in beforeAll. With Solr
          //     actually booting (post infra_solr_smoke_stability PR #383's Lever-0
          //     perms fix), the reseed seeds all 6 scenarios; AC-8 of
          //     feat_demo_ubi_study_comparison bounds the in-flight reseed at
          //     1140s (~19 min hard ceiling) with ~28 min worst case per §14.
          //     Adding Playwright + smoke-job setup overhead pushes total wall-
          //     clock past the smoke job's 25-min cap (run 26790636716 hit it).
          //     Excluding here keeps the smoke job runtime-bounded; local `make
          //     up` smoke (CI= unset) retains full demo-ubi coverage. See
          //     docs/03_runbooks/smoke-solr-stability.md §4 for the lever
          //     cascade context.
          '**/demo-ubi.spec.ts',
        ]
      : []),
  ],
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
