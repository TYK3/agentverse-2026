import { test, expect } from '@playwright/test';
import { parseJsonl, ReplayPlayer, STATUS_TOPIC, type Scheduler } from '../src/replay-jsonl';

// An excerpt of a real run (SIM_RECORD, sim/recorder.py, #126): the full hub with every lane on the
// backup scene, an aftershock injected at about 15 s. Big payloads trimmed; order, t, topics and z kept.
const REAL = [
  "{\"t\":0.0,\"wall\":0.0,\"topic\":\"record/meta\",\"data\":{\"scene\":\"backup\",\"started\":\"2026-11-08T01:34:33\"}}",
  "{\"t\":0.0,\"wall\":0.0,\"topic\":\"scene/loaded\",\"data\":{\"scene\":\"backup\",\"blocks\":[{\"id\":\"b1\",\"label\":\"wall\",\"pos\":[-1.5,0.25,0.5],\"size\":[0.05,1.3,0.5]},{\"id\":\"b2\",\"label\":\"wall\",\"pos\":[2.5,0.25,0.5],\"size\":[0.05,1.3,0.5]}]}}",
  "{\"t\":0.1,\"wall\":0.094,\"topic\":\"sim/truth\",\"data\":{\"scene\":\"backup\",\"shaking\":false,\"scout\":{\"pos\":[-0.5,-1.5,0.075],\"yaw\":1.571,\"sensor\":[-0.5,-1.5,0.075],\"state\":\"idle\"},\"casualties\":{\"c1\":[2.0,1.0,0.12]},\"responder\":{\"pos\":[-0.5,-1.77,0.05],\"yaw\":1.571,\"state\":\"idle\",\"route\":null}}}",
  "{\"t\":0.2,\"wall\":0.266,\"topic\":\"sim/truth\",\"data\":{\"scene\":\"backup\",\"shaking\":false,\"scout\":{\"pos\":[-0.5,-1.5,0.075],\"yaw\":1.571,\"sensor\":[-0.5,-1.5,0.075],\"state\":\"idle\"},\"casualties\":{\"c1\":[2.0,1.0,0.12]},\"responder\":{\"pos\":[-0.5,-1.77,0.05],\"yaw\":1.571,\"state\":\"idle\",\"route\":null}}}",
  "{\"t\":0.2,\"wall\":0.281,\"topic\":\"say\",\"data\":{\"to\":\"casualty\",\"intent\":\"reassure\",\"text\":\"Hello? Is anyone there? If you can hear me, tap three times on something hard.\",\"lang\":\"auto\"}}",
  "{\"t\":0.6,\"wall\":0.719,\"topic\":\"map/cells\",\"data\":{\"t\":0.7,\"res\":0.05,\"cells\":[{\"cell\":[-31,-22,0],\"state\":\"seen\",\"occupied\":true},{\"cell\":[-30,-22,0],\"state\":\"seen\",\"occupied\":false}]}}",
  "{\"t\":1.1,\"wall\":1.266,\"topic\":\"scout/goto\",\"data\":{\"target\":[-0.575,-0.925,0.075],\"reason\":\"frontier at cell [-8, -15, 0], 9 unknown neighbours\"}}",
  "{\"t\":3.9,\"wall\":4.422,\"topic\":\"say\",\"data\":{\"to\":\"casualty\",\"intent\":\"reassure\",\"text\":\"If you can hear me and cannot tap, shout. I will keep listening.\",\"lang\":\"auto\"}}",
  "{\"t\":5.4,\"wall\":6.063,\"topic\":\"casualty/reply\",\"data\":{\"id\":\"c1\",\"t\":5.4,\"text\":\"Yes! Yes, I can hear you. Please help me.\",\"source\":\"sim\",\"level\":0.23}}",
  "{\"t\":10.0,\"wall\":11.313,\"topic\":\"sim/truth\",\"data\":{\"scene\":\"backup\",\"shaking\":false,\"scout\":{\"pos\":[-1.275,-0.076,0.075],\"yaw\":2.11,\"sensor\":[-1.275,-0.076,0.075],\"state\":\"arrived\"},\"casualties\":{\"c1\":[2.0,1.0,0.12]},\"responder\":{\"pos\":[-0.5,-1.77,0.05],\"yaw\":1.571,\"state\":\"idle\",\"route\":null}}}",
  "{\"t\":14.3,\"wall\":16.11,\"topic\":\"log/decision\",\"data\":{\"t\":16.06,\"perception\":\"Scout blocked going to [-1.23, 1.02]\",\"model\":\"local-handoff\",\"physics\":\"\",\"outcome\":\"resplit\",\"reason\":\"Explorer re-picks the Scout's frontier; Responder continues its casualty queue\"}}",
  "{\"t\":14.9,\"wall\":18.406,\"topic\":\"world/change\",\"data\":{\"kind\":\"aftershock\",\"t\":14.9,\"moved_blocks\":[\"b8\",\"b10\"]}}",
  "{\"t\":14.9,\"wall\":18.406,\"topic\":\"log/decision\",\"data\":{\"t\":18.36,\"perception\":\"aftershock moved b8, b10\",\"model\":\"local-astar\",\"physics\":\"\",\"outcome\":\"replanning\",\"reason\":\"no active route (was IDLE); waiting for the Scout to re-scan\"}}",
].join('\n');

