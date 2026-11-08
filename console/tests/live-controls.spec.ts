import { test, expect, type Page } from '@playwright/test';

// LIVE-UI-2: approve / hold go out as gate/answer over the hub WebSocket, and "Trigger Slab Shift"
// drops the sim's spare block ahead of the Responder via the hub's POST /inject (block_added).
const INJECT = 'http://localhost:8000/inject';
const ROUTE = { id: 'r5', robot: 'responder', goal: 'deliver water to c1', model: 'local-astar',
  cells: Array.from({ length: 30 }, (_, i) => [i, 0, 0]) };

async function liveHub(page: Page, injectStatus = 200) {
  const sent: any[] = [];
  const injected: unknown[] = [];
  let socket: any;
  await page.routeWebSocket('ws://localhost:8000/ws', ws => {
    socket = ws;
    ws.onMessage(raw => sent.push(JSON.parse(String(raw))));
  });
  await page.route(INJECT, async route => {
    injected.push(route.request().postDataJSON());
    await route.fulfill({
      status: injectStatus, contentType: 'application/json',
      headers: { 'access-control-allow-origin': 'http://127.0.0.1:5173' },
      body: JSON.stringify(injectStatus === 200 ? { ok: true, block: 'x1' } : { error: 'no live sim on this hub' })
    });
  });
  await page.goto('/');
  await expect(page.locator('#connection-status')).toHaveText('Hub connected');
  return { sent, injected, push: (topic: string, data: unknown) => socket.send(JSON.stringify({ topic, data })) };
}

test('slab shift drops the block 0.5 m ahead of the Responder on its route', async ({ page }) => {
  const hub = await liveHub(page);
  hub.push('route/proposed', ROUTE);
  hub.push('responder/pose', { t: 1, pos: [0.075, 0.025, 0], yaw: 0, state: 'moving', route: 'r5', carrying: [] });
  await page.locator('#btn-slab-shift').click();
  // nearest cell is i=1; ten 0.05 m steps later is i=11, centre x = 11.5 * 0.05
  await expect.poll(() => hub.injected).toEqual([{ kind: 'block_added', pos: [0.575, 0.025, 0.3] }]);
  await expect(page.locator('#live-control-status')).toHaveText('Slab shift: x1 dropping on r5');
});

test('slab shift needs a Responder route and says so', async ({ page }) => {
  const hub = await liveHub(page);
  await page.locator('#btn-slab-shift').click();
  await expect(page.locator('#live-control-status')).toHaveText('No Responder route yet');
  expect(hub.injected).toEqual([]);
});

test('slab shift without a live sim reports it', async ({ page }) => {
  const hub = await liveHub(page, 503);
  hub.push('route/proposed', ROUTE);
  await page.locator('#btn-slab-shift').click();
  await expect(page.locator('#live-control-status')).toHaveText('No live sim on the hub');
  expect(hub.injected).toHaveLength(1);
});

test('fake mode never calls the hub for a slab shift', async ({ page }) => {
  const injected: unknown[] = [];
  await page.route(INJECT, route => { injected.push(route.request().postDataJSON()); return route.abort(); });
  await page.goto('/?fake=1');
  await page.locator('#btn-slab-shift').dispatchEvent('click');
  await expect(page.locator('#live-control-status')).toHaveText('Fake mode: no live sim to shift');
  expect(injected).toEqual([]);
});

test('approve and hold reach the hub as gate/answer', async ({ page }) => {
  const hub = await liveHub(page);
  hub.push('gate/request', { id: 'g-a', kind: 'risky_move', route: 'r5', summary: 'Cross the doorway' });
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect.poll(() => hub.sent).toContainEqual({ topic: 'gate/answer', data: { id: 'g-a', approved: true, by: 'operator' } });
  hub.push('gate/request', { id: 'g-h', kind: 'enter_at_risk', route: 'r5', summary: 'Enter the at-risk room' });
  await page.getByRole('button', { name: 'Reject', exact: true }).click();
  await expect.poll(() => hub.sent).toContainEqual({ topic: 'gate/answer', data: { id: 'g-h', approved: false, by: 'operator' } });
});
