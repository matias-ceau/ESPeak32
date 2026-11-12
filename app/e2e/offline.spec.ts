import { expect, test } from "@playwright/test";

// Runs against the production build (the service worker is only registered there), served by `vite preview`.
test.use({ baseURL: "http://localhost:5175/" });

test("after one online visit the app opens offline", async ({ page, context }) => {
  await page.goto("./");
  await expect(page.locator("h1")).toHaveText("ESPeak32");
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await context.setOffline(true);
  await page.reload();
  await expect(page.locator("h1")).toHaveText("ESPeak32");
  await expect(page.locator("#sync")).toBeVisible();
});
