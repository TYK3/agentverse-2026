import { test, expect, type Page } from '@playwright/test';

// BLENDER-LOOK: Blender robot and tower models, lighting, dust, robots following live poses.

type Look = { robotsLoaded: boolean; towerLoaded: boolean; towerVisible: boolean; error?: string; dust: number; responderPoses: number; enabled: boolean };
type Bus = { dispatchBusMessage(topic: string, data: unknown): void };

/** Robots loaded and the fixture replay done (it sends its own sensors/scout and responder/pose). */
async function ready(page: Page): Promise<void> {
  await expect(page.locator('#approval-meta')).toContainText('g4', { timeout: 15000 });
  await expect.poll(async () => (await look(page)).robotsLoaded, { timeout: 15000 }).toBe(true);
  // the replay's own responder/pose and sensors/scout (pos [0, 0, 0.1]) have arrived
  await expect.poll(() => page.evaluate(() => {
    const w = window as unknown as { aftershockLook: Look; aftershockMap: { scoutGroup: { position: { z: number } } } };
    return w.aftershockLook.responderPoses >= 1 && Math.abs(w.aftershockMap.scoutGroup.position.z - 0.1) < 1e-6;
  }), { timeout: 15000 }).toBe(true);
}

const look = (page: Page) => page.evaluate(() => (window as unknown as { aftershockLook: Look }).aftershockLook);

/** World-space size (x, y, z) and position of a named scene object, read from the map's Three.js scene. */
const probe = (page: Page, name: string) => page.evaluate(n => {
  const m = (window as unknown as { aftershockMap: { scene: { getObjectByName(n: string): any } } }).aftershockMap;
  const o = m.scene.getObjectByName(n);
  if (!o) return null;
  o.updateMatrixWorld(true);
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  o.traverse((c: any) => {
    if (!c.isMesh || !c.visible || c.name === 'headlight-beam') return;   // beams are light, not body
    c.geometry.computeBoundingBox();
    const b = c.geometry.boundingBox.clone().applyMatrix4(c.matrixWorld);
    for (let i = 0; i < 3; i++) { min[i] = Math.min(min[i], b.min.getComponent(i)); max[i] = Math.max(max[i], b.max.getComponent(i)); }
  });
  return { size: max.map((v, i) => v - min[i]), min, pos: [o.position.x, o.position.y, o.position.z], yaw: o.rotation.z };
}, name);

test('robot models load at their true envelopes, Z up, standing on the floor', async ({ page }) => {
  await page.goto('/?fake=1');
  await ready(page);
  const s = await look(page);
  expect(s.error).toBeUndefined();
  expect(s.dust).toBeGreaterThan(0);
  // let the Scout settle on the fixture pose, then measure it unrotated
  await page.evaluate(() => (window as unknown as Bus).dispatchBusMessage('sensors/scout', { t: 1, pose: { pos: [0.5, 0.5, 0.0], yaw: 0 } }));
  await expect.poll(async () => (await probe(page, 'look-scout'))?.pos[0] ?? 0, { timeout: 15000 }).toBeCloseTo(0.5, 2);
  const scout = (await probe(page, 'look-scout'))!;
  expect(scout.size[0]).toBeCloseTo(0.33, 2);
  expect(scout.size[1]).toBeCloseTo(0.23, 2);
  expect(scout.size[2]).toBeCloseTo(0.29, 2);
  expect(scout.min[2]).toBeCloseTo(0, 2);
  await page.evaluate(() => (window as unknown as Bus).dispatchBusMessage('responder/pose', { t: 1, pos: [-0.5, 0.2, 0.05], yaw: 0, state: 'idle', route: null, carrying: [] }));
  await expect.poll(async () => (await probe(page, 'look-responder'))?.pos[0] ?? 0, { timeout: 15000 }).toBeCloseTo(-0.5, 2);
  const resp = (await probe(page, 'look-responder'))!;
  expect(resp.size[0]).toBeCloseTo(0.52, 2);
  expect(resp.size[1]).toBeCloseTo(0.44, 2);
  expect(resp.size[2]).toBeCloseTo(0.75, 2);
  expect(resp.min[2]).toBeCloseTo(0, 2);                     // origin 0.05 m (chassis centre) -> wheels on z = 0
});

