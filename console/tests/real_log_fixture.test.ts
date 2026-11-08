import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parseJsonl } from '../src/replay-jsonl';
import { adaptB2Run } from '../src/replay_b2';
import { PHASES } from '../src/story-model';

// REAL-LOG-FIXTURE-TEST.
//
// Fixture: tests/fixtures/b2-seed0.jsonl. The only real run log under console/, and the
// newest: an unedited `python tools/run_b2.py` seed 0 recording (8 Nov 2026) of the
// descent L1 -> ground -> B1 -> B2. The excerpt in replay-jsonl.spec.ts and the RUN
// array in story.spec.ts are written by hand, so they are not used here.
//
// The page replays ?run= as bus envelopes ({"t","topic","data"}, story.ts via parseJsonl).
// This file is a runner log ({"t","kind",...}). replay_b2.ts adapts it. Descend B1 and
// Slab shift reach done on that adapted play, with no browser console errors. Each stage
// the log does not light is its own test.fail(): the assertion is still "reaches done",
// and the suite goes red if that stage starts passing. The raw ?run= play is the same
// kind of expected failure: parseJsonl drops every line as "missing topic".

const FIXTURE = readFileSync(fileURLToPath(new URL('./fixtures/b2-seed0.jsonl', import.meta.url)), 'utf8');

type Play = { errors: string[]; stages: Record<string, string | null> };

async function play(page: Page, name: string, body: string): Promise<Play> {
  const errors: string[] = [];
  const onError = (err: Error) => errors.push(err.message);
  const onConsole = (msg: { type(): string; text(): string }) => {
    if (msg.type() === 'error') errors.push(msg.text());
  };
  page.on('pageerror', onError);
  page.on('console', onConsole);
  try {
    await page.route(`**/runs/${name}`, route => route.fulfill({ status: 200, body, contentType: 'text/plain' }));
    await page.goto(`/?run=/runs/${name}&speed=200`);
    const badge = page.locator('#story .story-badge');
    await expect(badge).toContainText(`REPLAY ${name}`);
    await expect(badge).toContainText('end', { timeout: 60_000 });
    // Robot models load on an idle callback (assets.ts, timeout 2 s). Count errors that land after the replay.
    await page.waitForTimeout(2500);
    const stages: Record<string, string | null> = {};
    for (const phase of PHASES) {
      stages[phase.id] = await page.locator(`#story .story-phase[data-phase="${phase.id}"]`).getAttribute('data-state');
    }
    return { errors: [...errors], stages };
  } finally {
    page.off('pageerror', onError);
    page.off('console', onConsole);
  }
}

let adaptedOnce: Promise<Play> | null = null;

function adaptedPlay(page: Page): Promise<Play> {
  if (!adaptedOnce) {
    const run = adaptB2Run(FIXTURE);
    const body = run.events.map(e => JSON.stringify({ t: e.t, topic: e.topic, data: e.data })).join('\n');
    adaptedOnce = play(page, 'b2-seed0-adapted.jsonl', body);
  }
  return adaptedOnce;
}

test('adaptB2Run: Descend B1 and Slab shift reach done, with no browser console errors', async ({ page }) => {
  test.setTimeout(60_000);
  const run = adaptB2Run(FIXTURE);
  expect(run.issues).toEqual([]);
  expect(run.records).toBe(455);
  expect(run.result.levels).toEqual(['L1', 'ground', 'B1', 'B2']);
  const played = await adaptedPlay(page);
  expect(played.errors).toEqual([]);
  expect(played.stages.descend).toBe('done');
  expect(played.stages.shift).toBe('done');
});

function gap(stage: string, id: string, reason: string): void {
  test.fail(`${stage} reaches done: ${reason}`, async ({ page }) => {
    test.setTimeout(60_000);
    const played = await adaptedPlay(page);
    expect(played.stages[id]).toBe('done');
  });
}

gap('Quake', 'quake', 'no scene/loaded');
gap('Scout search', 'search', 'no scene/loaded');
gap('Casualty found', 'found', 'no casualty event');
gap('Talk', 'talk', 'no talk');
gap('Approve', 'approve', 'no gate');
gap('Deliver', 'deliver', 'no delivery');
gap('Stop + recheck', 'recheck', 'stop_and_recheck outcome does not open the chip; needs frozen or a revoked permit');
gap('Report', 'report', 'no handover');

test.fail('raw runner log not adapted', async ({ page }) => {
  test.setTimeout(60_000);
  await play(page, 'b2-seed0.jsonl', FIXTURE);
  const missing = parseJsonl(FIXTURE).issues.filter(i => i.reason === 'missing topic');
  expect(missing, 'raw ?run= drops runner lines as missing topic').toHaveLength(0);
});
