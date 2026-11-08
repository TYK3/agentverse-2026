import { test, expect } from '@playwright/test';

// ASSET-LOD (ref A1): in software WebGL (CI's SwiftShader) the console loads the textureless tower.
type Assets = { loaded: boolean; error?: string; blocks: string[]; softwareGl: boolean; towerFile: string };
const assets = (page: import('@playwright/test').Page) =>
  page.evaluate(() => {
    const a = (window as unknown as { aftershockAssets: Assets }).aftershockAssets;
    return { loaded: a.loaded, error: a.error, blocks: a.blocks, softwareGl: a.softwareGl, towerFile: a.towerFile };
  });

test('A1 LOD: software GL loads aftershock_lite.glb with every tower block', async ({ page }) => {
  const fetched: string[] = [];
  page.on('request', r => { if (/\/models\/.*\.glb$/.test(r.url())) fetched.push(r.url().split('/').pop()!); });
  await page.goto('/?fake=1&building=1');
  await expect.poll(async () => (await assets(page)).loaded, { timeout: 20000 }).toBe(true);
  const a = await assets(page);
  expect(a.error).toBeUndefined();
  expect(a.blocks).toHaveLength(27);
  if (a.softwareGl) {
    expect(a.towerFile).toBe('aftershock_lite.glb');
    expect(fetched).toContain('aftershock_lite.glb');
    expect(fetched).not.toContain('aftershock.glb');
  } else {
    expect(a.towerFile).toBe('aftershock.glb');
  }
  await page.goto('about:blank');   // stop drawing the tower: in software GL it starves the next test's setup
});

test('A1 LOD: ?lod=full loads the full tower even in software GL', async ({ page }) => {
  await page.goto('/?fake=1&building=1&lod=full');
  await expect.poll(async () => (await assets(page)).loaded, { timeout: 20000 }).toBe(true);
  expect((await assets(page)).towerFile).toBe('aftershock.glb');
  await page.goto('about:blank');
});
