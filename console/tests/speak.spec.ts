import { test, expect } from '@playwright/test';

// BROWSER-VOICE: robot `say` lines are spoken with the browser's speechSynthesis (no Gemini), the
// talk panel has a mute button, muting cancels speech and is remembered across reloads.

async function stubSpeech(page: import('@playwright/test').Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as any;
    w.__spoken = [];
    w.__cancels = 0;
    w.SpeechSynthesisUtterance = class { text: string; lang = ''; constructor(text: string) { this.text = text; } };
    Object.defineProperty(w, 'speechSynthesis', { configurable: true, value: {
      speak: (u: { text: string; lang: string }) => w.__spoken.push({ text: u.text, lang: u.lang }),
      cancel: () => { w.__cancels += 1; },
    } });
  });
}

async function connect(page: import('@playwright/test').Page) {
  let socket: any;
  await page.routeWebSocket('ws://localhost:8000/ws', ws => { socket = ws; });
  await page.goto('/');
  await expect(page.locator('#connection-status')).toHaveText('Hub connected');
  return (topic: string, data: unknown) => socket.send(JSON.stringify({ topic, data }));
}

const spoken = (page: import('@playwright/test').Page) => page.evaluate(() => (window as any).__spoken);

test('say lines are spoken, and the mute button silences them across a reload', async ({ page }) => {
  test.setTimeout(60_000);                       // two page loads
  await stubSpeech(page);
  const send = await connect(page);
  const voice = page.locator('#talk-panel').getByRole('button', { name: 'Mute robot voice' });
  await expect(voice).toHaveAttribute('aria-pressed', 'false');
  await expect(voice).toHaveText('Voice on');

  send('say', { to: 'casualty', intent: 'reassure', text: 'Hello, I am a rescue robot.', lang: 'auto' });
  send('say', { to: 'casualty', intent: 'ask', text: '¿Puede oírme?', lang: 'es' });
  send('say', { to: 'casualty', text: '   ' });
  await expect(page.locator('#talk-panel .talk-line')).toHaveCount(3);
  await expect.poll(() => spoken(page)).toEqual([
    { text: 'Hello, I am a rescue robot.', lang: '' },
    { text: '¿Puede oírme?', lang: 'es' },
  ]);

  await voice.click();
  await expect(voice).toHaveAttribute('aria-pressed', 'true');
  await expect(voice).toHaveText('Voice off');
  expect(await page.evaluate(() => (window as any).__cancels)).toBe(1);
  send('say', { to: 'casualty', text: 'Help is coming.' });
  await expect(page.locator('#talk-panel .talk-line')).toHaveCount(4);
  expect(await spoken(page)).toHaveLength(2);

  // Muted stays muted after a reload.
  await page.reload();
  await expect(page.locator('#connection-status')).toHaveText('Hub connected');
  await expect(page.locator('#talk-panel').getByRole('button', { name: 'Mute robot voice' }))
    .toHaveAttribute('aria-pressed', 'true');
});

test('without speechSynthesis the voice button says so and nothing breaks', async ({ page }) => {
  await page.addInitScript(() => { delete (window as any).speechSynthesis; });
  const send = await connect(page);
  const voice = page.locator('#talk-panel').getByRole('button', { name: 'Mute robot voice' });
  await expect(voice).toBeDisabled();
  await expect(voice).toHaveText('Voice unavailable');
  send('say', { to: 'casualty', text: 'Hello?' });
  await expect(page.locator('#talk-panel .talk-line')).toContainText('Hello?');
});