test('the Scout follows live poses and eases between samples; a long jump is drawn as a jump', async ({ page }) => {
  await page.goto('/?fake=1');
  await ready(page);
  const send = (x: number, y: number, yaw: number) => page.evaluate(([px, py, pyaw]) =>
    (window as unknown as Bus).dispatchBusMessage('sensors/scout', { t: 2, pose: { pos: [px, py, 0.075], yaw: pyaw } }), [x, y, yaw]);
  await send(0, 0, 0);
  await expect.poll(async () => (await probe(page, 'look-scout'))!.pos[0], { timeout: 15000 }).toBeCloseTo(0, 2);
  await expect.poll(async () => (await probe(page, 'look-scout'))!.pos[2], { timeout: 15000 }).toBeCloseTo(0, 3);  // 0.075 m origin -> floor
  await send(0.3, 0, Math.PI / 2);
  await expect.poll(async () => (await probe(page, 'look-scout'))!.pos[0], { timeout: 15000 }).toBeCloseTo(0.3, 2);
  await expect.poll(async () => (await probe(page, 'look-scout'))!.yaw, { timeout: 15000 }).toBeCloseTo(Math.PI / 2, 2);
  await send(1.8, 1.0, Math.PI / 2);                                        // 1.7 m away: snaps, no fake drive
  const first = await page.waitForFunction(() => {
    const m = (window as unknown as { aftershockMap: { scene: { getObjectByName(n: string): any } } }).aftershockMap;
    const p = m.scene.getObjectByName('look-scout').position;
    return Math.abs(p.x - 0.3) > 0.005 ? [p.x, p.y] : null;              // the first frame that moved it at all
  }, null, { polling: 'raf', timeout: 15000 });
  const p = (await first.jsonValue()) as number[];
  expect(p[0]).toBeCloseTo(1.8, 2);
  expect(p[1]).toBeCloseTo(1.0, 2);
});

test('the Responder follows responder/pose, not the route end', async ({ page }) => {
  await page.goto('/?fake=1');
  await ready(page);
  const before = (await look(page)).responderPoses;
  for (const [i, x] of [0.0, 0.1, 0.2, 0.3].entries()) {
    await page.evaluate(([t, px]) => (window as unknown as Bus).dispatchBusMessage('responder/pose',
      { t, pos: [px, -0.5, 0.05], yaw: 0, state: 'moving', route: 'r3', carrying: ['water'] }), [i * 0.1, x]);
    await page.waitForTimeout(100);
  }
  await expect.poll(async () => (await probe(page, 'look-responder'))!.pos[0], { timeout: 15000 }).toBeCloseTo(0.3, 2);
  expect((await look(page)).responderPoses - before).toBe(4);
  await page.evaluate(() => (window as unknown as Bus).dispatchBusMessage('responder/action', { action: 'move', route: 'r3' }));
  await page.waitForTimeout(300);
  expect((await probe(page, 'look-responder'))!.pos[0]).toBeCloseTo(0.3, 2);  // the real pose wins over the route end
});

test('the tower loads with ?look=tower: sim boxes, B1..B3 basements, cut-away south walls', async ({ page }) => {
  await page.goto('/?fake=1&look=tower');
  await expect.poll(async () => (await look(page)).towerLoaded, { timeout: 20000 }).toBe(true);
  expect((await look(page)).towerVisible).toBe(true);
  const names = await page.evaluate(() => {
    const m = (window as unknown as { aftershockMap: { scene: { getObjectByName(n: string): any } } }).aftershockMap;
    const out: Record<string, boolean> = {};
    for (const n of ['level_g_static', 'level_l1_static', 'level_b1_static', 'level_b2_static', 'level_b3_static',
      'level_b1_wall_s', 'b27', 'b1_test_slab']) {
      const o = m.scene.getObjectByName(n);
      out[n] = !!o && o.visible;
    }
    return out;
  });
  expect(names).toEqual({ level_g_static: true, level_l1_static: true, level_b1_static: true, level_b2_static: true,
    level_b3_static: true, level_b1_wall_s: false, b27: true, b1_test_slab: true });
  const b1 = (await probe(page, 'level_b1_static'))!;
  expect(b1.min[2]).toBeCloseTo(-1.1, 2);                    // B1 slab top -1.00, 0.10 m thick
  const ground = (await probe(page, 'level_g_static'))!;
  expect(ground.min[0]).toBeCloseTo(-2.05, 2);               // 4 m core + the sim's 0.05 m wall half thickness
});

test('a model that fails to load leaves the console primitives in place', async ({ page }) => {
  await page.route('**/models/blender_*.glb', r => r.fulfill({ status: 404, body: 'missing' }));
  await page.goto('/?fake=1');
  await expect.poll(async () => (await look(page)).error ?? '', { timeout: 15000 }).toContain('robot models');
  expect((await look(page)).robotsLoaded).toBe(false);
  const visible = await page.evaluate(() => {
    const m = (window as unknown as { aftershockMap: { scoutGroup: { children: { visible: boolean }[] } } }).aftershockMap;
    return m.scoutGroup.children.filter(c => c.visible).length;
  });
  expect(visible).toBeGreaterThan(1);
});

test('?look=0 turns the look off', async ({ page }) => {
  await page.goto('/?fake=1&look=0');
  await page.waitForTimeout(1500);
  const s = await look(page);
  expect(s.enabled).toBe(false);
  expect(s.robotsLoaded).toBe(false);
});
