// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Chat with the agent (guide 10).
 *
 * Captures a real LLM-backed chat turn end-to-end against the hosted
 * OpenAI endpoint (no mocking — per user direction). Sends a clear
 * introspection prompt that reliably triggers the `list_clusters` tool
 * dispatch; captures the user-message bubble, the streaming
 * tool-call card, and the assistant's final response.
 *
 * Cost: ~$0.01-0.03 per run with gpt-4o (one user turn + one tool dispatch +
 * one assistant response, ~2-4K total tokens).
 *
 * Prerequisites:
 *   - make up stack running (UI :3000, API :8000)
 *   - secrets/openai_key populated; /healthz reports
 *     function_calling: ok and structured_output: ok
 *   - At least one cluster registered (seeded by this spec)
 *
 * Cursor + smoother pacing + WebVTT step captions via the shared demo-cursor
 * helper (feat_walkthrough_video_cursor_captions). Run video-only so the
 * committed screenshots don't churn:
 *   cd ui
 *   DEMO_VIDEO_ONLY=1 pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/10_chat_with_agent.spec.ts
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import metadata from '../../../public/guides/10_chat_with_agent/metadata.json';
import { glide, installCursor, loadStepCaptions, shot, StepTimer, writeCaptionsVtt } from '../helpers/demo-cursor';
import { seedCluster, seedConversation } from '../helpers/seed';

const SLUG = '10_chat_with_agent';
const GUIDES_ROOT = path.resolve(__dirname, '../../../public/guides');
const SCREENSHOTS = path.join(GUIDES_ROOT, SLUG);

test.describe('Walkthrough: Chat with the agent', () => {
  // LLM round-trip with a tool dispatch typically completes in 8-15s but can
  // stretch to 30s+ under heavy load; bump the spec timeout accordingly.
  test.setTimeout(180_000);

  test('captures a real LLM chat turn with tool dispatch', async ({ page }) => {
    await installCursor(page);
    const captions = loadStepCaptions(metadata);
    const timer = new StepTimer();

    // Seed a cluster so the agent's list_clusters tool returns something
    // meaningful. Without this the chat would say "no clusters registered"
    // which is technically correct but a less informative screenshot.
    await seedCluster();
    const conv = await seedConversation('Walkthrough — list my clusters');

    // 01: Land on the chat detail page (composer + secrets banner visible).
    await page.goto(`/chat/${conv.id}`);
    await expect(page.getByTestId('composer-input')).toBeVisible({ timeout: 10_000 });
    // Dismiss the secrets warning so it doesn't compete for visual attention.
    const banner = page.getByTestId('secrets-warning');
    if (await banner.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await page.getByTestId('dismiss-secrets-warning').click();
    }
    await page.waitForTimeout(500);
    timer.mark(captions[0]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '01-chat-empty-composer.png'),
      fullPage: false,
    });

    // 02: Type a prompt that reliably triggers the list_clusters tool.
    const prompt = 'What clusters do we have set up? Please use the list_clusters tool.';
    const composer = page.getByTestId('composer-input');
    await glide(page, composer);
    await composer.click();
    await composer.pressSequentially(prompt, { delay: 55 });
    await page.waitForTimeout(500);
    timer.mark(captions[1]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '02-message-typed.png'),
      fullPage: false,
    });

    // 03: Send + wait for the user message bubble to render.
    await glide(page, page.getByTestId('composer-send'));
    await page.getByTestId('composer-send').click();
    await expect(page.getByTestId('message-bubble-user').first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId('message-bubble-user').first()).toContainText(/list_clusters/i);
    await page.waitForTimeout(800);
    timer.mark(captions[2]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '03-user-message-sent.png'),
      fullPage: false,
    });

    // 04: Wait for the tool-call card to appear. The agent should fire
    // list_clusters in response to the prompt.
    await expect(page.getByTestId('tool-call-card').first()).toBeVisible({ timeout: 60_000 });
    await page.waitForTimeout(1_000);
    timer.mark(captions[3]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '04-tool-call-card.png'),
      fullPage: true,
    });

    // 05: Wait for the assistant's final text response.
    // The composer-input is disabled while `streaming === true` and re-enables
    // once the SSE 'done' event fires. (composer-send is also disabled when
    // input is empty, so it's not a reliable streaming-done signal.)
    await expect(page.getByTestId('composer-input')).toBeEnabled({ timeout: 120_000 });
    await page.waitForTimeout(1_500);
    timer.mark(captions[4]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '05-assistant-response.png'),
      fullPage: true,
    });

    if (captions.length === 0) {
      // Zero-caption deck: delete any stale captions.vtt, emit no <track>.
      writeCaptionsVtt([], SLUG, GUIDES_ROOT);
    } else {
      if (timer.timings.length !== captions.length) {
        throw new Error(
          `caption/step mismatch for ${SLUG}: ${timer.timings.length} marks vs ${captions.length} captions`,
        );
      }
      writeCaptionsVtt(timer.timings, SLUG, GUIDES_ROOT);
    }
  });
});
