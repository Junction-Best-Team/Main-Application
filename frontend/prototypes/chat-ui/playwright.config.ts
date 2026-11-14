import { defineConfig } from "@playwright/test";

// Runs against the standalone prototype dev server (fake in-memory backend).
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  reporter: "list",
  outputDir: "test-results",
  use: { baseURL: "http://127.0.0.1:5183" },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5183",
    reuseExistingServer: true,
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
});
