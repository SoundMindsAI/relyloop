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
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import { seedConversation } from '../helpers/seed';

const SCREENSHOTS = path.resolve(__dirname, '../../../public/guides/08_chat_shell');

test.describe('Walkthrough: Chat shell', () => {
  test('captures conversation list + new + secrets banner', async ({ page }) => {
    const seeded = await seedConversation('e2e walkthrough conversation');

    // 01: Conversation list with seeded rows.
    await page.goto('/chat');
    await expect(page.getByTestId('conversation-list')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '01-chat-list.png'),
      fullPage: false,
    });

    // 02: Open the seeded conversation — shows the secrets warning banner.
    await page.goto(`/chat/${seeded.id}`);
    await expect(page.getByTestId('secrets-warning')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '02-chat-detail-with-banner.png'),
      fullPage: false,
    });

    // 03: Dismiss the banner — UI session-storage state.
    await page.getByTestId('dismiss-secrets-warning').click();
    await expect(page.getByTestId('secrets-warning')).not.toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '03-chat-banner-dismissed.png'),
      fullPage: false,
    });

    // 04: New conversation button → fresh /chat/{id}.
    await page.goto('/chat');
    await page.waitForTimeout(300);
    await page.getByTestId('new-conversation').click();
    await page.waitForURL(/\/chat\/[a-f0-9-]+$/, { timeout: 10_000 });
    await expect(page.getByTestId('composer-input')).toBeVisible({ timeout: 5_000 });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '04-chat-new-conversation.png'),
      fullPage: false,
    });
  });
});
