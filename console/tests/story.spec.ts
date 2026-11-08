import { test, expect } from '@playwright/test';
import { StoryModel, PHASES } from '../src/story-model';
import { parseJsonl } from '../src/replay-jsonl';

// A whole rescue as bus events, in the shapes coord/CONTRACT.md fixes (t in sim seconds).
const RUN: [string, unknown][] = [
  ['scene/loaded', { scene: 'building', blocks: [{ id: 'b1', label: 'column', pos: [0, 0, 1.4], size: [0.15, 0.15, 1.4] },
                                                 { id: 'b2', label: 'slab', pos: [4, 2, 2.9], size: [2, 2.25, 0.1] }] }],
  ['sim/truth', { scout: { pos: [2, -1.6, 0], yaw: 1.57 }, responder: { pos: [2, -2.8, 0], yaw: 1.57 } }],
  ['scout/goto', { target: [2, 1.2, 0.26], reason: 'frontier at cell [40, 24, 0]' }],
  ['map/casualties', [{ id: 'c2', pos: [10.2, 7.4, 0.15], confidence: 0.82, clues: ['thermal', 'sound'],
                        vitals: { breathing_rate: 14, simulated: true } }]],
  ['say', { to: 'casualty', intent: 'reassure', text: 'Hello, can you hear me?', lang: 'auto' }],
  ['casualty/reply', { id: 'c2', t: 21.4, text: 'Yes, my leg is trapped.', source: 'sim', level: 0.4 }],
  ['responder/pose', { t: 30, pos: [9.5, 6.8, -3.0], yaw: 0, state: 'moving', route: 'r2', carrying: ['water'] }],
  ['gate/request', { id: 'g4', kind: 'risky_move', summary: 'enter the pancake void', route: 'r2' }],
  ['gate/answer', { id: 'g4', approved: true, by: 'operator' }],
  ['responder/action', { action: 'place_supply', route: 'r2', item: 'water' }],
  ['log/decision', { t: 41.0, perception: 'responder at [10.1, 7.2]', model: 'sim', physics: 'mujoco', outcome: 'done',
                     reason: 'placed water at [10.20, 7.30]' }],
  ['world/change', { kind: 'aftershock', t: 44.0, moved_blocks: ['b22', 'b57'] }],
  ['permit/route', { route: 'r3', granted: false, t: 44.2, reason: 'slab shift seen on the route', evidence: [] }],
  ['log/decision', { t: 44.3, perception: 'aftershock', model: 'sim', physics: 'mujoco', outcome: 'frozen', reason: 'stopped' }],
  ['permit/route', { route: 'r3', granted: true, t: 52.0, reason: 'every route cell re-seen free', evidence: [] }],
  ['report/handover', { json: { casualties: 1 }, markdown: '# Handover\n- c2: trapped leg, water delivered' }],
];

test('DEMO-FLOW: a whole rescue lights every phase in order, with the facts for the card', () => {
  const m = new StoryModel();
  const order: string[] = [];
  for (const [topic, data] of RUN) {
    const moved = m.apply(topic, data);
    if (moved && !order.includes(moved)) order.push(moved);
  }
  expect(order).toEqual(PHASES.map(p => p.id));
  for (const p of PHASES) expect(m.phase(p.id).state).toBe('done');
  expect(m.facts).toMatchObject({
    scene: 'building', replies: 1, delivered: ['water'], shifts: 1, stops: 2, rechecks: 1,
    approvals: { asked: 1, approved: 1, held: 0 }, deepestZ: -3,
  });
  expect(Object.keys(m.facts.casualties)).toEqual(['c2']);
  expect(m.t).toBe(44);                                             // last sim-timed event: the aftershock
});

test('DEMO-FLOW: camera focus follows the phase (scout target, casualty, responder)', () => {
  const m = new StoryModel();
  m.apply(...RUN[0]);
  m.apply(...RUN[1]);
  m.apply(...RUN[2]);
  expect(m.focus).toEqual([2, 1.2, 0.26]);                          // where the Scout is going
  m.apply(...RUN[3]);
  expect(m.focus).toEqual([10.2, 7.4, 0.15]);                       // the casualty, with its z
  m.apply(...RUN[6]);
  expect(m.focus).toEqual([9.5, 6.8, -3.0]);                        // the Responder down in the basement
});

test('DEMO-FLOW: approval waits, hold is shown as held, and nothing is invented', () => {
  const m = new StoryModel();
  m.apply('gate/request', { id: 'g1', kind: 'risky_move', summary: 'enter at-risk cell', route: 'r1' });
  expect(m.phase('approve').state).toBe('waiting');
  m.apply('gate/answer', { id: 'g1', approved: false, by: 'operator' });
  expect(m.phase('approve').state).toBe('held');
  expect(m.facts.approvals).toEqual({ asked: 1, approved: 0, held: 1 });
  // events that do not belong to a phase move nothing
  expect(m.apply('status/gemini', { mode: 'off' })).toBeNull();
  expect(m.apply('say', { to: 'operator', text: 'route ready' })).toBeNull();
  expect(m.apply('map/casualties', [])).toBeNull();
  expect(m.lit()).toEqual(['approve']);
});

