import { expect, test } from '@playwright/test';

// Browser smoke test for the static review app in apps/claude-review-app, served by its own
// Python server on the committed synthetic sample session (see playwright.config.ts).
test.use({ baseURL: 'http://127.0.0.1:4176' });

test('the static review app renders the sample session in the browser', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/');

  await expect(page.locator('#day-select')).toHaveValue('2026-01-07');
  await expect(page.locator('#load-state')).toHaveText('');
  await expect(page.locator('#chart canvas').first()).toBeVisible();
  await expect(page.locator('#chart-empty')).toBeHidden();
  await expect(page.locator('#warning-banner')).toBeHidden();
  await expect(page.locator('#reload-button')).toBeEnabled();

  await page.locator('#scenario-select').selectOption('Opening range breakout@09:45:53');
  await page.locator('#drawer-tab').click();
  await expect(page.locator('#drawer-tab')).toHaveAttribute('aria-expanded', 'true');
  const drawer = page.locator('#drawer-panel');
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText('Trigger conditions');
  const cards = drawer.locator('article.agent-card');
  await expect(cards).toHaveCount(2);
  await expect(drawer.getByRole('article', { name: 'Opus response' })).toContainText('synthetic-opus');
  await expect(drawer.getByRole('article', { name: 'Astra response' })).toContainText('synthetic-astra');

  const vwap = page.locator('#toggle-vwap');
  const pressed = await vwap.getAttribute('aria-pressed');
  await vwap.click();
  await expect(vwap).not.toHaveAttribute('aria-pressed', pressed ?? '');
  await page.locator('#sub-select').selectOption({ index: 1 });
  await page.locator('#reload-button').click();
  await expect(page.locator('#load-state')).toHaveText('');
  await expect(page.locator('#chart canvas').first()).toBeVisible();

  expect(errors).toEqual([]);
});
