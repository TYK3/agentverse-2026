import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { STATUS_TOPIC, type Scheduler } from '../src/replay-jsonl';
import { adaptB2Run, playB2Run, B2_STATUS_TOPIC, SLAB_ID } from '../src/replay_b2';

// B2-CONSOLE-REPLAY. The fixture is a real run, unedited: `python tools/run_b2.py` (seed 0, 9/9 steps passed,
// 03:17 London on 8 Nov 2026) -> runs/b2-0.jsonl. L1 -> ground -> B1 -> B2, slab shift at 173.6 s, c2 at 179.3 s.
const REAL = readFileSync(fileURLToPath(new URL('./fixtures/b2-seed0.jsonl', import.meta.url)), 'utf8');

class FakeTimers implements Scheduler {
  waits: number[] = [];
  private pending: (() => void) | null = null;
  set = (fn: () => void, ms: number) => { this.waits.push(ms); this.pending = fn; return this.waits.length; };
  clear = () => { this.pending = null; };
  runAll(): void { for (let fn = this.pending; fn; fn = this.pending) { this.pending = null; fn(); } }
}

function record() {
  const out: { topic: string; data: any }[] = [];
  return { out, dispatch: (topic: string, data: unknown) => { out.push({ topic, data }); } };
}

test('B2: the real run adapts with no issues, its levels, its verdict and its result', () => {
  const run = adaptB2Run(REAL);
  expect(run.issues).toEqual([]);
  expect(run.records).toBe(455);
  expect(run.scene).toBe('levels');
  expect(run.result.levels).toEqual(['L1', 'ground', 'B1', 'B2']);
  expect(run.result.total).toBe(9);
  expect(run.result.passed).toBe(9);
  expect(run.result.reached).toBe(true);
  expect(run.result.final_level).toBe('B2');
  expect(run.result.final_pos![2]).toBeLessThan(-1);           // B2 stays below ground: z is untouched
  expect(run.result.shift_t).toBe(173.6);
  const topics = new Set(run.events.map(e => e.topic));
  expect([...topics].sort()).toEqual([B2_STATUS_TOPIC, 'log/decision', 'route/proposed', 'sensors/scout', 'world/change']);
  expect(run.events.filter(e => e.topic === 'sensors/scout')).toHaveLength(180);
});

test('B2: events keep file order and sim time; poses keep z and get a finite heading', () => {
  const run = adaptB2Run(REAL);
  for (let i = 1; i < run.events.length; i++) expect(run.events[i].t).toBeGreaterThanOrEqual(run.events[i - 1].t);
  const poses = run.events.filter(e => e.topic === 'sensors/scout').map(e => e.data as any);
  expect(poses[0]).toEqual({ t: 0, pose: { pos: [0.5, 0.5, 0.675], yaw: expect.any(Number) } });
  expect(poses.every(p => Number.isFinite(p.pose.yaw))).toBe(true);
  expect(Math.min(...poses.map(p => p.pose.pos[2]))).toBeLessThan(-1);   // it really drives down to B2
  const moving = poses.findIndex((p, i) => i + 1 < poses.length &&
    Math.hypot(poses[i + 1].pose.pos[0] - p.pose.pos[0], poses[i + 1].pose.pos[1] - p.pose.pos[1]) > 0.05);
  const [a, b] = [poses[moving].pose, poses[moving + 1].pose];
  expect(Math.cos(a.yaw)).toBeCloseTo((b.pos[0] - a.pos[0]) / Math.hypot(b.pos[0] - a.pos[0], b.pos[1] - a.pos[1]), 1);
});

