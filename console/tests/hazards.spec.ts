import { test, expect } from '@playwright/test';

type Viewer = { hazardOverlayCount(): number; updateHazards(h: unknown[]): void };

test('X1: predicted hazards show as floor tiles before any aftershock, and are replaced not merged', async ({ page }) => {
  test.setTimeout(60000);
  // ?fake=1 replays fixtures one file at a time, in manifest order, and map__hazards.json comes after the
  // gate fixture that shows g4. Wait for the last fixture so its map/hazards cannot land after ours.
  const replayed = page.waitForResponse(r => r.url().endsWith('/fixtures/panels.json'), { timeout: 15000 });
  await page.goto('/?fake=1');
  await expect(page.locator('#approval-meta')).toContainText('g4', { timeout: 10000 });
  await replayed;
  // The overlay is rebuilt on the next animation frame; software GL on a busy runner can go seconds
  // without one, so the polls allow longer than the 5 s default.
  const settled = { timeout: 20000 };
  const count = () => page.evaluate(() => (window as unknown as { aftershockMap: Viewer }).aftershockMap.hazardOverlayCount());
  await expect.poll(count, settled).toBeGreaterThan(0);      // demo scene: leaning slab b10 at_risk, no world/change yet
  await page.evaluate(() => {
    const m = (window as unknown as { aftershockMap: Viewer }).aftershockMap;
    m.updateHazards([
      { cell: [2, 3, 0], status: 'at_risk', why: 'unsupported wall b7', estimate: true },
      { cell: [2, 3, 1], status: 'collapsed', why: 'same column, other layer', estimate: true },
      { cell: [5, 5, 0], status: 'stable', why: '', estimate: true }
    ]);
  });
  await expect.poll(count, settled).toBe(1);                 // one tile per column, stable draws nothing
  await page.evaluate(() => (window as unknown as { aftershockMap: Viewer }).aftershockMap.updateHazards([]));
  await expect.poll(count, settled).toBe(0);                 // the full list replaced the old one
});
