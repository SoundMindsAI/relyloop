// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /chat workflows (E4 resume past conversation, new-conversation
 * button, secrets warning banner).
 *
 * Message streaming (C2 study-via-chat, E1-E3 agent introspection) requires
 * a live LLM endpoint and is out of scope for this spec. The chat shell —
 * list page, navigation, page chrome on a freshly-seeded conversation — is
 * what we cover here.
 */
import { expect, test } from '@playwright/test';

import { seedConversation } from './helpers/seed';

test.describe('/chat shell', () => {
  test('lists past conversations after seeding one', async ({ page }) => {
    const conv = await seedConversation('e2e seed convo');

    await page.goto('/chat');
    await expect(page.getByTestId('conversation-list')).toBeVisible({ timeout: 5_000 });
    // The seeded conversation surfaces in the list with its title.
    await expect(page.getByText(conv.title ?? '').first()).toBeVisible({ timeout: 5_000 });
  });

  test('new-conversation button navigates to a fresh /chat/[id]', async ({ page }) => {
    await page.goto('/chat');
    await page.getByTestId('new-conversation').click();
    // Navigation lands on /chat/{uuid}.
    await page.waitForURL(/\/chat\/[a-f0-9-]+$/, { timeout: 10_000 });
    // Composer mounts on the detail page.
    await expect(page.getByTestId('composer-input')).toBeVisible({ timeout: 5_000 });
  });

  test('detail page renders the secrets warning banner and supports dismissal', async ({
    page,
  }) => {
    const conv = await seedConversation('e2e banner test');

    await page.goto(`/chat/${conv.id}`);
    await expect(page.getByTestId('secrets-warning')).toBeVisible({ timeout: 5_000 });
    await page.getByTestId('dismiss-secrets-warning').click();
    // Banner disappears immediately on dismiss.
    await expect(page.getByTestId('secrets-warning')).not.toBeVisible();
  });
});
