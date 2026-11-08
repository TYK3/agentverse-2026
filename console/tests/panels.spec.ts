import { test, expect } from '@playwright/test';

test('fixture panels update and approvals are queued', async ({ page }) => {
  const outgoing: string[] = [];
  page.on('console', msg => { if (msg.text().startsWith('[bus fake outgoing]')) outgoing.push(msg.text()); });
  await page.goto('/?fake=1');
  await expect(page.locator('#budget-panel')).toContainText('OVER LIMIT', { timeout: 10000 });
  await expect(page.locator('#gemini-status')).toHaveAttribute('title', /planner, tts/);
  await expect(page.locator('#reasoning-log')).toContainText('rescan before acting');
  await expect(page.locator('#confidence-panel progress')).toHaveAttribute('value', '0.6');
  await expect(page.locator('#approval-meta')).toContainText('g4');
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.locator('#approval-meta')).toContainText('demo-gate-2');
  await page.getByRole('button', { name: 'Reject', exact: true }).click();
  expect(outgoing.some(x => x.includes('"id":"g4","approved":true,"by":"operator"'))).toBeTruthy();
  expect(outgoing.some(x => x.includes('"id":"demo-gate-2","approved":false'))).toBeTruthy();
  await page.getByRole('button', { name: 'Handover report' }).click();
  await expect(page.locator('#report-content h1')).toHaveText('Demo handover');
  await expect(page.locator('#report-content')).toContainText('SIMULATED');
  await expect(page.locator('#report-content')).toContainText('ESTIMATE');
});

test('live socket emits exact messages and retains failed approval', async ({ page }) => {
  const messages: any[] = [];
  let socket: any;
  await page.routeWebSocket('ws://localhost:8000/ws', ws => {
    socket = ws;
    ws.onMessage(raw => messages.push(JSON.parse(String(raw))));
  });
  await page.goto('/');
  await expect(page.locator('#connection-status')).toHaveText('Hub connected');
  socket.send(JSON.stringify({ topic: 'status/link', data: { online: true } }));
  await expect(page.locator('#link-status')).toHaveText('Online');
  await page.keyboard.press('o');
  await expect.poll(() => messages).toContainEqual({ topic: 'status/link', data: { online: false } });
  await page.locator('#operator-command').fill('send water');
  await page.locator('#operator-command').press('Enter');
  await expect.poll(() => messages).toContainEqual({ topic: 'operator/command', data: { text: 'send water', source: 'typed' } });
  socket.send(JSON.stringify({ topic: 'gate/request', data: { id: 'g-live', kind: 'risky_move', route: 'r3', summary: 'Move rubble' } }));
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect.poll(() => messages).toContainEqual({ topic: 'gate/answer', data: { id: 'g-live', approved: true, by: 'operator' } });
  socket.send(JSON.stringify({ topic: 'gate/request', data: { id: 'g-disconnected', kind: 'risky_move', summary: 'Wait' } }));
  await expect(page.locator('#approval-meta')).toContainText('g-disconnected');
  socket.close();
  await expect(page.locator('#connection-status')).toContainText('disconnected');
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.locator('#approval-dialog')).toBeVisible();
  await expect(page.locator('#approval-error')).toContainText('Not sent');
});
