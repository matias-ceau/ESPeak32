import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "./", // served from a GitHub Pages sub-path
  test: { include: ["test/**/*.test.ts"] },
});
