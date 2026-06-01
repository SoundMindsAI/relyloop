// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Register your first cluster (guide 01).
 *
 * Captures the operator's first-time cluster-registration journey using the
 * **acme-products-prod** scenario from `scripts/seed_meaningful_demos.py` so
 * the screenshots look like a real production e-commerce cluster rather than
 * a `walkthrough-{6hex}` dev-test artifact. The Target filter input
 * (`feat_cluster_target_filter`, PR #168) is filled with `products*` to teach
 * the per-cluster index-scoping feature.
 *
 * The spec is self-contained — it does NOT depend on `make seed-demo` having
 * run; it just borrows the scenario's naming + field values. The cluster name
 * is suffixed with `randomUUID().slice(0, 6)` so reruns and seeded state don't
 * collide.
 *
 * Usage:
 *   cd ui
 *   pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/01_register_first_cluster.spec.ts
 *
 * Prerequisite: `make up` stack running (UI at :3000, API at :8000).
 */
import path from 'node:path';
import { randomUUID } from 'node:crypto';

import { expect, test, request as pwRequest } from '@playwright/test';

import { appendForCleanup } from '../helpers/seed';

const SCREENSHOTS = path.resolve(__dirname, '../../../public/guides/01_register_first_cluster');
const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

test.describe('Walkthrough: Register your first cluster', () => {
  test('captures the full cluster-registration journey', async ({ page }) => {
    // Mirror scripts/seed_meaningful_demos.py SCENARIOS[0] (acme-products-prod)
    // with a UUID suffix so reruns and the already-seeded canonical cluster
    // don't collide. Everything else (engine, URL, auth, creds, env, target
    // filter) comes verbatim from the seed scenario.
    const name = `acme-products-prod-${randomUUID().slice(0, 6)}`;
    const notes = 'Production Elasticsearch cluster — e-commerce product search.';
    const targetFilter = 'products*';

    // Pre-seed one OpenSearch + one Solr cluster (via API) so the landing
    // clusters-list screenshot demonstrates RelyLoop's three-engine reach —
    // the engine filter chips (all / elasticsearch / opensearch / solr) and
    // the per-engine <EngineBadge> only tell the multi-engine story when rows
    // of each engine actually exist. The walkthrough itself still registers an
    // Elasticsearch cluster step-by-step below; these two just enrich the list.
    const sfx = randomUUID().slice(0, 6);
    const apiCtx = await pwRequest.newContext({ baseURL: API_URL });
    const preSeed: Array<{ name: string; engine_type: string; base_url: string; auth_kind: string; credentials_ref: string; environment: string }> = [
      {
        name: `news-search-staging-${sfx}`,
        engine_type: 'opensearch',
        base_url: 'http://opensearch:9200',
        auth_kind: 'opensearch_basic',
        credentials_ref: 'local-opensearch',
        environment: 'staging',
      },
      {
        name: `acme-kb-docs-solr-${sfx}`,
        engine_type: 'solr',
        base_url: 'http://solr:8983',
        auth_kind: 'solr_basic',
        credentials_ref: 'local-solr',
        environment: 'prod',
      },
    ];
    for (const c of preSeed) {
      const r = await apiCtx.post('/api/v1/clusters', { data: c });
      if (r.status() === 201) {
        const body = (await r.json()) as { id: string };
        appendForCleanup('cluster', body.id);
      }
    }
    await apiCtx.dispose();

    // ── 01: Land on /clusters list ─────────────────────────────────────
    await page.goto('/clusters');
    await expect(page.getByTestId('open-register-cluster')).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '01-clusters-list.png'),
      fullPage: false,
    });

    // ── 02: Open the register modal ────────────────────────────────────
    await page.getByTestId('open-register-cluster').click();
    await expect(page.getByTestId('register-form')).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '02-register-modal-empty.png'),
      fullPage: false,
    });

    // ── 03: Fill the form (acme-products-prod realistic values) ───────
    await page.getByLabel('Name', { exact: true }).fill(name);
    await page.getByLabel('Base URL', { exact: true }).fill('http://elasticsearch:9200');
    await page.getByLabel(/^Credentials ref/).fill('local-es');

    // The acme scenario uses Production environment.
    await page.locator('#cl-env').click();
    await page.getByRole('option', { name: 'prod' }).click();

    // local-es credentials are username+password; switch auth_kind to match.
    await page.locator('#cl-auth').click();
    await page.getByRole('option', { name: 'es_basic' }).click();

    // Notes: describe the scenario in operator-relatable language.
    await page.getByLabel('Notes', { exact: true }).fill(notes);

    // Target filter: scope this cluster's index picker to the e-commerce
    // products family. The caption for this step teaches the new feature.
    await page.getByLabel(/^Target filter/).fill(targetFilter);

    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '03-register-modal-filled.png'),
      fullPage: true,
    });

    // ── 04: Submit + wait for the 201 ─────────────────────────────────
    const registerPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes('/api/v1/clusters') &&
        resp.request().method() === 'POST' &&
        resp.status() < 500,
      { timeout: 15_000 },
    );
    await page.getByTestId('register-submit').click();
    const resp = await registerPromise;
    expect(resp.status()).toBe(201);

    // ── 05: New cluster appears in the list with health probe result ──
    await expect(page.getByTestId('register-form')).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(600);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '04-cluster-registered.png'),
      fullPage: false,
    });

    // ── 06: Click the row → detail page ────────────────────────────────
    await page.getByText(name).first().click();
    await page.waitForURL(/\/clusters\/[a-f0-9-]+$/, { timeout: 10_000 });
    await page.waitForTimeout(600);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '05-cluster-detail.png'),
      fullPage: false,
    });
  });
});
