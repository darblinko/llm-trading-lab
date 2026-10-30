import { expect, test } from '@playwright/test';
import { catalog, days, sessions } from './fixtures';

test('an installation with only codex logs opens the codex instance', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/sessions**', async route => {
    const url = new URL(route.request().url());
    const instance = url.searchParams.get('instance');
    const codexOnly = { ...catalog, instances: ['codex'], instance };
    if (url.pathname === '/api/sessions') {
      await route.fulfill({ json: instance === 'codex' ? codexOnly : { ...codexOnly, sessions: [] } });
      return;
    }
    const body = instance === 'codex' ? sessions.find(s => url.pathname.endsWith(`/${s.date}`)) : undefined;
    await route.fulfill({ status: body ? 200 : 404, json: body || { detail: 'Missing fixture' } });
  });
  await page.goto('/');
  await expect(page.getByLabel('Trading day')).toHaveValue(days[0]);
  await expect(page.locator('.session-summary')).toContainText('/ codex instance');
  await expect(page.getByLabel('Trading instance')).toHaveCount(0);
  expect(errors).toEqual([]);
});