class FakeTimers implements Scheduler {
  waits: number[] = [];
  private pending: (() => void) | null = null;
  set = (fn: () => void, ms: number) => { this.waits.push(ms); this.pending = fn; return this.waits.length; };
  clear = () => { this.pending = null; };
  runNext(): boolean { const fn = this.pending; this.pending = null; if (!fn) return false; fn(); return true; }
  runAll(): void { while (this.runNext()) { /* each step schedules the next */ } }
}

function record() {
  const out: { topic: string; data: unknown }[] = [];
  return { out, dispatch: (topic: string, data: unknown) => { out.push({ topic, data }); } };
}

const busOnly = (out: { topic: string; data: unknown }[]) => out.filter(m => m.topic !== STATUS_TOPIC);

test('S1: a real recording parses in file order with its scene and no issues', () => {
  const parsed = parseJsonl(REAL);
  expect(parsed.issues).toEqual([]);
  expect(parsed.meta?.scene).toBe('backup');
  expect(parsed.scene).toBe('backup');
  expect(parsed.events[0].topic).toBe('scene/loaded');           // record/meta is not a bus message
  const topics = parsed.events.map(e => e.topic);
  expect(topics.indexOf('world/change')).toBeGreaterThan(topics.indexOf('casualty/reply'));
  const ts = parsed.events.map(e => e.t);
  expect(ts).toEqual([...ts].sort((a, b) => a - b));
});

test('S1: replay keeps real-topic order, data and z untouched', () => {
  const parsed = parseJsonl(REAL);
  const { out, dispatch } = record();
  const timers = new FakeTimers();
  new ReplayPlayer(parsed, dispatch, { source: 'runs/live.jsonl', scheduler: timers }).start();
  timers.runAll();
  const bus = busOnly(out);
  expect(bus.map(m => m.topic)).toEqual(parsed.events.map(e => e.topic));
  expect(bus.map(m => m.data)).toEqual(parsed.events.map(e => e.data));
  const truth = bus.filter(m => m.topic === 'sim/truth').map(m => m.data as any);
  expect(truth[0].scout.pos).toEqual([-0.5, -1.5, 0.075]);          // z kept
  expect(truth[0].responder.pos[2]).toBe(0.05);
});

test('S1: pacing follows recorded sim time, scaled by speed', () => {
  const text = [0, 0, 0.1, 0.35, 0.35, 1.0].map((t, i) => JSON.stringify({ t, topic: `x/${i}`, data: i })).join('\n');
  for (const speed of [1, 2]) {
    const timers = new FakeTimers();
    const { out, dispatch } = record();
    new ReplayPlayer(parseJsonl(text), dispatch, { speed, scheduler: timers }).start();
    // events due at the same t go out together, before any wait
    expect(busOnly(out).map(m => m.topic)).toEqual(['x/0', 'x/1']);
    timers.runAll();
    expect(timers.waits.map(w => Math.round(w))).toEqual([100, 250, 650].map(ms => Math.round(ms / speed)));
    expect(busOnly(out).length).toBe(6);
  }
});

test('S1: the replay always says it is a replay, with file, time and progress', () => {
  const { out, dispatch } = record();
  const timers = new FakeTimers();
  const player = new ReplayPlayer(parseJsonl(REAL), dispatch, { source: 'runs/live.jsonl', scheduler: timers });
  expect(player.status().state).toBe('ready');
  player.start();
  timers.runAll();
  const statuses = out.filter(m => m.topic === STATUS_TOPIC).map(m => m.data as any);
  expect(statuses.length).toBeGreaterThan(2);
  for (const s of statuses) {
    expect(s.source).toBe('replay');
    expect(s.file).toBe('runs/live.jsonl');
    expect(s.scene).toBe('backup');
  }
  expect(statuses[0].state).toBe('playing');
  const last = statuses[statuses.length - 1];
  expect(last).toMatchObject({ state: 'done', index: last.total, t: 14.9 });
  expect(JSON.stringify(statuses)).not.toContain('"live"');
});

