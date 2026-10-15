import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "./", // served from a GitHub Pages sub-path
  build: { target: "es2022" },
  // the e2e fake loads the committed vectors from ../protocol (dev server only)
  server: { fs: { allow: [".."] } },
  test: { include: ["test/**/*.test.ts"] },
});
