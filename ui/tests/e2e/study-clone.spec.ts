/**
 * E2E spec: clone-a-study happy path (feat_study_clone_from_previous Story 3.1).
 *
 * Drives the full clone flow against the real backend with no `page.route()`
 * mocking:
 *   1. Seed cluster + template + query set + judgment list + completed study
 *      via the public `seedFullChain` + `seedStudyCompletedWithDigest` helpers.
 *   2. Navigate to `/studies/<sourceId>` and click the "Clone study" button.
 *   3. Assert direct navigation to `/studies` (completed source → no confirm
 *      dialog), the deep-link query-string is cleared by `router.replace`,
 *      and the cloned-from banner is visible inside the create-study modal.
 *   4. Walk the wizard and submit → POST /api/v1/studies should return a new
 *      study whose `parent_study_id` matches the source id (the wire-format
 *      contract added in Story 1.1).
 *   5. GET /api/v1/studies/<newId> → assert the persisted row carries the
 *      same `parent_study_id`.
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudyCompletedWithDigest } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

test('Clone study from study-detail → banner + parent_study_id round-trip', async ({
  page,
  request,
}) => {
  // 1. Seed a completed parent chain + a completed study.
  const chain = await seedFullChain();
  const completed = await seedStudyCompletedWithDigest({
    clusterId: chain.clusterId,
    querySetId: chain.querySetId,
    templateId: chain.templateId,
    judgmentListId: chain.judgmentListId,
    withPendingProposal: false,
  });
  const sourceId = completed.studyId;

  // Fetch the source's name so we can spot-check the banner copy.
  const sourceResp = await request.get(`${API_BASE}/api/v1/studies/${sourceId}`);
  expect(sourceResp.ok()).toBe(true);
  const source = (await sourceResp.json()) as { id: string; name: string };

  // 2. Navigate to study-detail and click Clone.
  await page.goto(`/studies/${sourceId}`);
  await expect(page.getByTestId('clone-study')).toBeVisible({ timeout: 10_000 });
  await page.getByTestId('clone-study').click();

  // 3. Source is `completed` → direct navigation, no running-confirm dialog.
  //    The deep-link reader on /studies opens the modal with prefill and
  //    clears the `?clone_from` query param via router.replace.
  await page.waitForURL(/\/studies$/, { timeout: 5_000 });
  await expect(page).not.toHaveURL(/clone_from/);
  await expect(page.getByTestId('cloned-from-banner')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('cloned-from-banner')).toContainText(source.name);

  // 4. Walk the wizard and submit. The form is prefilled from the source,
  //    including search_space + objective + config + the name (which the
  //    helper appends " (clone)" to per FR-5).
  // Step 1 (cluster + target) → next.
  await page.getByTestId('step-next').click();
  // Step 2 (data sources) → next.
  await page.getByTestId('step-next').click();
  // Step 3 (template) → next.
  await page.getByTestId('step-next').click();
  // Step 4 (identity) — verify the prefilled name carries the " (clone)" suffix.
  const nameInput = page.getByLabel('Study name');
  await expect(nameInput).toBeVisible();
  await expect(nameInput).toHaveValue(/\(clone\)$/);
  await page.getByTestId('step-next').click();
  // Step 5 (objective + config) — submit and capture the POST response so we
  // can read the new id directly (the modal does not auto-navigate to the
  // new study per spec §11 step 8).
  const postResponsePromise = page.waitForResponse(
    (r) => r.url().endsWith('/api/v1/studies') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: /Create study/i }).click();
  const postResponse = await postResponsePromise;
  expect(postResponse.ok()).toBe(true);
  const created = (await postResponse.json()) as { id: string; parent_study_id: string | null };

  // FR-6 / FR-9 round-trip: the create endpoint persists parent_study_id.
  expect(created.parent_study_id).toBe(sourceId);

  // 5. Re-fetch the new study via the public API and confirm lineage persists.
  const reloadResp = await request.get(`${API_BASE}/api/v1/studies/${created.id}`);
  expect(reloadResp.ok()).toBe(true);
  const reloaded = (await reloadResp.json()) as { parent_study_id: string | null };
  expect(reloaded.parent_study_id).toBe(sourceId);
});
