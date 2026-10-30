import { expect, test, type Page } from '@playwright/test';
import { catalog, days, sessions } from './fixtures';

const browserErrors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  browserErrors.set(page, errors);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/sessions**', async route => {
    const path = new URL(route.request().url()).pathname;
    const body = path === '/api/sessions' ? catalog : sessions.find(s => path.endsWith(`/${s.date}`));
    await route.fulfill({ status: body ? 200 : 404, json: body || { detail: 'Missing fixture' } });
  });
  await page.goto('/');
  await expect(page.getByLabel('Trading day')).toHaveValue(days[0]);
  await expect(page.getByTestId('price-chart').locator('canvas').first()).toBeVisible();
  test.info().annotations.push({ type: 'data', description: 'Deterministic API fixtures; backend parsers are checked by pytest.' });
});

test.afterEach(async ({ page }) => {
  expect(browserErrors.get(page)).toEqual([]);
});

test('six sessions and scenario revisions remain selectable across days', async ({ page }) => {
  const day = page.getByLabel('Trading day');
  await expect(day.locator('option')).toHaveCount(6);
  for (const date of days) {
    await day.selectOption(date);
    await expect(page.getByLabel('Session chart')).toBeVisible();
    await expect(page.locator('.session-summary')).toContainText('2 setups');
  }
  await page.getByRole('button', { name: 'Choose scenario' }).click();
  await page.getByRole('textbox', { name: 'Search scenarios' }).fill(days[1]);
  const revisions = page.locator('.picker-options').getByRole('button', { name: /Support reclaim/ });
  await expect(revisions).toHaveCount(2);
  await revisions.nth(1).click();
  await expect(day).toHaveValue(days[1]);
  await page.getByRole('button', { name: 'Setup details', exact: true }).click();
  await expect(page.locator('.setup-details .source')).toContainText(`scenarios_${days[1]}.jsonl:2`);
  await expect(page.getByRole('complementary', { name: 'Agent reasoning' })).toContainText('No agent evaluation was recorded');
});

test('indicator panes can be changed, hidden, and resized', async ({ page }) => {
  const chart = page.getByTestId('price-chart');
  const initialCanvasCount = await chart.locator('canvas').count();
  for (const value of ['rsi', 'stochrsi', 'macd_hist', 'rvol', 'cvd_21']) {
    await page.getByLabel('Technical indicator').selectOption(value);
    await expect(page.getByRole('button', { name: 'Hide indicator' })).toBeVisible();
    await expect.poll(() => chart.locator('canvas').count()).toBeGreaterThan(initialCanvasCount);
  }
  await page.getByRole('button', { name: 'Hide indicator' }).click();
  await expect(page.getByLabel('Technical indicator')).toHaveValue('none');
  await expect(chart.locator('canvas')).toHaveCount(initialCanvasCount);
  const initialWidth = (await chart.boundingBox())!.width;
  await page.getByRole('button', { name: 'Toggle agent reasoning' }).click();
  await expect(page.getByRole('complementary', { name: 'Agent reasoning' })).toHaveCount(0);
  await expect.poll(async () => (await chart.boundingBox())!.width).toBeGreaterThan(initialWidth);
  await page.setViewportSize({ width: 1000, height: 800 });
  await expect.poll(async () => (await chart.boundingBox())!.width).toBeLessThan(1000);
  await expect.poll(() => chart.evaluate(element => element.querySelector('canvas')!.clientWidth)).toBeGreaterThan(0);
});

test('scenario zones meet at the recorded revision time between candles', async ({ page }) => {
  const chart = page.getByTestId('price-chart');
  await chart.evaluate(element => {
    const strokeRect = CanvasRenderingContext2D.prototype.strokeRect;
    CanvasRenderingContext2D.prototype.strokeRect = function(x, y, width, height) {
      if (this.strokeStyle === '#45c9a0') {
        element.setAttribute('data-zone-bounds', JSON.stringify([x, x + width]));
      }
      strokeRect.call(this, x, y, width, height);
    };
  });
  await page.locator('.setup-link').first().click();
  await expect(chart).toHaveAttribute('data-zone-bounds');
  const first = JSON.parse((await chart.getAttribute('data-zone-bounds'))!) as number[];
  expect(first[1]).toBeGreaterThan(first[0]);
  await chart.evaluate(element => element.removeAttribute('data-zone-bounds'));
  await page.locator('.setup-link').nth(1).click();
  await expect(chart).toHaveAttribute('data-zone-bounds');
  const second = JSON.parse((await chart.getAttribute('data-zone-bounds'))!) as number[];
  expect(second[0]).toBeCloseTo(first[1], 3);
  // The revision occurs at 10:05, 35 minutes into a 390-minute session.
  expect((second[0] - first[0]) / (second[1] - first[0])).toBeCloseTo(35 / 390, 3);
});

test('expanded reasoning retains selection and the existing chart', async ({ page }) => {
  await page.locator('.setup-link').first().click();
  const evaluation = page.getByLabel('Evaluation');
  await evaluation.selectOption(`${days[0]}-decision-2`);
  const chart = await page.getByTestId('price-chart').locator('canvas').first().elementHandle();
  await page.getByRole('button', { name: 'Expand reasoning' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'Claude Opus' })).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'OpenAI Astra' })).toBeVisible();
  await expect(dialog).toContainText("This agent's response was not recorded");
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(evaluation).toHaveValue(`${days[0]}-decision-2`);
  expect(await chart!.evaluate(element => element.isConnected)).toBe(true);
  await evaluation.selectOption(`${days[0]}-decision-1`);
  await expect(page.locator('.opus .badge')).toHaveText('Enter');
  await expect(page.locator('.astra .badge')).toHaveText('Wait');
  await expect(page.locator('.consensus .badge')).toHaveText('Wait');
});

test('fill selection shows the recorded source and linked evaluation', async ({ page }) => {
  await page.getByRole('button', { name: /Executions/ }).click();
  await page.getByRole('button', { name: /Entry/ }).click();
  await expect(page.getByLabel('Evaluation')).toHaveValue(`${days[0]}-decision-2`);
  await expect(page.locator('.fill-detail')).toContainText('BUY 2 @ $1.20');
  await expect(page.locator('.fill-detail')).toContainText('Recorded fill-detection time');
  await expect(page.locator('.fill-detail .source')).toHaveText(`claude/orders/orders_${days[0]}.jsonl:3`);
  await page.getByLabel('Trading day').selectOption(days[1]);
  await expect(page.getByLabel('Session activity')).toContainText('No confirmed fills in this session');
  await expect(page.locator('.legend-observation')).toHaveText('Recorded prices · OHLC unavailable');
});

test('failed refresh keeps the session usable and retry recovers', async ({ page }) => {
  await page.route('**/api/sessions?*', route => route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } }));
  await page.getByRole('button', { name: 'Refresh data' }).click();
  await expect(page.getByRole('alert')).toContainText('Unable to load session data (503)');
  await expect(page.getByLabel('Trading day')).toHaveValue(days[0]);
  await expect(page.getByLabel('Session chart')).toBeVisible();
  await page.unroute('**/api/sessions?*');
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('the Lightweight Charts attribution notice and link are visible', async ({ page }) => {
  const footer = page.locator('.app-footer .attribution');
  await expect(footer).toContainText('TradingView Lightweight Charts™, Copyright (c) 2025 TradingView, Inc.');
  await expect(footer.getByRole('link', { name: 'tradingview.com' })).toHaveAttribute('href', 'https://www.tradingview.com/');
});
