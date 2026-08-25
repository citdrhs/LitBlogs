import { expect, test } from '../support/fixtures.js';

test.describe.configure({ mode: 'serial' });

test('serves the built sign-in shell in real Chromium', async ({ page }) => {
  await page.goto('/sign-in');

  await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible();
});
