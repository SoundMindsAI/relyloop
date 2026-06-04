// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Chat shell (guide 08).
 *
 * Captures the conversation-management surface around /chat — list page,
 * new-conversation button, the secrets warning banner. Does NOT exercise
 * actual message streaming, which requires a live LLM endpoint and is
 * outside the scope of a deterministic walkthrough.
 *
 * If you're looking to walk a user through agent-driven study creation
 * end-to-end (workflow C2 / E1-E3), that guide ships when MVP2 lands LLM
 * mocking infrastructure.
 *
 * Cursor + smoother pacing + WebVTT step captions via the shared demo-cursor
 * helper (feat_walkthrough_video_cursor_captions). Run video-only so the
 * committed screenshots don't churn:
 *   cd ui
 *   DEMO_VIDEO_ONLY=1 pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/08_chat_shell.spec.ts
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import metadata from '../../../public/guides/08_chat_shell/metadata.json';
import { glide, installCursor, loadStepCaptions, shot, StepTimer, finalizeCaptions } from '../helpers/demo-cursor';
import { seedConversation } from '../helpers/seed';

const SLUG = '08_chat_shell';
const GUIDES_ROOT = path.resolve(__dirname, '../../../public/guides');
const SCREENSHOTS = path.join(GUIDES_ROOT, SLUG);

test.describe('Walkthrough: Chat shell', () => {
  test('captures conversation list + new + secrets banner', async ({ page }) => {
    await installCursor(page);
    const captions = loadStepCaptions(metadata);
    const timer = new StepTimer();

    const seeded = await seedConversation('e2e walkthrough conversation');

    // 01: Conversation list with seeded rows.
    await page.goto('/chat');
    await expect(page.getByTestId('conversation-list')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    timer.mark(captions[0]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '01-chat-list.png'),
      fullPage: false,
    });

    // 02: Open the seeded conversation — shows the secrets warning banner.
    await page.goto(`/chat/${seeded.id}`);
    await expect(page.getByTestId('secrets-warning')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    timer.mark(captions[1]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '02-chat-detail-with-banner.png'),
      fullPage: false,
    });

    // 03: Dismiss the banner — UI session-storage state.
    await glide(page, page.getByTestId('dismiss-secrets-warning'));
    await page.getByTestId('dismiss-secrets-warning').click();
    await expect(page.getByTestId('secrets-warning')).not.toBeVisible();
    await page.waitForTimeout(400);
    timer.mark(captions[2]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '03-chat-banner-dismissed.png'),
      fullPage: false,
    });

    // 04: New conversation button → fresh /chat/{id}.
    await page.goto('/chat');
    await page.waitForTimeout(300);
    await glide(page, page.getByTestId('new-conversation'));
    await page.getByTestId('new-conversation').click();
    await page.waitForURL(/\/chat\/[a-f0-9-]+$/, { timeout: 10_000 });
    await expect(page.getByTestId('composer-input')).toBeVisible({ timeout: 5_000 });
    await page.waitForTimeout(500);
    timer.mark(captions[3]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '04-chat-new-conversation.png'),
      fullPage: false,
    });

    finalizeCaptions(timer, captions, SLUG, GUIDES_ROOT);
  });
});
