import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parseJsonl } from '../src/replay-jsonl';
import { adaptB2Run } from '../src/replay_b2';
import { PHASES, type PhaseState } from '../src/story-model';

// REAL-LOG-FIXTURE-TEST.
//
// Fixture: tests/fixtures/b2-seed0.jsonl. It is the only real run log under console/,
// and the newest: an unedited `python tools/run_b2.py` seed 0 recording (8 Nov 2026)
// of the descent L1 -> ground -> B1 -> B2. The excerpt in replay-jsonl.spec.ts and the
// RUN array in story.spec.ts are written by hand, so they are not used here. There is
// no separate B1-only log in this tree.
//
// The page replays ?run= as bus envelopes ({"t","topic","data"}, story.ts). This file
// is a runner log ({"t","kind",...}); replay_b2.ts is the console's adapter for it.
// Both plays go through the real screen. Every story stage must leave "pending",
// and the browser console must stay clear of errors.

const FIXTURE_URL = './fixtures/b2-seed0.jsonl';
const FIXTURE = readFileSync(fileURLToPath(new URL(FIXTURE_URL, import.meta.url)), 'utf8');
const WANTED: Record<string, PhaseState> = Object.fromEntries(PHASES.map(p => [p.id, 'done' as PhaseState]));

type Play = { errors: string[]; stages: Record<string, string | null>; card: string };

async function play(page: Page, name: string, body: string, errors: string[]): Promise<Play> {
  errors.length = 0;
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
  const card = (await page.locator('#story .story-card').innerText()).replace(/\s+/g, ' ').trim();
  return { errors: [...errors], stages, card };
}

test('the real run log replays on the console and every rescue stage renders, with no console errors', async ({ page }) => {
  test.setTimeout(90_000);
  const run = adaptB2Run(FIXTURE);
  expect(run.issues).toEqual([]);
  expect(run.records).toBe(455);
  expect(run.result.levels).toEqual(['L1', 'ground', 'B1', 'B2']);
  expect(run.result.final_level).toBe('B2');

  const parsed = parseJsonl(FIXTURE);
  const errors: string[] = [];
  page.on('pageerror', err => errors.push(err.message));
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

  const raw = await play(page, 'b2-seed0.jsonl', FIXTURE, errors);
  const adaptedBody = run.events.map(e => JSON.stringify({ t: e.t, topic: e.topic, data: e.data })).join('\n');
  const adapted = await play(page, 'b2-seed0-adapted.jsonl', adaptedBody, errors);

  expect({
    rawParse: { events: parsed.events.length, issues: parsed.issues.length, first: parsed.issues[0] ?? null },
    raw: { errors: raw.errors, stages: raw.stages },
    adapted: { errors: adapted.errors, stages: adapted.stages },
  }).toEqual({
    rawParse: { events: parsed.events.length, issues: 0, first: null },
    raw: { errors: [], stages: { ...WANTED } },
    adapted: { errors: [], stages: { ...WANTED } },
  });
});
