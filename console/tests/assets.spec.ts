import { test, expect } from '@playwright/test';

type Assets = {
  loaded: boolean; error?: string; buildingVisible: boolean; blocks: string[];
  credits: { licence: string }[]; movedBlocks: string[];
  showBuilding(show: boolean): void; markMoved(ids: string[]): void;
};
const assets = (page: import('@playwright/test').Page) =>
  page.evaluate(() => {
    const a = (window as unknown as { aftershockAssets: Assets }).aftershockAssets;
    return { loaded: a.loaded, error: a.error, visible: a.buildingVisible, blocks: a.blocks, credits: a.credits, moved: a.movedBlocks };
  });

test('A1: the demo model loads with every tower block named by its scene id, plus credits', async ({ page }) => {
  await page.goto('/?fake=1&building=1');
  await expect.poll(async () => (await assets(page)).loaded, { timeout: 20000 }).toBe(true);
  const a = await assets(page);
  expect(a.error).toBeUndefined();
  expect(a.blocks).toHaveLength(27);
  expect(a.blocks).toContain('b17');
  expect(a.visible).toBe(true);
  expect(a.credits.map(c => c.licence).sort()).toEqual(['BSD-3-Clause', 'CC0', 'CC0', 'CC0', 'CC0']);
  await page.locator('#asset-credits').evaluate(el => { (el as HTMLDetailsElement).open = true; });  // under the fake gate modal
  await expect(page.locator('#asset-credits li')).toHaveCount(5);
  await expect(page.locator('#asset-credits')).toContainText('Quaternius');
});

test('A1: the tower model shows only for the tower scene, and moved blocks turn to ghosts', async ({ page }) => {
  await page.goto('/?fake=1');                                  // fixtures replay the backup scene
  await expect.poll(async () => (await assets(page)).loaded, { timeout: 20000 }).toBe(true);
  expect((await assets(page)).visible).toBe(false);
  expect((await assets(page)).moved).toEqual([]);              // backup-scene world/change never marks tower blocks
  await page.evaluate(() => (window as unknown as { aftershockAssets: Assets }).aftershockAssets.showBuilding(true));
  expect((await assets(page)).visible).toBe(true);
  await page.evaluate(() => (window as unknown as { aftershockAssets: Assets }).aftershockAssets.markMoved(['b26', 'b99']));
  const moved = (await assets(page)).moved;
  expect(moved).toContain('b26');
  expect(moved).not.toContain('b99');                           // unknown ids are ignored
});

test('A1: robot models replace the primitives at the same footprint', async ({ page }) => {
  await page.goto('/?fake=1');
  await expect.poll(async () => (await assets(page)).loaded, { timeout: 20000 }).toBe(true);
  const r = await page.evaluate(() => {
    type G = { children: { name: string; visible: boolean; isMesh?: boolean }[] };
    const m = (window as unknown as { aftershockMap: { scoutGroup: G; responderGroup: G } }).aftershockMap;
    const pick = (g: G) => ({ model: g.children.some(c => c.name === 'scout' || c.name === 'responder'),
                              primsHidden: g.children.filter(c => c.isMesh).every(c => !c.visible) });
    return { scout: pick(m.scoutGroup), responder: pick(m.responderGroup) };
  });
  expect(r).toEqual({ scout: { model: true, primsHidden: true }, responder: { model: true, primsHidden: true } });
});
