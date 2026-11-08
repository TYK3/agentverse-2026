import { test, expect } from '@playwright/test';
import { parseJsonl } from '../src/replay-jsonl';

// CONSOLE-E2E-REPLAY: inline development recording, not a captured simulation run.
// The browser seam is ?run= -> fetch -> JSONL parser/player -> bus -> rendered report.
// This catches replay/UI integration failures, not the simulator's driving or planner safety.
// Floor heights and wire envelopes follow coord/CONTRACT.md; no scene reset between legs.
function chainedRecording(): string {
  const records: { t: number; topic: string; data: unknown }[] = [];
  const emit = (topic: string, data: unknown) => records.push({ t: records.length / 10, topic, data });
  emit('record/meta', { scene: 'levels', source: 'inline chained B1>B3 test' });
  emit('scene/loaded', { scene: 'levels', blocks: [] });
  emit('scout/goto', { target: [0.5, 0.5, -0.6], reason: 'explore the basement floors' });
  for (const [index, floor] of ['B1', 'B2', 'B3'].entries()) {
    const z = [-0.6, -1.2, -1.8][index];
    const id = `c${index + 1}`, route = `r${index + 1}`, gate = `g${index + 1}`;
    const pos = [0.5, 0.5, z];
    emit('map/cells', { t: records.length / 10, res: 0.05,
      cells: [{ cell: [10, 10, [-12, -24, -36][index]], state: 'seen', occupied: false }] });
    emit('map/casualties', [{ id, pos, confidence: 0.9, clues: ['thermal', 'sound'],
      vitals: { breathing_rate: 14, simulated: true } }]);
    emit('casualty/reply', { id, t: records.length / 10, text: `I am on ${floor}`, source: 'sim' });
    emit('route/proposed', { id: route, robot: 'responder', cells: [[10, 10, [-12, -24, -36][index]]],
      goal: `deliver water to ${id} on ${floor}`, model: 'local-astar' });
    emit('route/verified', { id: route, ok: true, unstable_cells: [], detail: 'checked' });
    emit('gate/request', { id: gate, kind: 'risky_move', summary: `enter ${floor}`, route });
    emit('gate/answer', { id: gate, approved: true, by: 'operator' });
    emit('responder/pose', { t: records.length / 10, pos, yaw: 0, state: 'arrived', route, carrying: ['water'] });
    if (floor === 'B2') {
      emit('world/change', { kind: 'aftershock', t: records.length / 10, moved_blocks: ['x1'] });
      emit('permit/route', { route, granted: false, t: records.length / 10, reason: 'slab shifted', evidence: [] });
      emit('permit/route', { route, granted: true, t: records.length / 10, reason: 'fresh scan clear', evidence: [] });
    }
    emit('responder/action', { action: 'place_supply', route, item: 'water' });
    emit('log/decision', { t: records.length / 10, perception: `arrived at ${id} on ${floor}`,
      model: 'local-astar', physics: 'checked', outcome: 'done', reason: `placed water on ${floor}` });
  }
  emit('report/handover', { json: { casualties: 3 }, markdown: '# Chained B1 > B2 > B3\nWater delivered to c1, c2 and c3.' });
  return records.map(record => JSON.stringify(record)).join('\n');
}

test('CONSOLE-E2E-REPLAY: chained B1>B3 recording reaches the final report without errors', async ({ page }) => {
  const errors: string[] = [];
  const sockets: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('websocket', socket => {
    if (new URL(socket.url()).pathname === '/ws') sockets.push(socket.url());
  });

  const jsonl = chainedRecording();
  expect(parseJsonl(jsonl).issues).toEqual([]);
  await page.route('**/runs/chained-b1-b3.jsonl', route => route.fulfill({
    status: 200, contentType: 'application/x-ndjson', body: jsonl,
  }));
  await page.goto('/?run=/runs/chained-b1-b3.jsonl&speed=10');
  const badge = page.locator('#story .story-badge');
  await expect(badge).toContainText('REPLAY chained-b1-b3.jsonl');
  await expect(badge).toContainText(' · end');
  await expect(page.locator('#story .story-phase[data-state="done"]')).toHaveCount(10);
  const card = page.locator('#story .story-card');
  await expect(card).toBeVisible();
  const fact = (name: string) => card.locator('dt').filter({ hasText: new RegExp(`^${name}$`) }).locator('+ dd');
  await expect(fact('Scene')).toHaveText('levels');
  await expect(fact('Casualties found')).toHaveText('c1, c2, c3');
  await expect(fact('Replies heard')).toHaveText('3');
  await expect(fact('Deepest level reached')).toHaveText('z -1.8 m');
  await expect(fact('Supplies delivered')).toHaveText('water, water, water');
  await expect(fact('Approvals')).toHaveText('3 approved, 0 held, of 3 asked');
  await expect(fact('Ground moved')).toHaveText('1');
  await expect(fact('Stops / rechecks')).toHaveText('1 / 1');
  await expect(card.locator('pre')).toContainText('Chained B1 > B2 > B3');
  await expect(fact('Phases reached')).toHaveText('10 of 10');
  expect(sockets).toEqual([]); // Replay must not also connect to the live hub.
  expect(errors).toEqual([]);
});
