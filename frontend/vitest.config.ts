// Component tests that check the UI loads and behaves correctly (jsdom, no browser, no server).
// They are the safety net for the upcoming UI design work: see the note in tests/chat.test.tsx.
import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
      include: ["tests/**/*.test.tsx"],
      css: false,
      coverage: {
        provider: "v8",
        include: ["src/main.tsx"],
        reporter: ["text", "json-summary", "lcov"],
        reportsDirectory: "coverage",
        // A floor, not a target: measured 2026-11-14 at 82.6% lines, 78.5% statements, 76.1%
        // functions, 71.4% branches. Raise it as tests are added; the Python gate is 95%.
        thresholds: { lines: 80, statements: 75, functions: 72, branches: 68 },
      },
    },
  }),
);
