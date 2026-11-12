import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:5174/",
    browserName: "chromium",
    // Set PW_CHROMIUM to use a system Chromium instead of Playwright's download (e.g. /usr/bin/chromium).
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  webServer: [
    { command: "npx vite --port 5174 --strictPort", url: "http://localhost:5174/", reuseExistingServer: false },
    // production build for offline.spec.ts (the service worker exists only there)
    { command: "npx vite build && npx vite preview --port 5175 --strictPort", url: "http://localhost:5175/",
      reuseExistingServer: false },
  ],
});
