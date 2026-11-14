import { expect, test, type Page } from "./test";

async function signIn(page: Page, path: string) {
  await page.goto(path);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password").fill("pw");
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function expectNoHorizontalOverflow(page: Page) {
  const { scrollWidth, viewport } = await page.evaluate(() => ({
    scrollWidth: document.scrollingElement!.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(viewport);
}

const screens = [
  { name: "Request (new)", path: "/request", ready: { role: "heading", name: "Aimo Kitchen Assistant" } },
  { name: "Request (conversation)", path: "/conversations/conv-carbonara", ready: { role: "heading", name: "Overview" } },
  { name: "Past Orders", path: "/purchases", ready: { role: "heading", name: "Past Orders" } },
  { name: "Home", path: "/", ready: { role: "heading", name: "Welcome" } },
] as const;

for (const screen of screens) {
  test(`${screen.name} has no horizontal page scroll`, async ({ page }) => {
    await signIn(page, screen.path);
    await expect(page.getByRole(screen.ready.role, { name: screen.ready.name }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoHorizontalOverflow(page);
  });
}
