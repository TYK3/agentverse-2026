import { test, expect } from '@playwright/test';
import { createHash } from 'node:crypto';
import { gunzipSync } from 'node:zlib';
import { STATUS_TOPIC, type Scheduler } from '../src/replay-jsonl';
import { adaptB3Run, playB3Run, B3_STATUS_TOPIC, B3_LEVELS, SLAB_ID } from '../src/replay_b3';

// B3-CONSOLE-REPLAY. The fixture is a real run, unedited, kept in this spec (scope: these two files only):
// `python tools/run_b2.py --floor B3 --seed 0` (#185; 9/9 steps passed, 03:38 London on 8 Nov 2026)
// -> runs/b3-0.jsonl, 598 records, 150,165 bytes, gzip -9 then base64 below; the sha256 is checked first.
// L1 -> ground -> B1 -> B2 -> B3, slab x1 lands on the route in B3 at 225.8 s, c3 reached at 230.9 s.
// To refresh: rerun that command and regenerate RUN_B3_SEED0 and RUN_B3_SHA256 from the new log.
const RUN_B3_SHA256 = '4c14bb857cf87783f5db223f905b664abe0b61beff6b5c7401b51ae928fd2daf';
const RUN_B3_SEED0 = [
  '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',
  'XHdgeJLLuE0MVzgGSRyhCMd6CbME/m8dAr5HwPcI+B4B3yPgewR8j4DvEfA9Ar5HwPcI+B4B3yPgOwR8h4BvEfAtAr59DODbxu5U25teVuYXbX',
  '+hobj7ArovgPukAPdF0iHpkQxAMvdJge4LVfc5dJ9F9xl0n0H3GXSfQfeZHeO1vXhC5RvTwxfvr0hKdN92ujn0l31mf7nGUiLNr+ze1Rv3EGdK',
  'FwUJXQt+jmUZJOdERfTsC4iK8KJA2DV6hR7nINqoi34rm0sBNpcCbB5JlEpi9UXicMxt7i63eePJSSHjXpMXan8dhVaFlPAIpnRNlzCVcs3Udx',
  'jiU/GzHF3P6Tgl6hAa4j0h1ypPL8+HUKYAZ8oz9MvXjx9v7v+Mi94Pd3f381fub2/e/H47/NHD/dfb4ffvPt18+DurFaVb9xDg0x8tBPp488+/',
  '/7+vHz+f/stJZTVgavbO5LNI/v19FFvWRf7j9v7tuzcPyfO3nwdx/vXq7e2XN7ef3t6+vYq8r379M//wcHf18PvtVYqBq1HHfw1sJ80GLp++fv',
  'hw+vHt7cPNuyj6f9HV6/9z9Y+TYJ/eDj/9JdJ/kfF/1at/D+w/3Px69fb+blj5XN19ioyGoPx0IqNC439sch/LFTP7+O2bh0WpYvhgZv5/h2Xa',
  '1ZeHxP3L73f3D1d3v0V2w7/dYJOWPIzNEE1X4wJqUiqt5q5+u7/7GL8Ymf3PL1d3//3p6uPtzZev97cfbz89fHkkF3119+bN18/vTp8cgvM/vv',
  'zn1btPk6in704Fl6v/iMvEX67yIvE/o0z3t6/Rrjd/3L17++VcZe3/spN/Pt88/P7l6ua3h9v79JmhQJS+e/XugVk450H8ozcnzW8+PPz5eL/m',
  '2J1lSC4tJM/KtZ9O8Xt/dbLy7X1mv6nqKnjTv3336cu7t7ejOp9OmXD74fbzKVAe95FT2l6dQOY2J+3Vx6vPg7HevXmfnJIi/I/RgIPQJ0FPoZ',
  'Pi5pRAu5Pv7v3V+xkJXv174Pf55suXiEd/PS/bdyfqI5Ls7Hx5TDCfH3qtmFl4f7/zIsSffJT8cILo/w9uT9OflUoCAA==',
].join('');
const REAL = gunzipSync(Buffer.from(RUN_B3_SEED0, 'base64')).toString('utf8');

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

test('B3: the fixture is the recorded run, byte for byte', () => {
  expect(createHash('sha256').update(REAL, 'utf8').digest('hex')).toBe(RUN_B3_SHA256);
  expect(REAL.trim().split('\n')).toHaveLength(598);
});

