// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: feat_index_document_browser top-down + filter chip flow.
 *
 * Covers AC-1, AC-2, AC-3, AC-5, AC-19 against the real backend.
 *
 * Setup:
 *  - Bulk-load ~30 docs into a unique ES test index.
 *  - Register a cluster pointing at the engine.
 *  - Tests navigate: /clusters → cluster detail → Indices card → index
 *    summary → documents list → document detail → studies-list filter chip.
 *
 * No page.route() mocking — assertions use Playwright's `page` against
 * the live backend.
 */
import { randomUUID } from 'crypto';
import { expect, test } from '@playwright/test';

import { appendForCleanup, seedCluster } from './helpers/seed';

const ES_BASE = process.env.PLAYWRIGHT_ES_BASE_URL ?? 'http://127.0.0.1:9200';

async function seedDocumentsIndex(): Promise<string> {
  const indexName = `e2e-docs-${randomUUID().slice(0, 8)}`;
  // Best-effort wipe of any prior run with the same suffix.
  await fetch(`${ES_BASE}/${indexName}`, { method: 'DELETE' }).catch(() => {});

  const lines: string[] = [];
  for (let i = 0; i < 30; i += 1) {
    lines.push(
      JSON.stringify({ index: { _index: indexName, _id: `doc-${i.toString().padStart(3, '0')}` } }),
    );
    lines.push(
      JSON.stringify({
        title: `Title ${i}`,
        brand: `Brand ${i % 5}`,
        price: 10 + i,
      }),
    );
  }
  const body = `${lines.join('\n')}\n`;
  const resp = await fetch(`${ES_BASE}/_bulk?refresh=true`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-ndjson' },
    body,
  });
  if (!resp.ok) {
    throw new Error(`bulk seed failed: HTTP ${resp.status} — ${await resp.text()}`);
  }
  return indexName;
}

test.describe('feat_index_document_browser top-down flow', () => {
  test('navigate cluster → indices card → summary → documents → detail', async ({ page }) => {
    const indexName = await seedDocumentsIndex();
    const cluster = await seedCluster();

    // Cluster detail → indices card.
    await page.goto(`/clusters/${cluster.id}`);
    const indicesTable = page.getByTestId('indices-card-table');
    await expect(indicesTable).toBeVisible();

    // Find the row for our seeded index and click into the summary.
    const indexRow = page.getByTestId(`indices-card-row-${indexName}`);
    await expect(indexRow).toBeVisible();
    await indexRow.getByRole('link', { name: indexName }).click();

    // Index summary page.
    await expect(page).toHaveURL(new RegExp(`/clusters/${cluster.id}/indices/${indexName}$`));
    await expect(page.getByTestId('index-summary-header')).toBeVisible();
    await expect(page.getByTestId('index-summary-browse-link')).toBeVisible();
    await expect(page.getByTestId('index-summary-studies-link')).toBeVisible();

    // Documents list.
    await page.getByTestId('index-summary-browse-link').click();
    await expect(page).toHaveURL(
      new RegExp(`/clusters/${cluster.id}/indices/${indexName}/documents$`),
    );
    await expect(page.getByTestId('documents-list-table')).toBeVisible();
    const totalCount = page.getByTestId('documents-list-total-count');
    await expect(totalCount).toContainText(/30 documents/);

    // Click the first row to drill into the detail page.
    const firstRow = page.getByTestId('documents-row-doc-000');
    await expect(firstRow).toBeVisible();
    await firstRow.getByRole('link', { name: 'doc-000' }).click();

    // Document detail page.
    await expect(page).toHaveURL(/documents\/doc-000$/);
    await expect(page.getByTestId('document-detail-json')).toBeVisible();
    const pre = page.getByTestId('document-detail-json');
    await expect(pre).toContainText('"title"');
    await expect(pre).toContainText('"Title 0"');

    // Cleanup the ES test index (cluster cleanup is handled by seedCluster's appendForCleanup).
    await fetch(`${ES_BASE}/${indexName}`, { method: 'DELETE' }).catch(() => {});
  });
});

test.describe('feat_index_document_browser studies ?target= filter chip', () => {
  test('navigating to /studies?target=foo renders the active filter chip', async ({ page }) => {
    // Hardcoded link — no API state required because the chip rendering
    // depends only on URL searchParams, and the underlying list query
    // returns an empty array (no studies with target=hypothetical-index).
    await page.goto('/studies?target=hypothetical-index');
    await expect(page.getByTestId('studies-target-filter-chip')).toBeVisible();
    await expect(page.getByTestId('studies-target-filter-chip')).toContainText(
      'hypothetical-index',
    );

    // Clicking × drops the param.
    await page.getByTestId('studies-target-filter-clear').click();
    await expect(page).toHaveURL(/\/studies$/);
    await expect(page.getByTestId('studies-target-filter-chip')).not.toBeVisible();
  });
});

// Suppress an unused-import warning that ESLint can flag depending on flag.
void appendForCleanup;
