import { expect, test } from "@playwright/test";

// The fake is loaded by the page itself (Vite serves it), so it can reuse the MockDevice from the unit tests.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const fakeModule = "/e2e/fakeBluetooth.ts"; // served by the Vite dev server
    const ready = import(fakeModule);
    Object.defineProperty(navigator, "bluetooth", {
      configurable: true,
      value: {
        requestDevice: async (o: unknown) => (await ready).fake.requestDevice(o),
        getDevices: async () => (await ready).fake.getDevices(),
      },
    });
  });
});

test("sync two notes across a dropped link, list them, play one", async ({ page }) => {
  await page.goto("./");
  await page.click("#sync");
  await expect(page.locator("#status")).toContainText("Synced 2", { timeout: 15_000 });
  await expect(page.locator("#notes li")).toHaveCount(2);
  const fake = await page.evaluate(() => (window as any).__espeak32Fake.stats());
  expect(fake.notesLeft).toBe(0); // deleted after the notes were stored
  expect(fake.connections).toBe(2); // the link dropped once and the sync resumed

  await page.reload();
  await expect(page.locator("#notes li")).toHaveCount(2);
  await page.locator("#notes li .play").first().click();
  await expect(page.locator("#player")).toHaveAttribute("src", /^blob:/);
});

test("delete-after-sync off keeps the notes on the device", async ({ page }) => {
  await page.goto("./");
  await page.uncheck("#delete-after-sync");
  await page.click("#sync");
  await expect(page.locator("#status")).toContainText("Synced 2", { timeout: 15_000 });
  const fake = await page.evaluate(() => (window as any).__espeak32Fake.stats());
  expect(fake.notesLeft).toBe(2);
});
