import { test, expect } from '@playwright/test';
import { STATUS_TOPIC } from '../src/replay-jsonl';
import {
  HUB_SOCKET,
  mountSourceBadge,
  paintSourceBadge,
  sourceFromFeed,
  sourceFromSearch,
  SOURCE_BADGE_ID,
  type SourceState,
  type Subscribe,
} from '../src/source_badge';

// CONSOLE-LIVE-BADGE. Decision tests run in node (the console's unit-test style, same as
// replay-jsonl.spec.ts). The last test mounts the badge in the real page, because this
// change does not edit main.ts.

const replay = (over: Record<string, unknown> = {}) => ({
  source: 'replay', file: 'runs/b2-0.jsonl', state: 'playing', t: 12.5,
  index: 3, total: 10, speed: 1, scene: 'levels', skipped_lines: 0, ...over,
});

test('CONSOLE-LIVE-BADGE: the hub stream reads LIVE, a run log reads REPLAY', () => {
  const live = sourceFromSearch('');
  expect(live).toEqual({
    kind: 'live', label: 'LIVE', className: 'pill online',
    title: `Hub WebSocket stream · ${HUB_SOCKET}`,
  });
  expect(sourceFromSearch('?fake=1')).toEqual(live);                 // fixtures are not a run log
  expect(sourceFromSearch('?run=')).toEqual(live);                   // empty run, same as setupStory
  expect(sourceFromSearch('?benchmark=1')).toEqual(live);

  const recorded = sourceFromSearch('?run=/runs/b2-0.jsonl&speed=4');
  expect(recorded.label).toBe('REPLAY');
  expect(recorded.kind).toBe('replay');
  expect(recorded.className).toBe('pill relook');
  expect(recorded.title).toBe('Recorded run log · b2-0.jsonl');
  expect(sourceFromSearch('?fake=1&run=/replays/b2-0.jsonl').label).toBe('REPLAY');
});

test('CONSOLE-LIVE-BADGE: console/replay switches to REPLAY and the hub cannot claim it back', () => {
  let state = sourceFromSearch('');
  expect(sourceFromFeed(state, 'status/gemini', { mode: 'live' })).toBe(state);
  expect(sourceFromFeed(state, STATUS_TOPIC, { source: 'live', file: 'nope' })).toBe(state);
  expect(sourceFromFeed(state, STATUS_TOPIC, null)).toBe(state);

  state = sourceFromFeed(state, 'console/connection', { online: false });
  expect(state.label).toBe('LIVE');
  expect(state.title).toBe(`Hub WebSocket stream · ${HUB_SOCKET} · reconnecting`);
  state = sourceFromFeed(state, 'console/connection', { online: true });
  expect(state.title).toBe(`Hub WebSocket stream · ${HUB_SOCKET}`);

  state = sourceFromFeed(state, STATUS_TOPIC, replay());
  expect(state.label).toBe('REPLAY');
  expect(state.className).toBe('pill relook');
  expect(state.title).toBe('Recorded run log · b2-0.jsonl · t 12.5 s');

  const done = sourceFromFeed(state, STATUS_TOPIC, replay({ state: 'done', t: 179.3 }));
  expect(done.label).toBe('REPLAY');
  expect(done.title).toBe('Recorded run log · b2-0.jsonl · t 179.3 s · end');
  expect(sourceFromFeed(done, 'console/connection', { online: true })).toBe(done);
  expect(sourceFromFeed(done, 'console/connection', { online: false })).toBe(done);
});

class FakeEl {
  id = '';
  className = '';
  textContent = '';
  title = '';
  dataset: Record<string, string> = {};
  parentNode: FakeEl | null = null;
  children: FakeEl[] = [];
  attrs: Record<string, string> = {};
  setAttribute(name: string, value: string) { this.attrs[name] = value; }
  insertAdjacentElement(_where: string, node: FakeEl) {
    const kids = this.parentNode?.children;
    if (kids) kids.splice(kids.indexOf(this) + 1, 0, node);
    node.parentNode = this.parentNode;
    return node;
  }
  appendChild(node: FakeEl) {
    node.parentNode = this;
    this.children.push(node);
    return node;
  }
}

function fakePage() {
  const top = new FakeEl();
  top.id = 'top-bar';
  const gemini = new FakeEl();
  gemini.id = 'gemini-status';
  top.appendChild(gemini);
  const known = [top, gemini];
  const doc = {
    getElementById(id: string) {
      return [...known, ...top.children].find(node => node.id === id) ?? null;
    },
    createElement() { return new FakeEl(); },
    body: top,
  };
  return { top, gemini, doc: doc as unknown as Document };
}

