// Shared Playwright `test` for every spec: same as @playwright/test, with
// Google Fonts served from a local cache (see fonts.ts).
import { test as base } from "@playwright/test";
import { routeGoogleFonts } from "./fonts";

export { expect } from "@playwright/test";
export type { Page, TestInfo } from "@playwright/test";

export const test = base.extend({
  context: async ({ context }, use) => {
    await routeGoogleFonts(context);
    await use(context);
  },
});
