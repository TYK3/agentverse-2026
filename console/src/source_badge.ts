// CONSOLE-LIVE-BADGE: LIVE while the hub WebSocket feeds the console, REPLAY while a
// recorded run log is playing.
//
// The two feeds already wired in this folder:
// - LIVE: bus.connect() opens ws://localhost:8000/ws. main.ts calls connect() whenever
//   story mode is not replaying. The socket then publishes console/connection {online}.
// - REPLAY: a recorded run log. ?run=<url> (story.ts) plays one, and any ReplayPlayer
//   (replay-jsonl.ts, including a B2 log from replay_b2.ts) announces
//   console/replay {source:"replay", file, t, state}. That announcement is never live.
// ?fake=1 replays labelled fixtures on the hub path. It is not a run log, so the badge
// stays LIVE. A non-empty run query wins, the same switch setupStory uses.
//
// Colours follow the GEMINI status badge: LIVE green, REPLAY amber (the top bar's
// .online and .relook pills). The short reading is the text; the feed detail is the title.
//
// Nothing runs on import. One wiring line in console/src/main.ts, immediately before
// `if (!story.replaying) connect();` (on is already imported from ./bus):
//   mountSourceBadge(on);
// Also add, with the other imports: import { mountSourceBadge } from './source_badge';

import { STATUS_TOPIC } from './replay-jsonl';

export const SOURCE_BADGE_ID = 'source-badge';
export const HUB_SOCKET = 'ws://localhost:8000/ws';

export type SourceKind = 'live' | 'replay';

export type SourceState = {
  kind: SourceKind;
  label: 'LIVE' | 'REPLAY';
  title: string;
  className: string;
};

export type Subscribe = (topic: string, handler: (data: unknown) => void) => () => void;

const LIVE_CLASS = 'pill online';
const REPLAY_CLASS = 'pill relook';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function runName(file: string | undefined): string {
  if (!file) return 'run log';
  const base = file.split('/').pop();
  return base || file;
}

function paint(kind: SourceKind, detail?: { file?: string; t?: number; state?: string }): SourceState {
  if (kind === 'live') {
    return { kind, label: 'LIVE', title: `Hub WebSocket stream · ${HUB_SOCKET}`, className: LIVE_CLASS };
  }
  const clock = typeof detail?.t === 'number' && Number.isFinite(detail.t) ? ` · t ${detail.t.toFixed(1)} s` : '';
  const end = detail?.state === 'done' ? ' · end' : '';
  return {
    kind,
    label: 'REPLAY',
    title: `Recorded run log · ${runName(detail?.file)}${clock}${end}`,
    className: REPLAY_CLASS,
  };
}

/** Same switch as setupStory: a non-empty ?run= is a recorded run log; otherwise the hub stream. */
export function sourceFromSearch(search: string): SourceState {
  const run = new URLSearchParams(search).get('run');
  return run ? paint('replay', { file: run }) : paint('live');
}

/**
 * Fold one bus message into the badge. A console/replay announcement wins over the hub
 * and stays REPLAY when the log ends or the socket drops. Other topics are ignored,
 * including status/gemini (that badge is separate).
 */
export function sourceFromFeed(state: SourceState, topic: string, data: unknown): SourceState {
  if (topic === STATUS_TOPIC && isRecord(data) && data.source === 'replay') {
    return paint('replay', {
      file: typeof data.file === 'string' ? data.file : undefined,
      t: typeof data.t === 'number' ? data.t : undefined,
      state: typeof data.state === 'string' ? data.state : undefined,
    });
  }
  if (topic === 'console/connection' && state.kind !== 'replay' && isRecord(data)) {
    const next = paint('live');
    return data.online === true ? next : { ...next, title: `${next.title} · reconnecting` };
  }
  return state;
}

/** Paint an element the way the GEMINI status badge is painted: text, title, status role. */
export function paintSourceBadge(node: HTMLElement, state: SourceState): void {
  node.id = SOURCE_BADGE_ID;
  node.className = state.className;
  node.dataset.mode = state.kind;
  node.dataset.source = state.kind === 'live' ? 'hub' : 'run-log';
  node.textContent = state.label;
  node.title = state.title;
  node.setAttribute('role', 'status');
}

/**
 * Create the badge beside #gemini-status and keep it in step with the feed.
 * `subscribe` is the bus `on`. Pass `search` / `document` only from tests.
 */
export function mountSourceBadge(
  subscribe?: Subscribe,
  opts: { parent?: Node; search?: string; document?: Document } = {},
): HTMLElement {
  const doc = opts.document ?? document;
  const search = opts.search ?? location.search;
  const parent = opts.parent ?? doc.getElementById('top-bar') ?? doc.body;
  let node = doc.getElementById(SOURCE_BADGE_ID);
  if (!node) {
    node = doc.createElement('span');
    const gemini = doc.getElementById('gemini-status');
    if (gemini && gemini.parentNode === parent) gemini.insertAdjacentElement('afterend', node);
    else parent.appendChild(node);
  }
  const badge = node;
  let state = sourceFromSearch(search);
  paintSourceBadge(badge, state);
  if (subscribe && badge.dataset.wired !== '1') {
    badge.dataset.wired = '1';
    for (const topic of [STATUS_TOPIC, 'console/connection']) {
      subscribe(topic, data => {
        state = sourceFromFeed(state, topic, data);
        paintSourceBadge(badge, state);
      });
    }
  }
  return badge;
}