test('CONSOLE-LIVE-BADGE: the badge sits beside GEMINI and follows the bus', () => {
  const { top, gemini, doc } = fakePage();
  const handlers = new Map<string, (data: unknown) => void>();
  const subscribe: Subscribe = (topic, handler) => { handlers.set(topic, handler); return () => {}; };
  const node = mountSourceBadge(subscribe, { document: doc, search: '', parent: top as unknown as Node });
  expect(node.id).toBe(SOURCE_BADGE_ID);
  expect(node.textContent).toBe('LIVE');
  expect(node.className).toBe('pill online');
  expect((node as unknown as FakeEl).attrs.role).toBe('status');
  expect(node.dataset).toMatchObject({ mode: 'live', source: 'hub', wired: '1' });
  expect(top.children.map(child => child.id)).toEqual(['gemini-status', SOURCE_BADGE_ID]);
  expect(top.children[top.children.indexOf(gemini) + 1]).toBe(node);

  handlers.get('console/connection')?.({ online: false });
  expect(node.textContent).toBe('LIVE');
  expect(node.title).toContain('reconnecting');
  handlers.get(STATUS_TOPIC)?.(replay({ file: '/runs/live.jsonl', state: 'paused', t: 1 }));
  expect(node.textContent).toBe('REPLAY');
  expect(node.className).toBe('pill relook');
  expect(node.dataset).toMatchObject({ mode: 'replay', source: 'run-log' });
  expect(node.title).toBe('Recorded run log · live.jsonl · t 1.0 s');
  handlers.get('console/connection')?.({ online: true });
  expect(node.textContent).toBe('REPLAY');

  const again = mountSourceBadge(subscribe, { document: doc, search: '?run=/runs/live.jsonl', parent: top as unknown as Node });
  expect(again).toBe(node);
  expect(top.children.filter(child => child.id === SOURCE_BADGE_ID)).toHaveLength(1);
  expect(handlers.size).toBe(2);                                   // second mount must not subscribe twice
});

test('CONSOLE-LIVE-BADGE: paintSourceBadge writes the reading and nothing else', () => {
  const node = new FakeEl() as unknown as HTMLElement;
  const state: SourceState = sourceFromSearch('?run=runs/demo.jsonl');
  paintSourceBadge(node, state);
  expect(node.textContent).toBe('REPLAY');
  expect(node.id).toBe(SOURCE_BADGE_ID);
  expect(node.title).toBe('Recorded run log · demo.jsonl');
});

test('CONSOLE-LIVE-BADGE: on the page, LIVE sits beside GEMINI and a run log flips it to REPLAY', async ({ page }) => {
  await page.routeWebSocket('ws://localhost:8000/ws', () => {});
  await page.goto('/');
  await page.evaluate(async () => {
    const badge = await import('/src/source_badge.ts');
    const bus = await import('/src/bus.ts');
    badge.mountSourceBadge(bus.on);
  });
  const el = page.locator('#source-badge');
  await expect(el).toHaveText('LIVE');
  await expect(el).toHaveAttribute('data-mode', 'live');
  await expect(el).toHaveAttribute('data-source', 'hub');
  await expect(el).toHaveClass('pill online');
  await expect(el).toHaveAttribute('title', `Hub WebSocket stream · ${HUB_SOCKET}`);
  const afterGemini = await page.locator('#top-bar').evaluate(bar => {
    const ids = [...bar.children].map(child => (child as HTMLElement).id);
    return ids[ids.indexOf('gemini-status') + 1];
  });
  expect(afterGemini).toBe('source-badge');
  expect(await el.evaluate(node => getComputedStyle(node).color)).toBe('rgb(121, 224, 173)');

  await page.evaluate(() => {
    (window as unknown as { dispatchBusMessage: (topic: string, data: unknown) => void }).dispatchBusMessage(
      'console/replay',
      { source: 'replay', file: 'runs/b2-0.jsonl', state: 'playing', t: 12.5, index: 3, total: 10, speed: 1, scene: 'levels', skipped_lines: 0 },
    );
  });
  await expect(el).toHaveText('REPLAY');
  await expect(el).toHaveAttribute('data-mode', 'replay');
  await expect(el).toHaveAttribute('data-source', 'run-log');
  await expect(el).toHaveClass('pill relook');
  await expect(el).toHaveAttribute('title', 'Recorded run log · b2-0.jsonl · t 12.5 s');
  expect(await el.evaluate(node => getComputedStyle(node).color)).toBe('rgb(255, 210, 127)');
});

test('CONSOLE-LIVE-BADGE: ?run= reads REPLAY on the page before the log is needed', async ({ page }) => {
  await page.routeWebSocket('ws://localhost:8000/ws', () => {});
  await page.route('**/runs/badge.jsonl', route => route.fulfill({
    status: 200, contentType: 'text/plain',
    body: `${JSON.stringify({ t: 0, topic: 'scene/loaded', data: { scene: 'backup', blocks: [] } })}\n`,
  }));
  await page.goto('/?run=/runs/badge.jsonl&speed=8');
  await page.evaluate(async () => {
    const { mountSourceBadge } = await import('/src/source_badge.ts');
    mountSourceBadge();
  });
  const el = page.locator('#source-badge');
  await expect(el).toHaveText('REPLAY');
  await expect(el).toHaveAttribute('data-source', 'run-log');
  await expect(el).toHaveAttribute('title', /badge\.jsonl/);
  await expect(el).toHaveClass(/relook/);
});
