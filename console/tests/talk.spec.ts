import { test, expect } from '@playwright/test';

// CONSOLE-TALK: the casualty talk panel shows say -> casualty, casualty/reply, the facts heard
// (casualty/contact) and gate asks with their answers, from live hub messages.
test('casualty talk panel shows the dialogue, facts heard and gate asks', async ({ page }) => {
  let socket: any;
  const sent: any[] = [];
  await page.routeWebSocket('ws://localhost:8000/ws', ws => {
    socket = ws;
    ws.onMessage(raw => sent.push(JSON.parse(String(raw))));
  });
  await page.goto('/');
  await expect(page.locator('#connection-status')).toHaveText('Hub connected');
  const panel = page.locator('#talk-panel');
  await expect(panel).toContainText('No casualty contact yet');
  const send = (topic: string, data: unknown) => socket.send(JSON.stringify({ topic, data }));

  send('casualty/contact', { id: 'c1', t: 30.0, status: 'talking', turns: 1, max_turns: 8,
    facts: { responsive: null, hurt: [], bleeding: null }, injuries: [], receipts: [] });
  send('say', { to: 'casualty', intent: 'reassure', text: 'Hello, I am a rescue robot. Can you hear me?', lang: 'auto' });
  send('casualty/reply', { id: 'c1', t: 31.2, text: 'Yes, my leg hurts', source: 'sim', level: 0.6 });
  send('casualty/contact', { id: 'c1', t: 33.0, status: 'talking', turns: 2, max_turns: 8,
    facts: { responsive: true, hurt: ['leg'], bleeding: false }, injuries: ['leg hurts, may be broken'], receipts: [] });
  send('gate/request', { id: 'g7', kind: 'risky_move', route: 'r3', summary: 'Drive past the leaning slab to c1' });

  const lines = panel.locator('.talk-line');
  await expect(lines).toHaveCount(3);
  await expect(lines.nth(0)).toHaveClass(/robot/);
  await expect(lines.nth(0)).toContainText('Robot → c1');
  await expect(lines.nth(0)).toContainText('reassure');
  await expect(lines.nth(0)).toContainText('Can you hear me?');
  await expect(lines.nth(1)).toHaveClass(/casualty/);
  await expect(lines.nth(1)).toContainText('31.2s · c1 → robot');
  await expect(lines.nth(1)).toContainText('Yes, my leg hurts');
  await expect(lines.nth(1).getByRole('meter', { name: 'Voice level' })).toHaveAttribute('aria-valuenow', '0.6');
  await expect(lines.nth(2)).toHaveClass(/ask/);
  await expect(lines.nth(2)).toContainText('g7 · risky move · route r3');
  await expect(lines.nth(2)).toContainText('pending');
  await expect(panel.locator('.talk-empty')).toBeHidden();

  const chip = panel.locator('.talk-contact[data-casualty="c1"]');
  await expect(chip).toContainText('talking');
  await expect(chip).toContainText('turn 2/8');
  const facts = panel.getByLabel('Facts heard from c1');
  await expect(facts).toContainText('Responsive');
  await expect(facts.locator('dd').nth(0)).toHaveText('yes');
  await expect(facts).toContainText('leg hurts, may be broken');
  await expect(facts.locator('dt', { hasText: 'Bleeding' })).toBeVisible();

  // Answering the ask in the approval dialog marks it in the transcript.
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect.poll(() => sent).toContainEqual({ topic: 'gate/answer', data: { id: 'g7', approved: true, by: 'operator' } });
  send('gate/answer', { id: 'g7', approved: true, by: 'operator' });
  await expect(lines.nth(2)).toHaveClass(/approved/);
  await expect(lines.nth(2)).toContainText('approved by operator');

  send('casualty/contact', { id: 'c1', t: 60.0, status: 'done', turns: 4, max_turns: 8,
    facts: { responsive: true, hurt: ['leg'], bleeding: false }, injuries: [], receipts: [] });
  await expect(chip).toContainText('done');
});

test('casualty talk never renders message text as HTML', async ({ page }) => {
  let socket: any;
  await page.routeWebSocket('ws://localhost:8000/ws', ws => { socket = ws; });
  await page.goto('/');
  await expect(page.locator('#connection-status')).toHaveText('Hub connected');
  socket.send(JSON.stringify({ topic: 'casualty/reply',
    data: { id: 'c2', t: 5, text: '<img src=x onerror="window.__talkXss=1">help', source: 'sim' } }));
  const line = page.locator('#talk-panel .talk-line');
  await expect(line).toContainText('<img src=x');
  await expect(page.locator('#talk-panel img')).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).__talkXss)).toBeUndefined();
});
