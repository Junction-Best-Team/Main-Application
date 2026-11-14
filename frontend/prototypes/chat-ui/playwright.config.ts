import { defineConfig } from "@playwright/test";

// Runs against the standalone prototype dev server (fake in-memory backend).
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  reporter: "list",
  outputDir: "test-results",
  use: { baseURL: "http://127.0.0.1:5283", viewport: { width: 1440, height: 1000 } },
  webServer: {
    command: "npm run dev -- --port 5283 --strictPort",
    url: "http://127.0.0.1:5283",
    reuseExistingServer: false,
  },
});