test('DEMO-FLOW: in the browser, ?run= replays a recording through the strip and ends on the report card', async ({ page }) => {
  const jsonl = RUN.map(([topic, data], i) => JSON.stringify({ t: i * 0.05, topic, data })).join('\n');
  await page.route('**/runs/story-test.jsonl', route => route.fulfill({ status: 200, body: jsonl, contentType: 'text/plain' }));
  await page.goto('/?run=/runs/story-test.jsonl&speed=4');
  const strip = page.locator('#story .story-phase');
  await expect(strip).toHaveCount(10);
  await expect(page.locator('#story .story-badge')).toContainText('REPLAY story-test.jsonl');
  await expect(page.locator('#story .story-phase[data-state="done"]')).toHaveCount(10, { timeout: 10000 });
  const card = page.locator('#story .story-card');
  await expect(card).toBeVisible();
  await expect(card).toContainText('Supplies delivered');
  await expect(card).toContainText('water');
  await expect(card).toContainText('10 of 10');
  await expect(card).not.toContainText('887');
  await page.waitForTimeout(500);                                   // let the chip colours settle
  await page.screenshot({ path: 'test-results/story-replay.png' });
  await card.getByRole('button', { name: 'Close' }).click();
  await expect(card).toBeHidden();
});

test('DEMO-FLOW: live mode shows LIVE and the follow toggle', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#story .story-badge')).toHaveText('LIVE');
  const follow = page.locator('#story .story-follow');
  await expect(follow).toHaveAttribute('aria-pressed', 'true');
  await follow.click();
  await expect(follow).toHaveAttribute('aria-pressed', 'false');
});

test('DEMO-FLOW: time comes from sim clocks only, not from lanes that stamp their own', () => {
  const m = new StoryModel();
  m.apply('log/decision', { t: 887460.8, perception: 'x', model: 'local-contact', physics: '', outcome: 'say', reason: 'r' });
  m.apply('casualty/reply', { id: 'c1', t: 887461.0, text: 'yes', source: 'sim' });
  expect(m.t).toBe(0);
  m.apply('responder/pose', { t: 12.5, pos: [0, 0, 0], yaw: 0, state: 'idle', carrying: [] });
  m.setTime(14.9);
  expect(m.t).toBe(14.9);
});

// B3-SHIFT-STORY: a real tools/run_b2.py --floor B3 log (seed 0, 9/9 checks): the slab lands on B3 at
// 225.8 s, the Scout stops, maps it from its own LiDAR and re-plans around it.
test('B3-SHIFT-STORY: the real B3 run lights slab shift, then stop, then recheck, in that order', async () => {
  const fs = await import('node:fs');
  const parsed = parseJsonl(fs.readFileSync('public/replays/b3-shift.jsonl', 'utf-8'));
  expect(parsed.issues).toEqual([]);
  const m = new StoryModel();
  const beats: [string, string, number][] = [];
  for (const ev of parsed.events) {
    const before = m.phase('recheck').state;
    const moved = m.apply(ev.topic, ev.data);
    if (moved === 'shift' || (moved === 'recheck' && m.phase('recheck').state !== before)) {
      beats.push([moved, m.phase(moved).state, ev.t]);
    }
  }
  expect(beats).toEqual([['shift', 'done', 225.8], ['recheck', 'held', 226.0], ['recheck', 'done', 226.0]]);
  expect(m.phase('recheck').note).toBe('re-planned around the slab from a fresh scan');
  expect(m.phase('descend').state).toBe('done');
  expect(m.phase('found').note).toBe('Scout reached c3 on B3');
  expect(m.facts.deepestZ).toBeLessThan(-1.7);                     // the real B3 height
  expect(m.facts).toMatchObject({ scene: 'levels', shifts: 1, stops: 1, rechecks: 1 });
  expect(m.facts.reportMarkdown).toContain('# Run checks: 9/9 passed');
  expect(m.t).toBe(230.9);
});

test('B3-SHIFT-STORY: run_b2 records replay as run/<kind>; a record without kind or topic is still an issue', () => {
  const parsed = parseJsonl([
    '{"t": 225.8, "kind": "shift", "xy": [0.675, 0.925], "level": "B3"}',
    '{"t": 226.0, "pose": [1, 2, 3]}',
  ].join('\n'));
  expect(parsed.events).toEqual([{ t: 225.8, topic: 'run/shift', data: { t: 225.8, xy: [0.675, 0.925], level: 'B3' }, line: 1 }]);
  expect(parsed.issues).toEqual([{ line: 2, reason: 'missing topic' }]);
});

test('B3-SHIFT-STORY: in the browser the B3 replay shows the shift beat and its recheck on the card', async ({ page }) => {
  await page.goto('/?run=/replays/b3-shift.jsonl&speed=400');
  await expect(page.locator('#story .story-badge')).toContainText('end', { timeout: 60000 });
  for (const phase of ['quake', 'descend', 'shift', 'recheck', 'found', 'report']) {
    await expect(page.locator(`#story .story-phase[data-phase="${phase}"]`)).toHaveAttribute('data-state', 'done');
  }
  const card = page.locator('#story .story-card');
  await expect(card).toContainText('Stops / rechecks');
  await expect(card).toContainText('1 / 1');
  await expect(card).toContainText('Run checks: 9/9 passed');
});
