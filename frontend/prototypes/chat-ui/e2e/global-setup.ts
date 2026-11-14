import { chromium, type FullConfig } from "@playwright/test";
import { routeGoogleFonts } from "./fonts";

// Runs once after the dev server is up: loads the app so Vite has transformed
// and pre-bundled everything, and fills the Google Fonts cache, before the
// first timed test.
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL!;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    await routeGoogleFonts(context);
    const page = await context.newPage();
    await page.goto(baseURL, { timeout: 60_000 });
    await page.getByLabel("Username").waitFor({ timeout: 60_000 });
    await page.evaluate(async () => {
      // Material Symbols subsets load lazily; use a glyph so they are fetched and cached.
      const probe = document.createElement("span");
      probe.className = "material-symbols-outlined";
      probe.textContent = "dashboard";
      document.body.append(probe);
      await document.fonts.ready;
    });
  } finally {
    await browser.close();
  }
}
