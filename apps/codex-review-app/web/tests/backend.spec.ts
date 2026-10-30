import { expect, test } from '@playwright/test';

// No route mocks: the browser reads the parser output of the real backend for the
// committed synthetic session in apps/sample-session/logs.
test.use({ baseURL: 'http://127.0.0.1:4175' });

test('the backend serves the committed sample session to the browser', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByLabel('Trading day')).toHaveValue('2026-01-07');
  await expect(page.getByTestId('price-chart').locator('canvas').first()).toBeVisible();
  await expect(page.locator('.session-summary')).toContainText('3 setups');
  await expect(page.locator('.session-summary')).toContainText('/ claude instance');
  await page.getByRole('button', { name: 'Choose scenario' }).click();
  await expect(page.locator('.picker-options').getByRole('button', { name: /Opening range breakout/ })).toHaveCount(1);
  await page.locator('.picker-options').getByRole('button', { name: /Opening range breakout/ }).click();
  await expect(page.getByRole('complementary', { name: 'Agent reasoning' })).toContainText('synthetic-opus');
  expect(errors).toEqual([]);
});
