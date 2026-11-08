import { test, expect, type Page } from '@playwright/test';

// LIVE-UI: "Simulate Re-Plan" asks the hub's live sim for a real aftershock (POST /inject) and only
// plays the local b7 demo when there is no sim (or in ?fake=1).
const INJECT = 'http://localhost:8000/inject';

async function stubHub(page: Page, status: number, bodies: unknown[]): Promise<void> {
  await page.route(INJECT, async route => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({
      status,
      contentType: 'application/json',
      headers: { 'access-control-allow-origin': 'http://127.0.0.1:5173' },
      body: JSON.stringify(status === 200 ? { ok: true } : { error: 'no live sim on this hub' })
    });
  });
}

test('live hub: the button injects an aftershock and does not fake one locally', async ({ page }) => {
  const bodies: unknown[] = [];
  await stubHub(page, 200, bodies);
  await page.goto('/');
  await page.locator('#btn-demo-replan').click();
  await expect.poll(() => bodies).toEqual([{ kind: 'aftershock' }]);
  await page.waitForTimeout(2000);  // the local demo would have shown its banner at once
  await expect(page.locator('#world-change-banner')).not.toHaveClass(/visible/);
});

test('no live sim (503): the button falls back to the local re-plan demo', async ({ page }) => {
  const bodies: unknown[] = [];
  await stubHub(page, 503, bodies);
  await page.goto('/');
  await page.locator('#btn-demo-replan').click();
  await expect.poll(() => bodies).toEqual([{ kind: 'aftershock' }]);
  await expect(page.locator('#world-change-banner')).toHaveClass(/visible/, { timeout: 5000 });
  await expect(page.locator('#world-change-banner')).toContainText('b7 moved');
});

test('fake mode never calls the hub', async ({ page }) => {
  const bodies: unknown[] = [];
  await stubHub(page, 200, bodies);
  await page.goto('/?fake=1');
  // the fixture replay opens the approval dialog over the map, so dispatch the click directly
  await page.locator('#btn-demo-replan').dispatchEvent('click');
  await expect(page.locator('#world-change-banner')).toHaveClass(/visible/, { timeout: 5000 });
  await expect(page.locator('#world-change-banner')).toContainText('b7 moved');
  expect(bodies).toEqual([]);
});
