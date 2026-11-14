import { expect, test, type Page, type TestInfo } from "./test";

async function signIn(page: Page, path: string) {
  await page.goto(path);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password").fill("pw");
  await page.getByRole("button", { name: "Sign in" }).click();
}

const isMobile = (info: TestInfo) => info.project.name === "mobile";

async function mainNav(page: Page, info: TestInfo) {
  if (isMobile(info)) await page.getByRole("button", { name: "Open menu" }).click();
  return page.getByRole("navigation", { name: "Main navigation" });
}

const shot = (page: Page, info: TestInfo, name: string) =>
  page.screenshot({
    path: `test-results/screens/${info.project.name}-shell-nav${name}.png`,
    fullPage: true,
    animations: "disabled",
  });

test("the desktop sidebar fills the viewport top to bottom and stays put while the page scrolls", async ({ page }, info) => {
  test.skip(isMobile(info), "Desktop sidebar only");
  await signIn(page, "/conversations/conv-carbonara");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  const sidebar = page.getByRole("complementary", { name: "Sidebar" });
  const viewport = page.viewportSize()!;

  const expectFullHeight = async () => {
    const box = (await sidebar.boundingBox())!;
    expect(Math.round(box.y)).toBe(0);
    expect(Math.round(box.height)).toBe(viewport.height);
    // Sign out (bottom of the sidebar) is always on screen.
    await expect(sidebar.getByRole("button", { name: "Sign out" })).toBeInViewport();
  };

  await expectFullHeight();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(100);
  await expectFullHeight();
  // The main content is not hidden behind the sidebar.
  const sidebarBox = (await sidebar.boundingBox())!;
  const mainBox = (await page.getByRole("main").boundingBox())!;
  expect(mainBox.x).toBeGreaterThanOrEqual(sidebarBox.x + sidebarBox.width - 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
  await shot(page, info, "-scrolled");
});
