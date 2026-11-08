import { test, expect } from '@playwright/test';

// MAP-DELTA-FIX: perception sends a full map/cells snapshot, then small deltas. The 3D map must keep the
// snapshot's cells when a delta arrives (it used to replace them, so the map flickered down to a few cells),
// drop a cell that a delta marks unknown, and start again on scene/loaded or a new grid resolution.
const cell = (i: number, j: number, occupied = false, state = 'seen') => ({ cell: [i, j, 0], state, occupied });

test('map/cells deltas merge into the snapshot instead of replacing it', async ({ page }) => {
  let socket: any;
  await page.routeWebSocket('ws://localhost:8000/ws', ws => { socket = ws; });
  await page.goto('/');
  await page.waitForFunction(() => 'aftershockMap' in window);
  await expect(page.locator('#connection-status')).toHaveText('Hub connected');
  const send = (topic: string, data: unknown) => socket.send(JSON.stringify({ topic, data }));
  const held = () => page.evaluate(() => (window as any).aftershockMap.currentCells.map((c: any) => c.cell.join(',')).sort());

  send('map/cells', { t: 5, res: 0.05, cells: [cell(0, 0), cell(1, 0, true), cell(2, 0), cell(3, 0)] });
  await expect.poll(held).toEqual(['0,0,0', '1,0,0', '2,0,0', '3,0,0']);

  // A delta with one new cell and one changed cell: the other snapshot cells stay.
  send('map/cells', { t: 5.5, res: 0.05, cells: [cell(4, 0, true), cell(0, 0, true)] });
  await expect.poll(held).toEqual(['0,0,0', '1,0,0', '2,0,0', '3,0,0', '4,0,0']);
  const first = await page.evaluate(() => (window as any).aftershockMap.currentCells.find((c: any) => c.cell.join(',') === '0,0,0'));
  expect(first.occupied).toBe(true);

  // An explicit unknown forgets that cell only.
  send('map/cells', { t: 6, res: 0.05, cells: [cell(2, 0, false, 'unknown')] });
  await expect.poll(held).toEqual(['0,0,0', '1,0,0', '3,0,0', '4,0,0']);

  // A new scene starts the map again.
  send('scene/loaded', { scene: 'backup', blocks: [] });
  send('map/cells', { t: 0.5, res: 0.05, cells: [cell(7, 7)] });
  await expect.poll(held).toEqual(['7,7,0']);

  // So does a change of grid resolution.
  send('map/cells', { t: 1, res: 0.1, cells: [cell(9, 9)] });
  await expect.poll(held).toEqual(['9,9,0']);
});
