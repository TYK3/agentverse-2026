import { test, expect } from '@playwright/test';

// MARKER-FIX: the Scout is labelled "Scout", demo route r3 ends at casualty c1, and the Responder
// stops beside a casualty at the end of its route instead of on top of them.
test.beforeEach(async ({ page }) => {
  await page.routeWebSocket('ws://localhost:8000/ws', () => {});  // no hub: keep the page quiet
  await page.goto('/');
  await page.waitForFunction(() => 'aftershockMap' in window);
});

test('scout label reads Scout, not Scout Rover', async ({ page }) => {
  const labels = await page.evaluate(() => {
    const map = (window as any).aftershockMap;
    return map.scoutGroup.children.map((c: any) => c.userData?.label).filter(Boolean);
  });
  expect(labels).toEqual(['Scout (pose)']);
});

test('demo route r3 ends at c1 and the Responder stops beside c1, not on them', async ({ page }) => {
  const got = await page.evaluate(() => {
    const map = (window as any).aftershockMap;
    map.loadBackupSceneDemo();
    const res = map.cellResolution;
    const end = map.routesMap.get('r3').cells.at(-1);
    const c1 = map.casualtiesMap.get('c1').pos;
    map.updateResponderAction({ action: 'move', route: 'r3' });
    const p = map.responderGroup.position;
    return { endXY: [(end[0] + 0.5) * res, (end[1] + 0.5) * res], c1, res, responder: [p.x, p.y] };
  });
  const d = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  expect(d(got.endXY, got.c1)).toBeLessThanOrEqual(got.res * Math.SQRT2);  // r3 ends at c1's cell (grid rounding)
  expect(d(got.responder, got.c1)).toBeGreaterThan(0.33);              // not on top of c1
  expect(d(got.responder, got.c1)).toBeLessThan(0.4);                  // but right beside them
  expect(d(got.responder, got.endXY)).toBeLessThan(0.5);               // on the approach, not back at the start
});

test('a route that ends away from any casualty still ends at its last cell', async ({ page }) => {
  const p = await page.evaluate(() => {
    const map = (window as any).aftershockMap;
    map.updateCasualties([{ id: 'c9', pos: [3, 3, 0], confidence: 0.9, clues: [] }]);
    map.updateRouteProposed({ id: 'r9', robot: 'responder', cells: [[0, 0, 0], [10, 0, 0]], goal: 'g', model: 'local-astar' });
    map.updateResponderAction({ action: 'move', route: 'r9' });
    return [map.responderGroup.position.x, map.responderGroup.position.y];
  });
  expect(p[0]).toBeCloseTo(0.525, 5);
  expect(p[1]).toBeCloseTo(0.025, 5);
});
