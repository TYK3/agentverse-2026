import { test, expect } from '@playwright/test';

test('Y7c: hardware specification panel opens and displays 2-column robot specs', async ({ page }) => {
  await page.goto('/');
  const btnSpecs = page.locator('#btn-hardware-specs');
  await expect(btnSpecs).toBeVisible();

  // Dialog is initially hidden
  const dialog = page.locator('#hardware-dialog');
  await expect(dialog).not.toHaveAttribute('open');

  // Open dialog
  await btnSpecs.click();
  await expect(dialog).toHaveAttribute('open');

  // Verify header
  await expect(page.locator('#hardware-title')).toContainText('Robot Hardware Specification');

  // Verify table structure and content
  const table = page.locator('#hardware-table');
  await expect(table).toBeVisible();

  const rows = page.locator('#hardware-tbody tr');
  await expect(rows).toHaveCount(13);

  // Check key rows
  const baseRow = page.locator('#hardware-tbody tr[data-property="Base"]');
  await expect(baseRow.locator('.hw-scout')).toContainText('AgileX LIMO Pro');
  await expect(baseRow.locator('.hw-responder')).toContainText('Clearpath Jackal');

  const computeRow = page.locator('#hardware-tbody tr[data-property="Compute"]');
  await expect(computeRow.locator('.hw-scout')).toContainText('Orin Nano');
  await expect(computeRow.locator('.hw-responder')).toContainText('Orin NX 16GB');

  const armRow = page.locator('#hardware-tbody tr[data-property="Arm"]');
  await expect(armRow.locator('.hw-scout')).toContainText('none');
  await expect(armRow.locator('.hw-responder')).toContainText('Kinova Gen3 lite');

  // Check estimate badge
  const estimateBadge = page.locator('#hardware-dialog .badge-estimate');
  await expect(estimateBadge.first()).toBeVisible();

  // Close dialog via close button
  await page.locator('#btn-close-hardware').click();
  await expect(dialog).not.toHaveAttribute('open');
});
