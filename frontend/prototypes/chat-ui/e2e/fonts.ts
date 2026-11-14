import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import type { BrowserContext, Route } from "@playwright/test";

// The app loads Hanken Grotesk, Space Grotesk and Material Symbols from Google
// Fonts. A stalled request to fonts.googleapis.com blocks the page `load`
// event (page.goto timeouts) and document.fonts.ready (screenshot timeouts).
// Tests therefore serve those files from a local disk cache, fetch them once
// with a short timeout when missing, and abort rather than hang if Google is
// unreachable, so the outside network can never stall a test.
const CACHE_DIR = fileURLToPath(new URL("../node_modules/.cache/e2e-google-fonts/", import.meta.url));
const GOOGLE_FONTS = /^https:\/\/fonts\.(googleapis|gstatic)\.com\//;

type Entry = { contentType: string };

async function serveFont(route: Route) {
  const url = route.request().url();
  const key = createHash("sha1").update(url).digest("hex");
  const bodyPath = `${CACHE_DIR}${key}.bin`;
  const metaPath = `${CACHE_DIR}${key}.json`;
  try {
    const meta = JSON.parse(await readFile(metaPath, "utf8")) as Entry;
    const body = await readFile(bodyPath);
    return await route.fulfill({
      status: 200,
      body,
      contentType: meta.contentType,
      headers: { "access-control-allow-origin": "*" },
    });
  } catch {
    /* Not cached yet. */
  }
  try {
    const response = await route.fetch({ timeout: 10_000 });
    if (response.ok()) {
      await mkdir(CACHE_DIR, { recursive: true });
      await writeFile(bodyPath, await response.body());
      await writeFile(metaPath, JSON.stringify({ contentType: response.headers()["content-type"] ?? "" }));
    }
    return await route.fulfill({ response });
  } catch {
    return await route.abort().catch(() => undefined);
  }
}

export async function routeGoogleFonts(context: BrowserContext) {
  await context.route(GOOGLE_FONTS, serveFont);
}
