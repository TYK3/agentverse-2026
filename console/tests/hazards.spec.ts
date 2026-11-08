import { test, expect } from '@playwright/test';

type Viewer = { hazardOverlayCount(): number; updateHazards(h: unknown[]): void };

test('X1: predicted hazards show as floor tiles before any aftershock, and are replaced not merged', async ({ page }) => {
  await page.goto('/?fake=1');
  await expect(page.locator('#approval-meta')).toContainText('g4');
  const count = () => page.evaluate(() => (window as unknown as { aftershockMap: Viewer }).aftershockMap.hazardOverlayCount());
  await expect.poll(count).toBeGreaterThan(0);              // demo scene: leaning slab b10 at_risk, no world/change yet
  await page.evaluate(() => {
    const m = (window as unknown as { aftershockMap: Viewer }).aftershockMap;
    m.updateHazards([
      { cell: [2, 3, 0], status: 'at_risk', why: 'unsupported wall b7', estimate: true },
      { cell: [2, 3, 1], status: 'collapsed', why: 'same column, other layer', estimate: true },
      { cell: [5, 5, 0], status: 'stable', why: '', estimate: true }
    ]);
  });
  await expect.poll(count).toBe(1);                         // one tile per column, stable draws nothing
  await page.evaluate(() => (window as unknown as { aftershockMap: Viewer }).aftershockMap.updateHazards([]));
  await expect.poll(count).toBe(0);                         // the full list replaced the old one
});
