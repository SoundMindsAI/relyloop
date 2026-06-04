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
 * Cursor + smoother pacing + WebVTT step captions via the shared demo-cursor
 * helper (feat_walkthrough_video_cursor_captions). Run video-only so the
 * committed screenshots don't churn:
 *   cd ui
 *   DEMO_VIDEO_ONLY=1 pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/01_register_first_cluster.spec.ts
 *
 * Prerequisite: `make up` stack running (UI at :3000, API at :8000).
 */
import path from 'node:path';
import { randomUUID } from 'node:crypto';

import { expect, test, request as pwRequest } from '@playwright/test';

import metadata from '../../../public/guides/01_register_first_cluster/metadata.json';
import { glide, installCursor, loadStepCaptions, shot, StepTimer, writeCaptionsVtt } from '../helpers/demo-cursor';
import { appendForCleanup } from '../helpers/seed';

const SLUG = '01_register_first_cluster';
const GUIDES_ROOT = path.resolve(__dirname, '../../../public/guides');
const SCREENSHOTS = path.join(GUIDES_ROOT, SLUG);
const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

test.describe('Walkthrough: Register your first cluster', () => {
  test('captures the full cluster-registration journey', async ({ page }) => {
    await installCursor(page);
    const captions = loadStepCaptions(metadata);
    const timer = new StepTimer(Date.now());

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
      // Assert success — a silent pre-seed failure (e.g. a wrong
      // credentials_ref that 503s the probe) would otherwise leave the
      // landing screenshot missing an engine while the test still passes.
      expect(r.status(), `pre-seed ${c.engine_type} cluster should 201`).toBe(201);
      const body = (await r.json()) as { id: string };
      appendForCleanup('cluster', body.id);
    }
    await apiCtx.dispose();

    // ── 01: Land on /clusters list ─────────────────────────────────────
    await page.goto('/clusters');
    await expect(page.getByTestId('open-register-cluster')).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(400);
    timer.mark(captions[0]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '01-clusters-list.png'),
      fullPage: false,
    });

    // ── 02: Open the register modal ────────────────────────────────────
    await glide(page, page.getByTestId('open-register-cluster'));
    await page.getByTestId('open-register-cluster').click();
    await expect(page.getByTestId('register-form')).toBeVisible();
    await page.waitForTimeout(400);
    timer.mark(captions[1]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '02-register-modal-empty.png'),
      fullPage: false,
    });

    // ── 03: Fill the form (acme-products-prod realistic values) ───────
    await glide(page, page.getByLabel('Name', { exact: true }), 400);
    await page.getByLabel('Name', { exact: true }).click();
    await page.getByLabel('Name', { exact: true }).pressSequentially(name, { delay: 55 });

    await glide(page, page.getByLabel('Base URL', { exact: true }), 400);
    await page.getByLabel('Base URL', { exact: true }).click();
    await page
      .getByLabel('Base URL', { exact: true })
      .pressSequentially('http://elasticsearch:9200', { delay: 55 });

    await glide(page, page.getByLabel(/^Credentials ref/), 400);
    await page.getByLabel(/^Credentials ref/).click();
    await page.getByLabel(/^Credentials ref/).pressSequentially('local-es', { delay: 55 });

    // The acme scenario uses Production environment.
    await glide(page, page.locator('#cl-env'));
    await page.locator('#cl-env').click();
    await glide(page, page.getByRole('option', { name: 'prod' }), 400);
    await page.getByRole('option', { name: 'prod' }).click();

    // local-es credentials are username+password; switch auth_kind to match.
    await glide(page, page.locator('#cl-auth'));
    await page.locator('#cl-auth').click();
    await glide(page, page.getByRole('option', { name: 'es_basic' }), 400);
    await page.getByRole('option', { name: 'es_basic' }).click();

    // Notes: describe the scenario in operator-relatable language.
    await glide(page, page.getByLabel('Notes', { exact: true }), 400);
    await page.getByLabel('Notes', { exact: true }).click();
    await page.getByLabel('Notes', { exact: true }).pressSequentially(notes, { delay: 55 });

    // Target filter: scope this cluster's index picker to the e-commerce
    // products family. The caption for this step teaches the new feature.
    await glide(page, page.getByLabel(/^Target filter/), 400);
    await page.getByLabel(/^Target filter/).click();
    await page.getByLabel(/^Target filter/).pressSequentially(targetFilter, { delay: 55 });

    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(400);
    timer.mark(captions[2]!, Date.now());
    await shot(page, {
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
    await glide(page, page.getByTestId('register-submit'));
    await page.getByTestId('register-submit').click();
    const resp = await registerPromise;
    expect(resp.status()).toBe(201);

    // ── 05: New cluster appears in the list with health probe result ──
    await expect(page.getByTestId('register-form')).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(600);
    timer.mark(captions[3]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '04-cluster-registered.png'),
      fullPage: false,
    });

    // ── 06: Click the row → detail page ────────────────────────────────
    await glide(page, page.getByText(name).first());
    await page.getByText(name).first().click();
    await page.waitForURL(/\/clusters\/[a-f0-9-]+$/, { timeout: 10_000 });
    await page.waitForTimeout(600);
    timer.mark(captions[4]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '05-cluster-detail.png'),
      fullPage: false,
    });

    if (captions.length > 0 && timer.timings.length !== captions.length) {
      throw new Error(
        `caption/step mismatch for ${SLUG}: ${timer.timings.length} marks vs ${captions.length} captions`,
      );
    }
    writeCaptionsVtt(timer.timings, SLUG, GUIDES_ROOT);
  });
});
