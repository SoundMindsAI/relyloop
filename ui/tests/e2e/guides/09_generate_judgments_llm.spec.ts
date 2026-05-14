/**
 * Walkthrough: Generate judgments via LLM (guide 09).
 *
 * Captures the LLM-driven judgment-generation flow end-to-end against
 * the real hosted OpenAI endpoint (no mocking — per user direction).
 * Each (query, top-K doc) pair fires one LLM call; cost ~$0.02-0.05
 * per run with gpt-4o-mini.
 *
 * Structure: drive the UI for the form-interaction screenshots (modal
 * empty → text fields filled → template dropdown open), then trigger
 * the generation via direct API call for the worker-state screenshots.
 * This sidesteps a Radix Select interaction issue where the
 * portal-mounted listbox renders options outside the viewport when many
 * templates are seeded, leaving keyboard nav unable to select reliably.
 */
import path from 'node:path';
import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

import { seedQuerySet, seedTemplate } from '../helpers/seed';

const SCREENSHOTS = path.resolve(__dirname, '../../../public/guides/09_generate_judgments_llm');
const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

test.describe('Walkthrough: Generate judgments via LLM', () => {
  test.setTimeout(240_000);

  test('captures the generate-judgments LLM flow', async ({ page, request }) => {
    const tpl = await seedTemplate();
    const { querySetId, clusterId } = await seedQuerySet(2);

    // ── 01: Query set detail ──────────────────────────────────────────
    await page.goto(`/query-sets/${querySetId}`);
    await page.waitForTimeout(600);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '01-query-set-detail-no-judgments.png'),
    });

    // ── 02: Open the Generate dialog ──────────────────────────────────
    await page.getByTestId('open-generate-judgments').click();
    await expect(page.getByTestId('generate-form')).toBeVisible({ timeout: 5_000 });
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SCREENSHOTS, '02-generate-dialog-empty.png') });

    // ── 03: Fill the text fields ──────────────────────────────────────
    const listName = `walkthrough-${randomUUID().slice(0, 6)}`;
    await page.getByLabel('Judgment list name', { exact: true }).fill(listName);
    await page.getByLabel(/Target index/).fill('products');
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SCREENSHOTS, '03-generate-dialog-text-filled.png') });

    // ── 04: Open the template dropdown so the screenshot shows options ─
    await page.locator('#gen-template').click();
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '04-template-dropdown-open.png'),
      fullPage: false,
    });
    // Close the dropdown + cancel the modal — we trigger generation via API
    // because the portal-mounted listbox is fragile in headless Chromium
    // when many templates are seeded.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    // Trigger generation via the API with the seeded template. This is the
    // same payload the UI submits — the API contract is identical.
    const apiResp = await request.post(`${API_BASE}/api/v1/judgments/generate`, {
      data: {
        name: listName,
        query_set_id: querySetId,
        cluster_id: clusterId,
        target: 'products',
        current_template_id: tpl.id,
        rubric:
          'Rate the relevance of each retrieved document to the query on a 0-3 scale: 0 = irrelevant, 1 = marginally related, 2 = relevant, 3 = highly relevant.',
      },
    });
    if (!apiResp.ok()) {
      throw new Error(`generate POST failed: ${apiResp.status()} ${await apiResp.text()}`);
    }
    const { judgment_list_id: judgmentListId } = (await apiResp.json()) as {
      judgment_list_id: string;
    };

    // Navigate to the judgment list detail page; worker is now generating.
    await page.goto(`/judgments/${judgmentListId}`);
    await page.waitForTimeout(800);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '05-judgment-list-terminal-state.png'),
      fullPage: true,
    });

    // ── 06 (best-effort): Poll for terminal state ─────────────────────
    // Worker hits OpenAI per (query, doc) pair. With 2 queries × top-K docs
    // this is typically <60s. Cap at 180s.
    const deadlineMs = Date.now() + 180_000;
    let terminalStatus: string | null = null;
    while (Date.now() < deadlineMs) {
      const detail = await request.get(`${API_BASE}/api/v1/judgment-lists/${judgmentListId}`);
      if (!detail.ok()) break;
      const body = (await detail.json()) as { status: string };
      if (body.status === 'complete' || body.status === 'failed') {
        terminalStatus = body.status;
        break;
      }
      await page.waitForTimeout(3_000);
    }
    // Re-capture once terminal (or once the polling cap elapses).
    await page.reload();
    await page.waitForTimeout(1_000);
    const filename =
      terminalStatus === 'complete'
        ? '05-judgment-list-terminal-state.png'
        : '05-judgment-list-terminal-state.png';
    void filename; // same path either way — we want the final state
    await page.screenshot({
      path: path.join(SCREENSHOTS, '05-judgment-list-terminal-state.png'),
      fullPage: true,
    });
  });
});