test('S1: malformed lines are skipped and reported, never thrown', () => {
  const text = [
    '{"t":0,"topic":"scene/loaded","data":{"scene":"tower","blocks":[]}}',
    '',
    'not json at all',
    '[1,2,3]',
    '{"t":0.1,"data":{}}',
    '{"t":-1,"topic":"a","data":1}',
    '{"t":"0.2","topic":"a","data":1}',
    '{"t":0.3,"topic":"a"}',
    '{"t":0.5,"topic":"ok/late","data":1}',
    '{"t":0.4,"topic":"ok/early","data":2}',
    '{"t":0.6,"topic":"ok/last","data":3}  ',
  ].join('\r\n');
  const parsed = parseJsonl(text);
  expect(parsed.issues.map(i => [i.line, i.reason])).toEqual([
    [3, 'not JSON'], [4, 'not an object'], [5, 'missing topic'], [6, 'missing or invalid t'],
    [7, 'missing or invalid t'], [8, 'missing data'], [10, 'time goes back (0.4 after 0.5); kept in file order'],
  ]);
  expect(parsed.scene).toBe('tower');
  expect(parsed.events.map(e => e.topic)).toEqual(['scene/loaded', 'ok/late', 'ok/early', 'ok/last']);
  const { out, dispatch } = record();
  const timers = new FakeTimers();
  const player = new ReplayPlayer(parsed, dispatch, { scheduler: timers });
  player.start();
  timers.runAll();
  expect(busOnly(out).map(m => m.topic)).toEqual(['scene/loaded', 'ok/late', 'ok/early', 'ok/last']);
  expect(player.status().skipped_lines).toBe(6);
});

test('S1: pause and stop cancel the pending step; an empty file just finishes', () => {
  const text = [0, 1, 2].map(t => JSON.stringify({ t, topic: 'x', data: t })).join('\n');
  const timers = new FakeTimers();
  const { out, dispatch } = record();
  const player = new ReplayPlayer(parseJsonl(text), dispatch, { scheduler: timers });
  player.start();
  player.pause();
  expect(timers.runNext()).toBe(false);
  expect(player.status()).toMatchObject({ state: 'paused', index: 1 });
  player.start();                       // resume: the next event keeps its remaining wait
  expect(player.status()).toMatchObject({ state: 'playing', index: 1 });
  expect(timers.runNext()).toBe(true);
  expect(player.status()).toMatchObject({ state: 'playing', index: 2 });
  player.stop();
  expect(timers.runNext()).toBe(false);
  expect(player.status()).toMatchObject({ state: 'stopped', index: 2 });
  expect(out.filter(m => m.topic === 'x').length).toBe(2);

  const empty = record();
  const p2 = new ReplayPlayer(parseJsonl('\n\n'), empty.dispatch, { scheduler: new FakeTimers() });
  p2.start();
  expect(p2.status()).toMatchObject({ state: 'done', total: 0 });
});

test('CONSOLE-LIVE: seeking rebuilds earlier events and waits for the next recorded time', () => {
  const text = [0, 1, 2].map(t => JSON.stringify({ t, topic: 'x', data: t })).join('\n');
  const timers = new FakeTimers();
  const { out, dispatch } = record();
  const player = new ReplayPlayer(parseJsonl(text), dispatch, { scheduler: timers, seekAt: 1.5 });
  player.start();
  expect(busOnly(out).map(m => m.data)).toEqual([0, 1]);
  expect(player.status()).toMatchObject({ state: 'playing', duration: 2, index: 2, t: 1 });
  expect(timers.waits).toEqual([500]);
  timers.runAll();
  expect(busOnly(out).map(m => m.data)).toEqual([0, 1, 2]);
  expect(player.status()).toMatchObject({ state: 'done', t: 2 });
});

test('CONSOLE-LIVE: browser controls pause and scrub a recording', async ({ page }) => {
  const jsonl = [
    { t: 0, topic: 'scene/loaded', data: { scene: 'levels', blocks: [] } },
    { t: 10, topic: 'world/change', data: { kind: 'aftershock', t: 10, moved_blocks: [] } },
    { t: 20, topic: 'report/handover', data: { json: {}, markdown: '# Handover' } },
  ].map(event => JSON.stringify(event)).join('\n');
  await page.route(url => url.pathname === '/runs/replay-controls.jsonl', route =>
    route.fulfill({ status: 200, contentType: 'text/plain', body: jsonl }));
  await page.goto('/?run=/runs/replay-controls.jsonl');
  const controls = page.locator('#replay-controls');
  await expect(controls.getByRole('button', { name: 'Pause replay' })).toBeVisible();
  await controls.getByRole('button', { name: 'Pause replay' }).click();
  await expect(controls.getByRole('button', { name: 'Play replay' })).toBeVisible();
  await controls.getByRole('button', { name: 'Play replay' }).click();
  await expect(controls.getByRole('button', { name: 'Pause replay' })).toBeVisible();
  await controls.getByRole('button', { name: 'Pause replay' }).click();
  await controls.locator('input[type="range"]').evaluate(input => {
    const slider = input as HTMLInputElement;
    slider.value = '15';
    slider.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.waitForURL(/seek=15/);
  await expect(controls.getByRole('button', { name: 'Pause replay' })).toBeVisible();
  await expect(page.locator('#story .story-badge')).toContainText('t 10.0 s');
});
