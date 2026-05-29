/**
 * E2E spec: SearchSpaceBuilder (`feat_create_study_search_space_builder` Story 4.1).
 *
 * Real-backend; no `page.route()` mocking. Four cases:
 *
 *   1. Happy path — builder edit `boost.high = 15` propagates to textarea,
 *      submitted study persists the value.
 *   2. Type switch — float → int → float via the type selector; the
 *      cross-type stash restores the original `{low, high, log}` after the
 *      round-trip.
 *   3. Categorical chip input — switch `boost` to `categorical`, add three
 *      mixed-type chips (`true`, `1`, `AUTO`); textarea reflects them in
 *      order with proper coercion + duplicates preserved.
 *   4. Cardinality cap warning — engineer a high-cardinality int row; the
 *      header counter turns red + identifies the max contributor while the
 *      Next button stays enabled (warning-only per FR-7).
 *
 * Stability note: mirrors the EntitySelect-click pattern from
 * `studies-create-validation.spec.ts` (toBeEnabled + dispatchEvent click).
 */
import { type Locator, type Page, expect, test } from '@playwright/test';

import { seedFullChain } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';
const ENTITY_SELECT_TIMEOUT = 10_000;

async function getName(path: string): Promise<string> {
  const resp = await fetch(new URL(path, API_BASE).toString());
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  const body = (await resp.json()) as { name: string };
  return body.name;
}

async function pickEntity(
  page: Page,
  triggerTestId: string,
  optionName: string | RegExp,
): Promise<void> {
  const trigger: Locator = page.getByTestId(triggerTestId);
  await expect(trigger).toBeEnabled({ timeout: ENTITY_SELECT_TIMEOUT });
  await trigger.dispatchEvent('click');
  await page.getByRole('option', { name: optionName }).first().click();
}

/**
 * Switch a builder row's `<RowTypeSelector>` (a Radix Select rendered as
 * a `<button role="combobox">`). `selectOption` does NOT work on Radix
 * Select — click the trigger to open the listbox, then click the matching
 * option in the Radix portal.
 */
async function switchRowType(
  page: Page,
  paramName: string,
  nextType: 'float' | 'int' | 'categorical',
): Promise<void> {
  const trigger = page.getByTestId(`cs-row-${paramName}-type`);
  await expect(trigger).toBeEnabled({ timeout: ENTITY_SELECT_TIMEOUT });
  await trigger.dispatchEvent('click');
  // Each SelectItem renders with its `value` as both the displayed text and
  // the option name (see row-type-selector.tsx). Match by role+name; the
  // matcher is the literal string for the three discriminator values.
  await page.getByRole('option', { name: nextType, exact: true }).click();
}

/**
 * Walks Steps 1–3 of the create-study wizard against a freshly seeded
 * cluster + query-set + template + judgment-list. Returns the seeded
 * fixture so each test can assert against it.
 */
async function walkToStep4(page: Page): Promise<{
  clusterName: string;
  templateName: string;
  querySetName: string;
  judgmentListName: string;
}> {
  // Pin the judgment-list target to the same string the study fills below
  // ('e2e-builder-target') so the feat_study_target_judgment_mismatch_guard
  // FR-4 dropdown filter matches and the Step-2 judgment-list picker is
  // enabled. Without this override, seedFullChain defaults the JL to
  // target='products', the modal's ?target=e2e-builder-target wire filter
  // returns 0 rows, and the cs-jl trigger renders disabled.
  const chain = await seedFullChain(2, { judgmentListTarget: 'e2e-builder-target' });
  const querySetName = await getName(`/api/v1/query-sets/${chain.querySetId}`);
  const judgmentListName = await getName(`/api/v1/judgment-lists/${chain.judgmentListId}`);

  await page.goto('/studies');
  await page.getByTestId('open-create-study').click();
  await expect(page.getByTestId('create-study-form')).toBeVisible({ timeout: 5_000 });

  await pickEntity(page, 'cs-cluster', chain.clusterName);
  // feat_create_study_target_autocomplete F2: target is an EntitySelect by
  // default. Flip into manual mode so the fill() path still works without
  // requiring this test to seed an ES index for the dropdown.
  await page.getByRole('button', { name: 'Enter manually' }).click();
  await page.getByLabel('Target index / collection').fill('e2e-builder-target');
  await page.getByTestId('step-next').click();

  await pickEntity(page, 'cs-qs', querySetName);
  await pickEntity(page, 'cs-jl', judgmentListName);
  await page.getByTestId('step-next').click();

  await pickEntity(page, 'cs-tpl', chain.templateName);
  await page.getByTestId('step-next').click();

  await expect(page.getByTestId('step-4')).toBeVisible({ timeout: 5_000 });
  await expect(page.getByTestId('cs-search-space-builder')).toBeVisible();
  // Wait for the auto-fill effect + canonicalize-on-mount to land.
  await expect(page.getByTestId('cs-param-row-boost')).toBeVisible({ timeout: 5_000 });

  return {
    clusterName: chain.clusterName,
    templateName: chain.templateName,
    querySetName,
    judgmentListName,
  };
}