test('B3: the real run adapts with no issues, all five levels in order, its verdict and its result', () => {
  const run = adaptB3Run(REAL);
  expect(run.issues).toEqual([]);
  expect(run.records).toBe(598);
  expect(run.scene).toBe('levels');
  expect(run.result.levels).toEqual(B3_LEVELS);
  expect(run.result.descended_in_order).toBe(true);
  expect(run.result).toMatchObject({ floor: 'B3', total: 9, passed: 9, reached: true, on_target: true,
                                     final_level: 'B3', route: 'ok', route_k: [12, -36],
                                     shift_t: 225.8, shift_level: 'B3' });
  expect(run.result.final_pos![2]).toBeLessThan(-1.6);         // B3 stays 1.8 m down: z is untouched
  const topics = new Set(run.events.map(e => e.topic));
  expect([...topics].sort()).toEqual([B3_STATUS_TOPIC, 'log/decision', 'route/proposed', 'sensors/scout', 'world/change']);
  expect(run.events.filter(e => e.topic === 'sensors/scout')).toHaveLength(231);
  const b3 = run.events.find(e => e.topic === 'log/decision' && (e.data as any).perception.startsWith('Scout on B3'))!;
  expect(b3).toMatchObject({ t: 217, data: { perception: 'Scout on B3, the target floor', outcome: 'level' } });
});

test('B3: events keep file order and sim time; poses keep z, reach B3 and get a finite heading', () => {
  const run = adaptB3Run(REAL);
  for (let i = 1; i < run.events.length; i++) expect(run.events[i].t).toBeGreaterThanOrEqual(run.events[i - 1].t);
  const poses = run.events.filter(e => e.topic === 'sensors/scout').map(e => e.data as any);
  expect(poses[0]).toEqual({ t: 0, pose: { pos: [0.5, 0.5, 0.675], yaw: expect.any(Number) } });
  expect(poses.every(p => Number.isFinite(p.pose.yaw))).toBe(true);
  expect(Math.min(...poses.map(p => p.pose.pos[2]))).toBeCloseTo(-1.725, 3);   // it really drives down to B3
  const moving = poses.findIndex((p, i) => i + 1 < poses.length &&
    Math.hypot(poses[i + 1].pose.pos[0] - p.pose.pos[0], poses[i + 1].pose.pos[1] - p.pose.pos[1]) > 0.05);
  const [a, b] = [poses[moving].pose, poses[moving + 1].pose];
  expect(Math.cos(a.yaw)).toBeCloseTo((b.pos[0] - a.pos[0]) / Math.hypot(b.pos[0] - a.pos[0], b.pos[1] - a.pos[1]), 1);
});

test('B3: the slab shift in B3 is a world/change with a stop-and-recheck decision, then routes avoid it', () => {
  const run = adaptB3Run(REAL);
  const shift = run.events.findIndex(e => e.topic === 'world/change');
  expect(run.events[shift]).toMatchObject({ t: 225.8, data: { kind: 'aftershock', t: 225.8, moved_blocks: [SLAB_ID] } });
  expect(run.events[shift + 1].data).toMatchObject({ outcome: 'stop_and_recheck',
                                                      perception: 'slab landed on the route at [0.68, 0.93] on B3' });
  expect(run.events.filter(e => e.topic === 'world/change')).toHaveLength(1);
  const mapped = run.events.find(e => e.topic === 'log/decision' && (e.data as any).outcome === 'mapped')!;
  expect((mapped.data as any).perception).toBe('4 slab cell(s) mapped from lidar, refused');
  const after = run.events.filter(e => e.topic === 'route/proposed' && e.t > 225.8).map(e => e.data as any);
  expect(after.length).toBeGreaterThan(0);
  const footprint = new Set((JSON.parse(REAL.split('\n')[run.events[shift].line - 1]).footprint as number[][])
    .map(c => c.join(',')));
  let b3cells = 0;
  for (const r of after) for (const c of r.cells) {
    if (c[2] !== -36) continue;                                 // B3 floor cells
    b3cells += 1;
    expect(footprint.has(`${c[0]},${c[1]}`)).toBe(false);
  }
  expect(b3cells).toBeGreaterThan(0);
});