test('B2: the slab shift is a world/change with a stop-and-recheck decision, then routes avoid it', () => {
  const run = adaptB2Run(REAL);
  const shift = run.events.findIndex(e => e.topic === 'world/change');
  expect(run.events[shift]).toMatchObject({ t: 173.6, data: { kind: 'aftershock', t: 173.6, moved_blocks: [SLAB_ID] } });
  expect(run.events[shift + 1].data).toMatchObject({ outcome: 'stop_and_recheck', perception: expect.stringContaining('B2') });
  expect(run.events.filter(e => e.topic === 'world/change')).toHaveLength(1);
  const mapped = run.events.find(e => e.topic === 'log/decision' && (e.data as any).outcome === 'mapped')!;
  expect((mapped.data as any).perception).toBe('5 slab cell(s) mapped from lidar, refused');
  const after = run.events.filter(e => e.topic === 'route/proposed' && e.t > 173.6).map(e => e.data as any);
  expect(after.length).toBeGreaterThan(0);
  const slab = run.events[shift].line;
  const footprint = new Set((JSON.parse(REAL.split('\n')[slab - 1]).footprint as number[][]).map(c => c.join(',')));
  for (const r of after) for (const c of r.cells) {
    if (c[2] === -24) expect(footprint.has(`${c[0]},${c[1]}`)).toBe(false);   // B2 cells never cross the slab
  }
});

test('B2: routes are well formed and only re-sent when the goal or status changes', () => {
  const run = adaptB2Run(REAL);
  const routes = run.events.filter(e => e.topic === 'route/proposed').map(e => e.data as any);
  expect(routes.length).toBeGreaterThan(3);
  expect(routes.length).toBeLessThan(267);                     // 267 plan records, deduplicated
  expect(new Set(routes.map(r => r.id)).size).toBe(routes.length);
  for (const r of routes) {
    expect(r).toMatchObject({ robot: 'scout', model: 'local-astar', goal: expect.any(String), reason: expect.any(String) });
    expect(r.cells.length).toBeGreaterThan(0);
    expect(r.cells.every((c: number[]) => c.length === 3 && c.every(Number.isInteger))).toBe(true);
  }
});

test('B2: the player paces by sim time, ends with the result, and never claims live', () => {
  const timers = new FakeTimers();
  const { out, dispatch } = record();
  const { player, run } = playB2Run(REAL, dispatch, { source: 'runs/b2-0.jsonl', speed: 10, scheduler: timers });
  player.start();
  timers.runAll();
  const status = out.filter(m => m.topic === STATUS_TOPIC).map(m => m.data);
  expect(status.every(s => s.source === 'replay' && s.file === 'runs/b2-0.jsonl' && s.scene === 'levels')).toBe(true);
  expect(status.at(-1)).toMatchObject({ state: 'done', index: run.events.length, total: run.events.length });
  const bus = out.filter(m => m.topic !== STATUS_TOPIC);
  expect(bus).toHaveLength(run.events.length);
  expect(bus.at(-1)).toEqual({ topic: B2_STATUS_TOPIC, data: { source: 'replay', ...run.result } });
  const total = timers.waits.reduce((a, b) => a + b, 0);
  expect(total).toBeCloseTo(179.3 * 1000 / 10, 0);             // 179.3 s of sim time at speed 10
  expect(JSON.stringify(out)).not.toContain('"live"');
});

test('B2: malformed and unknown lines are reported, never thrown', () => {
  const run = adaptB2Run([
    '{"t":0,"kind":"level","level":"L1"}',
    'not json',
    '[1,2]',
    '{"t":1,"kind":"pose"}',
    '{"kind":"pose","pos":[0,0,0]}',
    '{"t":2,"kind":"teleport","to":"B3"}',
    '{"t":3,"kind":"plan","status":"goal","cells":[[1.5,2,0]]}',
    '',
    '{"t":2.5,"kind":"pose","pos":[1,1,0.075],"state":"moving","level":"ground"}',
  ].join('\n'));
  expect(run.issues.map(i => i.line).sort((a, b) => a - b)).toEqual([2, 3, 4, 5, 6, 7, 9]);   // 9: time goes back, kept
  expect(run.issues.find(i => i.line === 6)!.reason).toBe('unknown kind teleport');
  expect(run.events.map(e => e.topic)).toEqual(['log/decision', 'log/decision', 'sensors/scout']);
  expect(run.result.total).toBe(0);
  expect(run.events.some(e => e.topic === B2_STATUS_TOPIC)).toBe(false);   // no summary/verdict: no result claimed
});