/**
 * Read the current parsed `search_space` from the textarea — the canonical
 * source-of-truth. The builder's debounce + onBlur flush ensures the
 * textarea is up to date by the time we read.
 */
async function readSearchSpace(page: Page): Promise<{ params: Record<string, unknown> }> {
  const raw = await page.getByTestId('cs-search-space').inputValue();
  return JSON.parse(raw);
}

test.describe('/studies — create-study Step-4 builder (Story 4.1)', () => {
  test('case 1: builder edits propagate to textarea + submitted study persists the value', async ({
    page,
  }) => {
    await walkToStep4(page);

    const studyName = `e2e-builder-happy-${Date.now()}`;
    await page.getByLabel('Study name').fill(studyName);

    // Edit `high` from the auto-filled default to 15 via the builder's
    // numeric input. Blur to flush synchronously.
    const highInput = page.getByTestId('cs-row-boost-high');
    await highInput.fill('15');
    await highInput.blur();

    // Assert the textarea reflects the builder edit.
    await expect(async () => {
      const parsed = await readSearchSpace(page);
      expect((parsed.params.boost as { high: number }).high).toBe(15);
    }).toPass({ timeout: 2_000 });

    // Step 4 → Step 5.
    await page.getByTestId('step-next').click();
    await expect(page.getByTestId('step-5')).toBeVisible({ timeout: 5_000 });
    await page.getByRole('spinbutton', { name: 'Max trials' }).fill('10');

    await page.getByTestId('create-study-submit').click();
    await expect(page.getByTestId('create-study-form')).not.toBeVisible({ timeout: 5_000 });

    // Fetch the created study by name and assert persistence.
    const studies = await (await fetch(new URL(`/api/v1/studies?limit=10`, API_BASE).toString())).json();
    const created = (studies.data as Array<{ id: string; name: string }>).find(
      (s) => s.name === studyName,
    );
    expect(created, `study ${studyName} not in /api/v1/studies?limit=10`).toBeDefined();
    const detail = await (await fetch(new URL(`/api/v1/studies/${created!.id}`, API_BASE).toString())).json();
    expect(detail.search_space.params.boost.high).toBe(15);
  });

  test('case 2: type switch float → int → float restores prior spec via cross-type stash (FR-2)', async ({
    page,
  }) => {
    await walkToStep4(page);

    // Capture the auto-filled FloatSpec for boost.
    const before = await readSearchSpace(page);
    const beforeBoost = before.params.boost as {
      type: 'float';
      low: number;
      high: number;
      log?: boolean;
    };
    expect(beforeBoost.type).toBe('float');

    // Switch float → int.
    await switchRowType(page, 'boost', 'int');
    await expect(async () => {
      const after = await readSearchSpace(page);
      const boost = after.params.boost as { type: string; low: number; high: number };
      expect(boost.type).toBe('int');
      // defaultSpecForType('int') = {low: 0, high: 5}
      expect(boost.low).toBe(0);
      expect(boost.high).toBe(5);
    }).toPass({ timeout: 2_000 });

    // Switch int → float; stash returns the original FloatSpec.
    await switchRowType(page, 'boost', 'float');
    await expect(async () => {
      const restored = await readSearchSpace(page);
      const boost = restored.params.boost as {
        type: string;
        low: number;
        high: number;
        log?: boolean;
      };
      expect(boost.type).toBe('float');
      expect(boost.low).toBe(beforeBoost.low);
      expect(boost.high).toBe(beforeBoost.high);
      expect(boost.log === true).toBe(beforeBoost.log === true);
    }).toPass({ timeout: 2_000 });
  });

  test('case 3: categorical chip input coerces mixed types + preserves duplicates (FR-5)', async ({
    page,
  }) => {
    await walkToStep4(page);

    // Switch boost float → categorical.
    await switchRowType(page, 'boost', 'categorical');
    await expect(async () => {
      const parsed = await readSearchSpace(page);
      expect((parsed.params.boost as { type: string }).type).toBe('categorical');
    }).toPass({ timeout: 2_000 });

    // The default-spec categorical seed is `['__placeholder__']`; remove it
    // first so we have a clean canvas for the typed coercions.
    const placeholderChip = page.getByTestId('cs-row-boost-chip-0');
    await placeholderChip.locator('button[aria-label*="Remove choice"]').click();
    await expect(async () => {
      const parsed = await readSearchSpace(page);
      expect((parsed.params.boost as { choices: unknown[] }).choices).toEqual([]);
    }).toPass({ timeout: 2_000 });

    // Add chips one at a time. Between commits, await the textarea to
    // reflect the new choice so the next commit reads the latest prop
    // value of `choices` (chip-input commits use the prop, not local
    // state — see row-categorical.tsx). Without this wait, rapid Enter
    // presses race the builder's 200ms debounce + RHF re-render cycle
    // and chips clobber each other.
    const chipInput = page.getByTestId('cs-row-boost-choices-input');
    async function addChip(raw: string, expectedAfter: unknown[]): Promise<void> {
      await chipInput.fill(raw);
      await chipInput.press('Enter');
      await expect(async () => {
        const parsed = await readSearchSpace(page);
        expect((parsed.params.boost as { choices: unknown[] }).choices).toEqual(expectedAfter);
      }).toPass({ timeout: 2_000 });
    }

    await addChip('true', [true]);
    await addChip('1', [true, 1]);
    await addChip('AUTO', [true, 1, 'AUTO']);
    // Duplicate — preserved per FR-5, NOT auto-deduped.
    await addChip('AUTO', [true, 1, 'AUTO', 'AUTO']);
  });

  test('case 4: cardinality cap > 1e6 turns header red + max-contributor hint + Next stays enabled (FR-7)', async ({
    page,
  }) => {
    await walkToStep4(page);

    // stepValid(3, values) requires values.name non-empty before Step-4 →
    // Step-5 advance — fill it now so the assertion below isolates the
    // cardinality contract from the unrelated name-required gate.
    await page.getByLabel('Study name').fill(`e2e-builder-cap-${Date.now()}`);

    // Drive `boost` to a high-cardinality int so the cap fires. With only
    // `boost` (1 row contributing 100,001) the product is 100,001 — UNDER
    // the cap. We need the cardinality > 1e6. The product is across all
    // params, so we engineer boost to alone clear the cap:
    //   int low=0, high=1_500_000 → contributes 1,500,001 (> 1e6).
    await switchRowType(page, 'boost', 'int');
    await expect(async () => {
      const parsed = await readSearchSpace(page);
      expect((parsed.params.boost as { type: string }).type).toBe('int');
    }).toPass({ timeout: 2_000 });

    await page.getByTestId('cs-row-boost-low').fill('0');
    await page.getByTestId('cs-row-boost-low').blur();
    await page.getByTestId('cs-row-boost-high').fill('1500000');
    await page.getByTestId('cs-row-boost-high').blur();

    // Header counter should now show the cap exceeded.
    const counter = page.getByTestId('cs-builder-header-cardinality');
    await expect(counter).toHaveAttribute('aria-invalid', 'true', { timeout: 2_000 });
    await expect(counter).toHaveClass(/text-destructive/);

    // Max-contributor hint should identify `boost` (the only row exceeding cap).
    const hint = page.getByTestId('cs-builder-cap-hint');
    await expect(hint).toBeVisible();
    await expect(hint).toContainText('boost');

    // FR-7 warning-only contract: Next button stays enabled.
    const next = page.getByTestId('step-next');
    await expect(next).toBeEnabled();
  });
});
