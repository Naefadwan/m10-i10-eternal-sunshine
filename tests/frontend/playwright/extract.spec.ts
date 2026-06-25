import { test, expect } from '@playwright/test';

test('extract page renders and returns entities', async ({ page }) => {
  await page.goto("/extract");
  await page.locator("textarea").fill("Akira Kurosawa directed Seven Samurai in 1954.");
  await page.getByRole("button", { name: /Extract/i }).click();
  await expect(page.locator('[data-testid="entity-span"]').first()).toBeVisible({ timeout: 10_000 });
});

