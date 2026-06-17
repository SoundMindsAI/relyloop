// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E modal-only smoke for the "Reset to demo state" engine selector.
 *
 * feat_selective_engine_startup_and_demo Story 3.1 / FR-8.
 *
 * Real-backend, no `page.route()` mocking. Opens the dialog, asserts the
 * checkbox group renders, asserts the Confirm-disabled state when the
 * operator unchecks everything. Does NOT trigger an actual reseed — that
 * would take 5-9 minutes. The long-running E2E (full reseed against the
 * stack) lives at `demo-ubi.spec.ts` and is CI-excluded.
 *
 * The capability endpoint `/api/v1/_test/demo/engines` is read by this
 * page's dialog when it opens; the spec runs against whatever engine
 * subset is currently reachable on the dev stack. Both "all three"
 * (the default `make up` posture) and a subset (operator opted into
 * RELYLOOP_ENGINES=es) are valid — the test just asserts the structural
 * shape (3 checkboxes, Confirm disabled when none selected) without
 * pinning to a specific reachable engine count.
 */

import { expect, test } from '@playwright/test';

test('reset modal renders engine-selection checkbox group + Confirm disabled when empty', async ({
  page,
}) => {
  await page.goto('/');

  // Click the trigger button to open the dialog.
  const trigger = page.getByTestId('reset-demo-state-trigger');
  await expect(trigger).toBeVisible();
  await trigger.click();

  // Dialog opens; the engines section renders.
  const engines = page.getByTestId('reset-demo-state-engines');
  await expect(engines).toBeVisible();
  await expect(engines).toContainText('Engines to reseed');

  // Three checkboxes, one per engine type, in deterministic order.
  const esCheckbox = page.getByTestId('engine-checkbox-elasticsearch');
  const osCheckbox = page.getByTestId('engine-checkbox-opensearch');
  const solrCheckbox = page.getByTestId('engine-checkbox-solr');
  await expect(esCheckbox).toBeVisible();
  await expect(osCheckbox).toBeVisible();
  await expect(solrCheckbox).toBeVisible();

  // Uncheck only the ones that are currently checked AND enabled —
  // unreachable engines are already disabled and shouldn't be toggled.
  for (const checkbox of [esCheckbox, osCheckbox, solrCheckbox]) {
    const isEnabled = await checkbox.isEnabled();
    const isChecked = await checkbox.isChecked();
    if (isEnabled && isChecked) {
      await checkbox.uncheck();
    }
  }

  // Confirm button is now disabled + the helper hint appears.
  const confirm = page.getByTestId('reset-demo-state-confirm');
  await expect(confirm).toBeDisabled();
  await expect(page.getByTestId('reset-demo-engines-empty-hint')).toBeVisible();

  // Closing the dialog without confirming should not start a reseed.
  await page.getByTestId('reset-demo-state-cancel').click();
  // (No reseed actually fired — we never clicked Confirm.)
});
