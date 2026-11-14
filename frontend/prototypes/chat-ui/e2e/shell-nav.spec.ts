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
  await expect(page.getByRole("log", { name: "Conversation messages" }).getByText(/carbonara/).first()).toBeVisible();
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
  await expect(sidebar.getByRole("link", { name: "200 portions of carbonara" })).toBeVisible();
  await shot(page, info, "-scrolled");
});

test("conversations are listed under Request and the current one follows navigation", async ({ page }, info) => {
  await signIn(page, "/");
  let nav = await mainNav(page, info);
  const list = nav.getByRole("list", { name: "Conversations" });
  for (const title of ["200 portions of carbonara", "Weekly oat milk restock"]) {
    await expect(list.getByRole("link", { name: title })).toBeVisible();
  }
  await list.getByRole("link", { name: "Weekly oat milk restock" }).click();
  await expect(page).toHaveURL(/\/conversations\/conv-oat-restock$/);
  await expect(page.getByRole("log", { name: "Conversation messages" }).getByText(/usual oat products/)).toBeVisible();
  if (isMobile(info)) await expect(page.getByRole("dialog", { name: "Menu" })).toBeHidden();

  nav = await mainNav(page, info);
  await expect(list.getByRole("link", { name: "Weekly oat milk restock" })).toHaveAttribute("aria-current", "page");
  await shot(page, info, "");
  await list.getByRole("link", { name: "200 portions of carbonara" }).click();
  await expect(page).toHaveURL(/\/conversations\/conv-carbonara$/);
  nav = await mainNav(page, info);
  await expect(list.getByRole("link", { name: "200 portions of carbonara" })).toHaveAttribute("aria-current", "page");
  await expect(list.getByRole("link", { name: "Weekly oat milk restock" })).not.toHaveAttribute("aria-current");
  // Request itself still starts a new request.
  await nav.getByRole("link", { name: "Request", exact: true }).click();
  await expect(page).toHaveURL(/\/request$/);
  await expect(list.locator('[aria-current="page"]')).toHaveCount(0);
});

test("the conversation list under Request collapses and expands", async ({ page }, info) => {
  await signIn(page, "/");
  const nav = await mainNav(page, info);
  const list = nav.getByRole("list", { name: "Conversations" });
  const hide = nav.getByRole("button", { name: "Hide conversations" });
  await expect(hide).toHaveAttribute("aria-expanded", "true");
  await expect(list).toBeVisible();

  await hide.click();
  await expect(list).toBeHidden();
  const show = nav.getByRole("button", { name: "Show conversations" });
  await expect(show).toHaveAttribute("aria-expanded", "false");
  // Collapsed, the nav is just Home, Request and Past Orders.
  const links = nav.getByRole("link");
  await expect(links).toHaveCount(3);
  for (const [i, name] of ["Home", "Request", "Past Orders"].entries()) {
    await expect(links.nth(i)).toHaveAccessibleName(name);
  }
  await shot(page, info, "-collapsed");

  await show.click();
  await expect(list.getByRole("link", { name: "200 portions of carbonara" })).toBeVisible();
});

test("a new conversation appears under Request after its first message", async ({ page }, info) => {
  await signIn(page, "/");
  await (await mainNav(page, info)).getByRole("link", { name: "Request", exact: true }).click();
  await expect(page).toHaveURL(/\/request$/);
  await page.getByRole("textbox", { name: /request/i }).fill("Coffee beans for the staff room");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(page).toHaveURL(/\/conversations\/conv-\d+$/);

  const nav = await mainNav(page, info);
  const item = nav.getByRole("list", { name: "Conversations" }).getByRole("link", { name: "Coffee beans for the staff room" });
  await expect(item).toBeVisible();
  await expect(item).toHaveAttribute("aria-current", "page");
});
