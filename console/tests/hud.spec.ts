import { test, expect } from '@playwright/test';
import { HudModel, formatClock } from '../src/hud';

// A whole rescue as bus events (t in sim seconds), the same shapes as story.spec.ts.
const RUN: [string, unknown][] = [
  ['scene/loaded', { scene: 'backup', blocks: [{ id: 'b1', label: 'column', pos: [0, 0, 1.4], size: [0.15, 0.15, 1.4] }] }],
  ['sensors/scout', { t: 3, pose: { pos: [0, 0, 0.075], yaw: 0 } }],
  ['scout/goto', { target: [2, 1.2, 0.26], reason: 'frontier' }],
  ['responder/pose', { t: 20, pos: [0, 0, 0], yaw: 0, state: 'idle', route: null, carrying: [] }],
  ['map/casualties', [{ id: 'c1', pos: [1.7, 0.9, 0.08], confidence: 0.9, clues: ['thermal'],
                        vitals: { breathing_rate: 14, simulated: true } }]],
  ['responder/pose', { t: 30, pos: [0.2, 0, 0], yaw: 0, state: 'moving', route: 'r1', carrying: ['water'] }],
  ['say', { to: 'casualty', intent: 'reassure', text: 'Help is coming.', lang: 'auto' }],
  ['responder/pose', { t: 45, pos: [0.5, 0.2, 0], yaw: 0, state: 'moving', route: 'r1', carrying: ['water'] }],
  ['responder/action', { action: 'place_supply', route: 'r1', item: 'water' }],
  ['world/change', { kind: 'aftershock', t: 50, moved_blocks: ['x1'] }],
  ['responder/pose', { t: 70, pos: [1.5, 0.8, 0], yaw: 0, state: 'arrived', route: 'r3', carrying: [] }],
  ['report/handover', { json: { casualties: 1 }, markdown: '# Handover' }],
];

test('CONSOLE-HUD: clock formats sim seconds', () => {
  expect(formatClock(null)).toBe('--:--');
  expect(formatClock(0)).toBe('0:00');
  expect(formatClock(65.9)).toBe('1:05');
  expect(formatClock(3725)).toBe('1:02:05');
});

test('CONSOLE-HUD: stages start in order with split times, the clock is sim time', () => {
  const m = new HudModel();
  expect(m.clock()).toBeNull();
  expect(m.stages().map(s => s.state)).toEqual(['pending', 'pending', 'pending', 'pending']);
  const seen: string[] = [];
  for (const [topic, data] of RUN) {
    m.apply(topic, data);
    const cur = m.stages().find(s => s.state === 'current')?.name;
    if (cur && !seen.includes(cur)) seen.push(cur);
  }
  expect(m.clock()).toBe(70);
  expect(seen).toEqual(['Find', 'Reach', 'Deliver']);   // Report ends the run: every stage done
  const st = m.stages();
  expect(st.map(s => s.state)).toEqual(['done', 'done', 'done', 'done']);
  expect(st.map(s => s.start)).toEqual([0, 30, 45, 70]);
  expect(st.map(s => s.took)).toEqual([30, 15, 25, 0]);
});

test('CONSOLE-HUD: the current stage never moves back, and a new scene starts a new run', () => {
  const m = new HudModel();
  for (const [topic, data] of RUN.slice(0, 9)) m.apply(topic, data);   // up to the supply placed
  expect(m.stages().find(s => s.state === 'current')?.name).toBe('Deliver');
  m.apply('say', { to: 'casualty', intent: 'reassure', text: 'Still here.', lang: 'auto' });   // a late Reach event
  expect(m.stages().find(s => s.state === 'current')?.name).toBe('Deliver');
  m.apply('scene/loaded', { scene: 'backup', blocks: [] });
  expect(m.stages().map(s => s.state)).toEqual(['current', 'pending', 'pending', 'pending']);
});

test('CONSOLE-HUD: a replay drives the clock from the recording', () => {
  const m = new HudModel();
  m.apply('console/replay', { source: 'replay', state: 'playing', t: 12.5 });
  expect(m.clock()).toBe(12.5);
});

test('CONSOLE-HUD: the map top bar shows the clock and the current stage from bus messages', async ({ page }) => {
  // A silent stand-in hub socket: a real hub on :8000 (another run on this machine) must not feed the page.
  await page.routeWebSocket(/:8000\/ws/, () => {});
  await page.goto('/');
  const hud = page.locator('#run-hud');
  await expect(hud).toBeVisible({ timeout: 15000 });   // the dev server's first compile can be slow
  await expect(hud.locator('.hud-clock')).toHaveText('T+--:--');
  await page.evaluate((run) => {
    const send = (window as unknown as { dispatchBusMessage: (t: string, d: unknown) => void }).dispatchBusMessage;
    for (const [topic, data] of run) send(topic, data);
  }, RUN.slice(0, 9));
  await expect(hud.locator('.hud-clock')).toHaveText('T+0:45');
  await expect(hud.locator('.hud-stage[data-state="current"]')).toHaveAttribute('data-stage', 'Deliver');
  await expect(hud.locator('.hud-stage[data-stage="Find"]')).toHaveText('Find 0:30');
});
