import { test, expect } from '@playwright/test';

test('Y4 replaces observed snapshots and slices basement heights with risk colors', async ({ page }) => {
  await page.goto('/?fake=1');
  await expect(page.locator('#budget-panel')).toContainText('Demo edge device');
  await page.locator('#reject').click();
  await page.locator('#reject').click();
  await page.evaluate(() => {
    const bus = window as any;
    bus.dispatchBusMessage('map/cells', { t:20, res:0.1, cells:[
      {cell:[0,0,-10],state:'seen',occupied:true},
      {cell:[1,0,-10],state:'seen',occupied:false},
      {cell:[0,0,0],state:'seen',occupied:true},
      {cell:[1,1,0],state:'inferred',occupied:false},
      {cell:[5,5,0],state:'unknown',occupied:false}
    ]});
    bus.dispatchBusMessage('map/hazards', [{cell:[0,0,-10],status:'at_risk',exclusion:true,estimate:true}]);
    bus.dispatchBusMessage('map/casualties', [{id:'c-basement',pos:[0.1,0,-0.95],confidence:0.83}]);
  });
  await expect(page.locator('#interior-counts')).toContainText('2 surfaces · 1 observed free cells · 1 inferred');
  await expect(page.locator('#interior-casualties')).toContainText('c-basement · 83% estimate');
  await page.selectOption('#interior-layer', '-10');
  await expect(page.locator('#interior-counts')).toContainText('1 surfaces · 1 observed free cells');
  const observation = () => page.evaluate(() => {
    const viewer = (window as any).aftershockMap;
    const group = viewer.scene.getObjectByName('observed-interior');
    const mesh = group.getObjectByName('observed-interior-surfaces');
    return {n:mesh.count,rgb:Array.from(mesh.instanceColor.array.slice(0,3)),freeVisible:group.getObjectByName('observed-free-voids').visible,planes:viewer.renderer.clippingPlanes.length};
  });
  await expect.poll(async () => (await observation()).n).toBe(1);
  const rgb = (await observation()).rgb as number[];
  expect(rgb[0]).toBeGreaterThan(rgb[1]);
  expect(rgb[2]).toBeGreaterThan(rgb[1]);
  expect((await observation()).planes).toBe(2);
  await page.locator('#interior-show-free').uncheck();
  await expect.poll(async () => (await observation()).freeVisible).toBe(false);
  await page.locator('#interior-casualties button').click();
  await page.evaluate(() => (window as any).dispatchBusMessage('map/cells',{t:21,res:0.1,cells:[]}));
  await expect(page.locator('#interior-counts')).toContainText('0 surfaces · 0 observed free cells');
  await expect.poll(async () => (await observation()).n).toBe(0);
});
