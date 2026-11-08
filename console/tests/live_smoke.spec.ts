import { expect, test, type Page } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// CONSOLE-SMOKE. Start the hub the way a live run does (GEMINI_MODE=off,
// `uvicorn coord.hub:app` on port 8000, from the repo root) so the sim lane is
// ticking, then open the console. playwright.config.ts already serves the page.
//
// The browser stream is that hub socket. Raw sensors/scout stays on the machine
// (coord/CONTRACT.md). The Scout's camera position is forwarded as
// map/points.points_from and moves as soon as the Scout drives. The Responder
// stays idle until a route is approved, which is later than 10 s, so the pose
// check follows the Scout.

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const HUB = 'ws://localhost:8000/ws';
const POSE_WINDOW_MS = 10_000;
const MOVE_M = 0.05;

type Frame = { at: number; topic: string; data: unknown };

let hub: ChildProcess | undefined;
const hubLog: string[] = [];

function note(chunk: Buffer | string): void {
  hubLog.push(String(chunk));
  let size = hubLog.reduce((total, part) => total + part.length, 0);
  while (size > 24_000 && hubLog.length > 1) size -= hubLog.shift()!.length;
}

function hubTail(): string {
  return hubLog.join('').slice(-4_000);
}

function startHub(): ChildProcess {
  const env = { ...process.env, GEMINI_MODE: 'off' };
  delete env.SIM_SCENE;
  delete env.SIM_RECORD;
  delete env.SIM_RECORD_FULL;
  const child = spawn('python3', ['-m', 'uvicorn', 'coord.hub:app', '--host', '127.0.0.1', '--port', '8000'], {
    cwd: ROOT,
    env,
    detached: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout?.on('data', note);
  child.stderr?.on('data', note);
  child.on('error', error => note(String(error)));
  return child;
}

async function stopHub(child?: ChildProcess): Promise<void> {
  if (!child?.pid || child.exitCode != null) return;
  try { process.kill(-child.pid, 'SIGTERM'); } catch { child.kill('SIGTERM'); }
  const exited = new Promise<void>(resolve => child.once('exit', () => resolve()));
  await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 5_000))]);
  if (child.exitCode == null && child.pid) {
    try { process.kill(-child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); }
  }
}

async function waitForHub(child: ChildProcess): Promise<void> {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (child.exitCode != null) throw new Error(`hub exited ${child.exitCode}\n${hubTail()}`);
    if (hubLog.join('').includes('Application startup complete')) return;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error(`hub did not start within 45 s\n${hubTail()}`);
}

function watch(page: Page): { frames: Frame[]; urls: string[] } {
  const frames: Frame[] = [];
  const urls: string[] = [];
  page.on('websocket', ws => {
    urls.push(ws.url());
    ws.on('framereceived', frame => {
      try {
        const message = JSON.parse(String(frame.payload)) as { topic?: unknown; data?: unknown };
        if (typeof message.topic === 'string') frames.push({ at: Date.now(), topic: message.topic, data: message.data });
      } catch { /* not a hub envelope */ }
    });
  });
  return { frames, urls };
}

function xyz(value: unknown): [number, number, number] | null {
  if (!Array.isArray(value) || value.length < 3) return null;
  const [x, y, z] = value;
  if (typeof x !== 'number' || typeof y !== 'number' || typeof z !== 'number') return null;
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
  return [x, y, z];
}

/** Metres the Scout's camera moved during the window, from map/points.points_from. */
function scoutTravel(frames: Frame[], from: number, until: number): number {
  const points = frames
    .filter(frame => frame.at >= from && frame.at <= until && frame.topic === 'map/points')
    .map(frame => xyz((frame.data as { points_from?: unknown } | null)?.points_from))
    .filter((point): point is [number, number, number] => point != null);
  if (points.length < 2) return 0;
  const [x, y, z] = points[0];
  return points.reduce((furthest, point) => Math.max(furthest, Math.hypot(point[0] - x, point[1] - y, point[2] - z)), 0);
}

test.beforeAll(async () => {
  hub = startHub();
  await waitForHub(hub);
});

test.afterAll(async () => {
  await stopHub(hub);
});

test('the console joins the live hub, draws both robots, and sees a pose change within 10 s', async ({ page }) => {
  test.setTimeout(90_000);
  const { frames, urls } = watch(page);
  await page.goto('/');
  await expect(page.locator('#mode-label')).toHaveText('LIVE HUB');
  await expect(page.locator('#connection-status')).toHaveText('Hub connected', { timeout: 20_000 });
  const connectedAt = Date.now();
  expect(urls).toContain(HUB);
  await expect(page.locator('#gemini-status')).toHaveText('GEMINI: OFF', { timeout: 10_000 });
  await expect.poll(() => frames.some(frame => frame.topic === 'responder/pose' && xyz((frame.data as { pos?: unknown } | null)?.pos) != null),
    { timeout: 10_000 }).toBe(true);

  await expect(page.locator('#map-canvas')).toBeVisible();
  await expect.poll(() => page.evaluate(() => {
    type Obj = {
      isMesh?: boolean; visible?: boolean; parent?: unknown;
      userData?: { label?: string };
      traverse?: (fn: (obj: Obj) => void) => void;
    };
    const map = (window as unknown as {
      aftershockMap?: { scoutGroup: Obj; responderGroup: Obj; renderer: { info: { render: { frame: number } } } };
    }).aftershockMap;
    if (!map) return { scout: false, responder: false, drawing: false };
    const shown = (group: Obj, name: string) => {
      let meshes = 0;
      let labelled = false;
      group.traverse?.(obj => {
        if (obj.isMesh && obj.visible) meshes += 1;
        if (typeof obj.userData?.label === 'string' && obj.userData.label.includes(name)) labelled = true;
      });
      return meshes > 0 && labelled && group.parent != null;
    };
    return {
      scout: shown(map.scoutGroup, 'Scout'),
      responder: shown(map.responderGroup, 'Responder'),
      drawing: map.renderer.info.render.frame > 0,
    };
  }), { timeout: 15_000 }).toEqual({ scout: true, responder: true, drawing: true });

  await expect.poll(() => scoutTravel(frames, connectedAt, connectedAt + POSE_WINDOW_MS), {
    timeout: Math.max(1_000, connectedAt + POSE_WINDOW_MS - Date.now() + 500),
    message: 'Scout camera pose (map/points.points_from) did not move within 10 s',
  }).toBeGreaterThan(MOVE_M);
});
