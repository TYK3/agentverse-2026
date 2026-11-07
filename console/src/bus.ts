export type Envelope = { topic: string; data: unknown };
export type Handler = (data: unknown) => void;
const WS_URL = 'ws://localhost:8000/ws';
const RECONNECT_MS = 2000;
const fake = new URLSearchParams(window.location.search).get('fake') === '1';
const listeners = new Map<string, Set<Handler>>();
let socket: WebSocket | null = null;
let retry: number | undefined;
let stopped = false;

export function on(topic: string, handler: Handler): () => void {
  const handlers = listeners.get(topic) ?? new Set<Handler>();
  handlers.add(handler);
  listeners.set(topic, handlers);
  return () => { handlers.delete(handler); if (!handlers.size) listeners.delete(topic); };
}

function dispatch(message: Envelope): void {
  console.log('[bus]', message.topic, message.data);
  listeners.get(message.topic)?.forEach(handler => handler(message.data));
  listeners.get('*')?.forEach(handler => handler(message));
}

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
