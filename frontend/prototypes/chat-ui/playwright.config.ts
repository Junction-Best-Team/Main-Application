import { defineConfig } from "@playwright/test";

// Runs against the standalone prototype dev server (fake in-memory backend).
// PW_PORT lets parallel checkouts run suites without sharing a dev server.
const port = Number(process.env.PW_PORT ?? 5183);
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  // Warms the dev server and the Google Fonts cache before the first test.
  globalSetup: "./e2e/global-setup.ts",
  workers: 1,
  reporter: "list",
  outputDir: "test-results",
  use: { baseURL },
  webServer: {
    command: `npm run dev -- --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: true,
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
});
