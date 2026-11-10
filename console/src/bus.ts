export type Envelope = { topic: string; data: unknown };
export type Handler = (data: unknown) => void;
const WS_URL = 'ws://localhost:8000/ws';
const RECONNECT_MS = 2000;
const fake = new URLSearchParams(window.location.search).get('fake') === '1';
const listeners = new Map<string, Set<Handler>>();
let socket: WebSocket | null = null;
let retry: number | undefined;
let stopped = false;

type ReplayStatus = { state: 'ready' | 'playing' | 'paused' | 'done' | 'stopped'; t: number; duration?: number };
type ReplayController = { start: () => void; pause: () => void; status: () => ReplayStatus };
let replayControls: { root: HTMLElement; button: HTMLButtonElement; slider: HTMLInputElement;
                      time: HTMLElement; seeking: boolean } | null = null;

function updateReplayControls(status: ReplayStatus): void {
  if (!new URLSearchParams(window.location.search).has('run')) return;
  const mode = document.getElementById('mode-label');
  if (mode) mode.textContent = 'REPLAY · recording';
  const connection = document.getElementById('connection-status');
  if (connection) connection.textContent = 'Recording replay';
  if (!replayControls) {
    const root = document.createElement('div');
    root.id = 'replay-controls';
    root.setAttribute('aria-label', 'Recording playback');
    root.style.cssText = 'position:fixed;left:50%;bottom:5.5rem;transform:translateX(-50%);z-index:50;'
      + 'display:flex;align-items:center;gap:.6rem;padding:.55rem .8rem;border:1px solid #54718b;'
      + 'border-radius:.5rem;background:#102337;color:#edf5fa;box-shadow:0 4px 16px #0009';
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-label', 'Pause replay');
    button.addEventListener('click', () => {
      const player = (window as unknown as { activeReplayPlayer?: ReplayController }).activeReplayPlayer;
      if (!player) return;
      if (player.status().state === 'done') {
        const params = new URLSearchParams(window.location.search);
        params.delete('seek');
        window.location.search = params.toString();
      } else if (player.status().state === 'playing') player.pause();
      else player.start();
    });
    const slider = document.createElement('input');
    slider.type = 'range';
    slider.min = '0';
    slider.max = '0';
    slider.step = '0.1';
    slider.setAttribute('aria-label', 'Seek replay time');
    slider.style.width = 'min(34vw, 22rem)';
    const time = document.createElement('span');
    time.style.cssText = 'font:12px ui-monospace,monospace;white-space:nowrap';
    slider.addEventListener('input', () => {
      if (!replayControls) return;
      replayControls.seeking = true;
      time.textContent = `${Number(slider.value).toFixed(1)} / ${Number(slider.max).toFixed(1)} s`;
    });
    slider.addEventListener('change', () => {
      const params = new URLSearchParams(window.location.search);
      params.set('seek', slider.value);
      window.location.search = params.toString();
    });
    root.append(button, slider, time);
    document.body.appendChild(root);
    replayControls = { root, button, slider, time, seeking: false };
  }
  const { button, slider, time } = replayControls;
  button.textContent = status.state === 'playing' ? 'Pause' : status.state === 'done' ? 'Restart' : 'Play';
  button.setAttribute('aria-label', `${button.textContent} replay`);
  slider.max = String(status.duration ?? 0);
  slider.disabled = !(status.duration && status.duration > 0);
  if (!replayControls.seeking) {
    slider.value = String(status.t);
    time.textContent = `${status.t.toFixed(1)} / ${(status.duration ?? 0).toFixed(1)} s`;
  }
}

export function on(topic: string, handler: Handler): () => void {
  const handlers = listeners.get(topic) ?? new Set<Handler>();
  handlers.add(handler);
  listeners.set(topic, handlers);
  return () => { handlers.delete(handler); if (!handlers.size) listeners.delete(topic); };
}

function dispatch(message: Envelope): void {
  console.log('[bus]', message.topic, message.data);
  if (message.topic === 'console/replay') updateReplayControls(message.data as ReplayStatus);
  listeners.get(message.topic)?.forEach(handler => handler(message.data));
  listeners.get('*')?.forEach(handler => handler(message));
}

(window as unknown as { dispatchBusMessage: (topic: string, data: unknown) => void }).dispatchBusMessage =
  (topic: string, data: unknown) => dispatch({ topic, data });

function parseMessage(raw: string): void {
  try {
    const message: unknown = JSON.parse(raw);
    if (message && typeof message === 'object' && 'topic' in message && 'data' in message &&
        typeof (message as Envelope).topic === 'string') dispatch(message as Envelope);
    else console.warn('[bus] ignored invalid envelope', message);
  } catch (error) { console.warn('[bus] invalid JSON', error); }
}

export function send(topic: string, data: unknown): boolean {
  const message = JSON.stringify({ topic, data });
  if (fake) { console.info('[bus fake outgoing]', message); return true; }
  if (socket?.readyState !== WebSocket.OPEN) {
    console.warn('[bus] cannot send: WebSocket disconnected', topic);
    return false;
  }
  socket.send(message);
  return true;
}

async function replayFixtures(): Promise<void> {
  const response = await fetch('/fixtures/manifest.json');
  if (!response.ok) throw new Error('Fixture manifest unavailable');
  const paths: unknown = await response.json();
  if (!Array.isArray(paths)) throw new Error('Fixture manifest is invalid');
  for (const path of paths) {
    if (typeof path !== 'string' || !/^[\w.-]+\.json$/.test(path)) continue;
    const file = await fetch('/fixtures/' + encodeURIComponent(path));
    if (!file.ok) { console.warn('[bus] fixture unavailable', path); continue; }
    const fixture: unknown = await file.json();
    const events: unknown[] = Array.isArray(fixture) ? fixture : [fixture];
    for (const event of events) {
      if (event && typeof event === 'object' && 'topic' in event && 'data' in event &&
          typeof (event as Envelope).topic === 'string') {
        if (['gate/answer', 'operator/command'].includes((event as Envelope).topic)) continue;
        dispatch(event as Envelope);
      }
      else console.warn('[bus] fixture missing topic/data envelope', path);
    }
  }
}

export function connect(): void {
  stopped = false;
  if (fake) {
    void replayFixtures().catch(error => console.error('[bus] fixture replay failed', error));
    return;
  }
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  socket = new WebSocket(WS_URL);
  socket.addEventListener('open', () => dispatch({ topic: 'console/connection', data: { online: true } }));
  socket.addEventListener('message', event => parseMessage(String(event.data)));
  socket.addEventListener('close', () => {
    socket = null;
    dispatch({ topic: 'console/connection', data: { online: false } });
    if (!stopped) retry = window.setTimeout(connect, RECONNECT_MS);
  });
  socket.addEventListener('error', () => socket?.close());
}

export function disconnect(): void {
  stopped = true;
  if (retry !== undefined) window.clearTimeout(retry);
  socket?.close();
  socket = null;
}