test('B3: routes are well formed and only re-sent when the goal or status changes', () => {
  const run = adaptB3Run(REAL);
  const routes = run.events.filter(e => e.topic === 'route/proposed').map(e => e.data as any);
  expect(routes.length).toBeGreaterThan(3);
  expect(routes.length).toBeLessThan(358);                     // 358 plan records, deduplicated
  expect(new Set(routes.map(r => r.id)).size).toBe(routes.length);
  expect(routes.every(r => r.id.startsWith('b3-r'))).toBe(true);
  for (const r of routes) {
    expect(r).toMatchObject({ robot: 'scout', model: 'local-astar', goal: expect.any(String), reason: expect.any(String) });
    expect(r.cells.length).toBeGreaterThan(0);
    expect(r.cells.every((c: number[]) => c.length === 3 && c.every(Number.isInteger))).toBe(true);
  }
  expect(routes.some(r => r.cells.some((c: number[]) => c[2] === -36))).toBe(true);   // plans reach the B3 floor
});

test('B3: the player paces by sim time, ends with the result, and never claims live', () => {
  const timers = new FakeTimers();
  const { out, dispatch } = record();
  const { player, run } = playB3Run(REAL, dispatch, { source: 'runs/b3-0.jsonl', speed: 10, scheduler: timers });
  player.start();
  timers.runAll();
  const status = out.filter(m => m.topic === STATUS_TOPIC).map(m => m.data);
  expect(status.every(s => s.source === 'replay' && s.file === 'runs/b3-0.jsonl' && s.scene === 'levels')).toBe(true);
  expect(status.at(-1)).toMatchObject({ state: 'done', index: run.events.length, total: run.events.length });
  const bus = out.filter(m => m.topic !== STATUS_TOPIC);
  expect(bus).toHaveLength(run.events.length);
  expect(bus.at(-1)).toEqual({ topic: B3_STATUS_TOPIC, data: { source: 'replay', ...run.result } });
  const total = timers.waits.reduce((a, b) => a + b, 0);
  expect(total).toBeCloseTo(230.9 * 1000 / 10, 0);             // 230.9 s of sim time at speed 10
  expect(JSON.stringify(out)).not.toContain('"live"');
});

test('B3: a log that is not a B3 run still replays but is flagged and never on target', () => {
  const lines = REAL.trim().split('\n');
  const summary = lines.findIndex(l => JSON.parse(l).kind === 'summary');
  const b2 = lines.map((l, i) => (i === summary ? JSON.stringify({ ...JSON.parse(l), floor: 'B2' }) : l)).join('\n');
  const run = adaptB3Run(b2);
  expect(run.issues).toEqual([{ line: summary + 1, reason: 'not a B3 run: summary floor is B2' }]);
  expect(run.result.on_target).toBe(false);
  const notReached = adaptB3Run(lines.map((l, i) =>
    (i === summary ? JSON.stringify({ ...JSON.parse(l), reached: false }) : l)).join('\n'));
  expect(notReached.issues).toEqual([]);
  expect(notReached.result.on_target).toBe(false);
});

test('B3: malformed and unknown lines are reported, never thrown', () => {
  const run = adaptB3Run([
    '{"t":0,"kind":"level","level":"L1"}',
    'not json',
    '[1,2]',
    '{"t":1,"kind":"pose"}',
    '{"kind":"pose","pos":[0,0,0]}',
    '{"t":2,"kind":"teleport","to":"B3"}',
    '{"t":3,"kind":"plan","status":"goal","cells":[[1.5,2,-36]]}',
    '',
    '{"t":2.5,"kind":"pose","pos":[1,1,-1.725],"state":"moving","level":"B3"}',
  ].join('\n'));
  expect(run.issues.map(i => i.line).sort((a, b) => a - b)).toEqual([2, 3, 4, 5, 6, 7, 9]);   // 9: time goes back, kept
  expect(run.issues.find(i => i.line === 6)!.reason).toBe('unknown kind teleport');
  expect(run.events.map(e => e.topic)).toEqual(['log/decision', 'log/decision', 'sensors/scout']);
  expect(run.result).toMatchObject({ total: 0, on_target: false, descended_in_order: false, floor: null });
  expect(run.events.some(e => e.topic === B3_STATUS_TOPIC)).toBe(false);   // no summary/verdict: no result claimed
});
