import { test, expect } from '@playwright/test';

test('L1: proof-carrying rescue console shows move permit and evidence trail per route', async ({ page }) => {
  await page.goto('/?fake=1');

  // Verify permit panel exists
  const panel = page.locator('#permit-panel');
  await expect(panel).toBeVisible();

  // Wait for fixture replay of permit__route.json
  const status = panel.locator('.permit-status');
  await expect(status).toBeVisible({ timeout: 10000 });

  // In fixture mode (permit__route.json), r3 is revoked on sensed LiDAR shift
  await expect(status).toHaveText('REVOKED');
  await expect(panel.locator('.permit-route-label')).toContainText('Route r3');
  await expect(panel.locator('.permit-reason')).toContainText('LiDAR hit inside the route');

  // Evidence list
  const evidenceItems = panel.locator('.evidence-item');
  await expect(evidenceItems).toHaveCount(3);

  // Check evidence kinds: verified, clear, shift
  await expect(evidenceItems.nth(0)).toHaveClass(/kind-verified/);
  await expect(evidenceItems.nth(0).locator('.evidence-detail')).toContainText('physics check passed');

  await expect(evidenceItems.nth(1)).toHaveClass(/kind-clear/);
  await expect(evidenceItems.nth(1).locator('.evidence-detail')).toContainText('no sensed hazard');

  await expect(evidenceItems.nth(2)).toHaveClass(/kind-shift/);
  await expect(evidenceItems.nth(2).locator('.evidence-detail')).toContainText('LiDAR hit inside the route');

  // Now dynamically re-earn permit via fresh observation
  await page.evaluate(() => {
    const bus = window as unknown as { dispatchBusMessage: (topic: string, data: unknown) => void };
    bus.dispatchBusMessage('permit/route', {
      route: 'r3',
      granted: true,
      t: 16.5,
      reason: 'granted: every route cell is seen free by a fresh ray',
      evidence: [
        { kind: 'verified', detail: 'physics check passed for 20 cells', t: 4.0 },
        { kind: 'clear', detail: 'no sensed hazard on the route', t: 4.0 },
        { kind: 'shift', detail: 'LiDAR hit inside the route at 2 cell(s)', t: 12.3 },
        { kind: 'fresh_scan', detail: 'fresh ray sweep verified 100% cells clear', t: 16.5 }
      ]
    });
  });

  // Verify status updates to GRANTED with fresh_scan
  await expect(status).toHaveText('GRANTED');
  await expect(panel.locator('.permit-reason')).toContainText('seen free by a fresh ray');
  await expect(evidenceItems).toHaveCount(4);
  await expect(evidenceItems.nth(3)).toHaveClass(/kind-fresh_scan/);
  await expect(evidenceItems.nth(3).locator('.evidence-detail')).toContainText('fresh ray sweep');
});
