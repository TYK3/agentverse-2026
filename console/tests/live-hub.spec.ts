import { test, expect, type Page } from '@playwright/test';

// LIVE-UI-3: the console's live controls against a REAL hub with every lane (no stubs). Opt-in:
//   GEMINI_MODE=off uvicorn coord.hub:app --port 8000     # repo root, fresh start
//   cd console && LIVE_HUB=1 npx playwright test tests/live-hub.spec.ts
// Approve / hold go out as gate/answer, Simulate Re-Plan as POST /inject aftershock and
// Trigger Slab Shift as POST /inject block_added; every effect asserted here comes back from the sim
// or planner over /ws.
test.skip(!process.env.LIVE_HUB, 'needs a running hub: set LIVE_HUB=1 (see the header)');

type Frame = { dir: 'in' | 'out'; topic: string; data: any };

async function watch(page: Page): Promise<Frame[]> {
  const frames: Frame[] = [];
  page.on('websocket', ws => {
    const add = (dir: Frame['dir']) => (f: { payload: string | Buffer }) => {
      try { const m = JSON.parse(String(f.payload)); frames.push({ dir, topic: m.topic, data: m.data }); } catch { /* not JSON */ }
    };
    ws.on('framereceived', add('in'));
    ws.on('framesent', add('out'));
  });
  return frames;
}

const after = (frames: Frame[], from: number, pred: (f: Frame) => boolean) => frames.slice(from).find(pred);

/** Approve gates without a route (triage) until a route gate is open; returns its id. */
async function nextRouteGate(page: Page): Promise<string> {
  const dialog = page.locator('#approval-dialog');
  for (let i = 0; i < 180; i++) {
    if (await dialog.evaluate(d => (d as HTMLDialogElement).open)) {
      const meta = (await page.locator('#approval-meta').textContent()) ?? '';
      if (/route r\d+/.test(meta)) return meta.split(' · ')[0];
      await page.getByRole('button', { name: 'Approve', exact: true }).click();
    }
    await page.waitForTimeout(500);
  }
  throw new Error('no route gate within 90 s');
}

/** Approve every gate the planner raises until the Responder reports moving on a route. */
async function approveUntilMoving(page: Page, frames: Frame[]): Promise<void> {
  const dialog = page.locator('#approval-dialog');
  for (let i = 0; i < 300; i++) {
    if (frames.some(f => f.topic === 'responder/pose' && f.data.state === 'moving' && f.data.route)) return;
    if (await dialog.evaluate(d => (d as HTMLDialogElement).open)) {
      await page.getByRole('button', { name: 'Approve', exact: true }).click();
    }
    await page.waitForTimeout(500);
  }
  throw new Error('the Responder never moved within 150 s');
}

test('slab shift, hold and re-plan go through the live hub and come back from the sim', async ({ page }) => {
  test.setTimeout(360_000);
  const frames = await watch(page);
  await page.goto('/');
  await expect(page.locator('#connection-status')).toHaveText('Hub connected');

  // Approve gates until the Responder is moving on a route, then Trigger Slab Shift.
  let mark: number;
  await approveUntilMoving(page, frames);
  mark = frames.length;
  await page.locator('#btn-slab-shift').click();
  await expect(page.locator('#live-control-status')).toContainText('Slab shift:', { timeout: 10_000 });
  await expect.poll(() => after(frames, mark, f => f.topic === 'world/change')?.data.kind, { timeout: 30_000 })
    .toBe('block_added');

  // Hold: Reject on the next route gate -> gate/answer approved:false -> planner logs hold.
  const gate = await nextRouteGate(page);
  mark = frames.length;
  await page.getByRole('button', { name: 'Reject', exact: true }).click();
  await expect.poll(() => after(frames, mark, f => f.dir === 'out' && f.topic === 'gate/answer')?.data)
    .toEqual({ id: gate, approved: false, by: 'operator' });
  await expect.poll(() => after(frames, mark, f => f.topic === 'log/decision' && f.data.outcome === 'hold')?.data.perception,
    { timeout: 15_000 }).toContain(gate);

  // Simulate Re-Plan: a real aftershock from the sim, then the planner re-plans.
  mark = frames.length;
  await page.locator('#btn-demo-replan').click();
  await expect.poll(() => after(frames, mark, f => f.topic === 'world/change')?.data.kind, { timeout: 30_000 })
    .toBe('aftershock');
  const moved: string[] = after(frames, mark, f => f.topic === 'world/change')!.data.moved_blocks;
  expect(moved.length).toBeGreaterThan(0);
  await expect.poll(() => after(frames, mark, f => f.topic === 'log/decision' && f.data.outcome === 'replanning') !== undefined,
    { timeout: 30_000 }).toBe(true);
  // the live re-plan, never the console's scripted b7 demo
  await expect(page.locator('#world-change-banner')).not.toContainText('avoiding collapsed block b7');
});
