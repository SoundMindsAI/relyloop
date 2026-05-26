/**
 * E2E spec: clone-with-narrow-bounds happy path
 * (feat_study_clone_narrow_bounds Story 1.4, AC-12).
 *
 * Drives the full clone-then-narrow flow against the real backend with no
 * `page.route()` mocking:
 *   1. Seed a completed study + digest via `seedStudyCompletedWithDigest`.
 *      Fixture provenance (do NOT silently let this drift): the test-only
 *      seed at backend/app/services/test_seeding.py:75-88 writes
 *      `search_space.params.boost = { type: 'float', low: 0.5,
 *      high: 5.0, log: false }`, and line 188 writes
 *      `recommended_config = { boost: 2.5 }`. The narrow-bounds
 *      ±20% clamp around 2.5 is therefore [2.0, 3.0], which fits inside
 *      [0.5, 5.0]. If either seed value changes, this test will fail
 *      loudly with a numeric mismatch — which is the right signal.
 *   2. Navigate to `/studies/<sourceId>` and click "Clone study".
 *   3. Walk Steps 1-3 of the modal, land on Step 4.
 *   4. Assert the narrow-bounds checkbox is visible (FR-1 gate open).
 *   5. Check it; parse the textarea; assert the clamped numeric bounds.
 *      Uncheck; assert the textarea restores to the source's bounds.
 *      Re-check to lock the clamped state in for submit.
 *   6. Advance to Step 5; click "Create study"; capture the POST response
 *      and the new study id. GET /api/v1/studies/{new_id} via `request`;
 *      assert the persisted `search_space.params.boost.low/high` carry
 *      the clamped [2.0, 3.0] bounds (FR-12 — server accepted the
 *      rewrite) AND `parent_study_id === sourceId` (FR-9 — lineage
 *      round-trip mirrors the v1 clone-spec at study-clone.spec.ts:24).
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudyCompletedWithDigest } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

test('Clone study → narrow bounds → submit → persisted search_space is clamped', async ({
  page,
  request,
}) => {
  // 1. Seed.
  const chain = await seedFullChain();
  const completed = await seedStudyCompletedWithDigest({
    clusterId: chain.clusterId,
    querySetId: chain.querySetId,
    templateId: chain.templateId,
    judgmentListId: chain.judgmentListId,
    withPendingProposal: false,
  });
  const sourceId = completed.studyId;

  // 2. Navigate to source detail and click Clone.
  await page.goto(`/studies/${sourceId}`);
  await expect(page.getByTestId('clone-study')).toBeVisible({ timeout: 10_000 });
  await page.getByTestId('clone-study').click();

  // Banner indicates the clone-mode modal opened.
  await expect(page.getByTestId('cloned-from-banner')).toBeVisible({ timeout: 10_000 });

  // 3. Walk Steps 1-3 → Step 4.
  await page.getByTestId('step-next').click(); // 1 → 2
  await page.getByTestId('step-next').click(); // 2 → 3
  await page.getByTestId('step-next').click(); // 3 → 4
  await expect(page.getByTestId('step-4')).toBeVisible();

  // 4. Narrow-bounds section is gated on a successful digest fetch; the
  //    seed wrote a real digest so the FR-1 gate opens.
  const checkbox = page.getByTestId('narrow-bounds-checkbox');
  await expect(checkbox).toBeVisible({ timeout: 10_000 });

  // 5a. Check it; read the textarea; assert the clamp.
  await checkbox.check();
  const textareaValue = await page.getByTestId('cs-search-space').inputValue();
  const parsed = JSON.parse(textareaValue) as {
    params: {
      boost: { type: string; low: number; high: number; log?: boolean };
    };
  };
  // ±20% around winner=2.5 → [2.0, 3.0]; fits inside source [0.5, 5.0].
  expect(parsed.params.boost.type).toBe('float');
  expect(parsed.params.boost.low).toBeCloseTo(2.0, 6);
  expect(parsed.params.boost.high).toBeCloseTo(3.0, 6);

  // 5b. Uncheck → assert textarea restores to the verbatim source bounds.
  //     Validates FR-5 (uncheck → restore) at the browser layer.
  await checkbox.uncheck();
  const restoredValue = await page.getByTestId('cs-search-space').inputValue();
  const restored = JSON.parse(restoredValue) as {
    params: { boost: { low: number; high: number } };
  };
  expect(restored.params.boost.low).toBe(0.5);
  expect(restored.params.boost.high).toBe(5.0);

  // 5c. Re-check to put the textarea back to the clamped state for submit.
  //     (We want to verify the SERVER receives + persists the narrowed
  //     bounds, not the source bounds.) Poll-wait for the textarea to
  //     reflect the re-applied clamp before advancing — without this,
  //     a fast click could submit the still-restored source bounds and
  //     hide a real bug behind a race. Per GPT-5.5 round 1 review.
  await checkbox.check();
  await expect
    .poll(async () => {
      const v = await page.getByTestId('cs-search-space').inputValue();
      const p = JSON.parse(v) as { params: { boost: { low: number } } };
      return p.params.boost.low;
    })
    .toBeCloseTo(2.0, 6);

  // 6. Advance Step 4 → 5 (objective + config), submit, capture the POST
  //    response. Pattern mirrors ui/tests/e2e/study-clone.spec.ts:24.
  await page.getByTestId('step-next').click();
  await expect(page.getByTestId('step-5')).toBeVisible();

  const postResponsePromise = page.waitForResponse(
    (r) => r.url().endsWith('/api/v1/studies') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: /Create study/i }).click();
  const postResponse = await postResponsePromise;
  // Spec-correct create semantics: assert 201 explicitly so a future
  // 200/202/204 regression doesn't silently pass. Per GPT-5.5 round 1.
  expect(postResponse.status()).toBe(201);
  const created = (await postResponse.json()) as {
    id: string;
    parent_study_id: string | null;
  };

  // FR-9 round-trip — clone lineage persisted (same assertion as v1 clone-spec).
  expect(created.parent_study_id).toBe(sourceId);

  // FR-12 round-trip — re-fetch the new study and confirm the persisted
  // search_space carries the narrowed [2.0, 3.0] bounds. This is the
  // load-bearing assertion this spec extension exists to add: the server
  // accepted the textarea-driven rewrite and the bounds round-trip via
  // GET. The narrowing algorithm itself is also covered by the unit
  // invariant at ui/src/__tests__/lib/narrow-bounds.test.ts; this spec
  // confirms the wire contract holds end-to-end.
  const reloadResp = await request.get(`${API_BASE}/api/v1/studies/${created.id}`);
  expect(reloadResp.ok()).toBe(true);
  const reloaded = (await reloadResp.json()) as {
    parent_study_id: string | null;
    search_space: { params: { boost: { type: string; low: number; high: number } } };
  };
  expect(reloaded.parent_study_id).toBe(sourceId);
  expect(reloaded.search_space.params.boost.type).toBe('float');
  expect(reloaded.search_space.params.boost.low).toBeCloseTo(2.0, 6);
  expect(reloaded.search_space.params.boost.high).toBeCloseTo(3.0, 6);
});
