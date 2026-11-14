import { expect, test, type Page, type TestInfo } from "./test";

async function signIn(page: Page, path: string) {
  await page.goto(path);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password").fill("pw");
  await page.getByRole("button", { name: "Sign in" }).click();
}

const isMobile = (info: TestInfo) => info.project.name === "mobile";

// Returns the main navigation, opening the mobile menu first when needed.
async function mainNav(page: Page, info: TestInfo) {
  if (isMobile(info)) await page.getByRole("button", { name: "Open menu" }).click();
  return page.getByRole("navigation", { name: "Main navigation" });
}

test("navigation offers Home, Request and Past Orders, and no Schedule", async ({ page }, info) => {
  await signIn(page, "/");
  const nav = await mainNav(page, info);
  // Top-level items only: collapse the conversation sub-list under Request.
  await nav.getByRole("button", { name: "Hide conversations" }).click();
  const links = nav.getByRole("link");
  await expect(links).toHaveCount(3);
  for (const [i, name] of ["Home", "Request", "Past Orders"].entries()) {
    await expect(links.nth(i)).toHaveAccessibleName(name);
  }
  await expect(page.getByRole("link", { name: /schedule/i })).toHaveCount(0);
});

test("each route marks its nav item as the current page", async ({ page }, info) => {
  // The fake store is in memory (a reload signs out), so deep links sign in at
  // the path and /request is reached through the nav.
  const expectCurrent = async (current: string) =>
    expect((await mainNav(page, info)).locator('[aria-current="page"]')).toHaveAccessibleName(current);

  await signIn(page, "/");
  await expectCurrent("Home");
  await page.getByRole("link", { name: "Request", exact: true }).click();
  await expect(page).toHaveURL(/\/request$/);
  await expectCurrent("Request");

  // Inside a conversation, the conversation is the page and Request the current section.
  await signIn(page, "/conversations/conv-carbonara");
  const nav = await mainNav(page, info);
  await expect(nav.locator('[aria-current="page"]')).toHaveAccessibleName("200 portions of carbonara");
  await expect(nav.getByRole("link", { name: "Request", exact: true })).toHaveAttribute("aria-current", "true");

  for (const [path, current] of [
    ["/purchases", "Past Orders"],
    ["/purchases/prop-ready", "Past Orders"],
  ] as const) {
    await signIn(page, path);
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expectCurrent(current);
  }
});

test("navigating moves between Home, the chat at /request and Past Orders", async ({ page }, info) => {
  await signIn(page, "/");
  await (await mainNav(page, info)).getByRole("link", { name: "Request" }).click();
  await expect(page).toHaveURL(/\/request$/);
  await expect(page.getByRole("textbox", { name: /message|ingredient|request/i }).first()).toBeVisible();
  await (await mainNav(page, info)).getByRole("link", { name: "Past Orders" }).click();
  await expect(page).toHaveURL(/\/purchases$/);
  await (await mainNav(page, info)).getByRole("link", { name: "Home" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Welcome" })).toBeVisible();
});


test("sidebar on desktop, top bar with a menu below 768px", async ({ page }, info) => {
  await signIn(page, "/");
  const sidebar = page.getByRole("complementary", { name: "Sidebar" });
  const menuButton = page.getByRole("button", { name: "Open menu" });
  if (!isMobile(info)) {
    await expect(sidebar).toBeVisible();
    await expect(menuButton).toBeHidden();
  } else {
    await expect(sidebar).toBeHidden();
    await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeHidden();
    await menuButton.click();
    const menu = page.getByRole("dialog", { name: "Menu" });
    await expect(menu.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
    await page.screenshot({ path: `test-results/screens/${info.project.name}-menu-open.png`, fullPage: true, animations: "disabled" });
    await menu.getByRole("button", { name: "Close menu" }).click();
    await expect(menu).toBeHidden();
  }
  // The same viewport switches layout once it crosses the 768px breakpoint.
  await page.setViewportSize({ width: isMobile(info) ? 768 : 767, height: 900 });
  await expect(sidebar).toBeVisible({ visible: isMobile(info) });
  await expect(menuButton).toBeVisible({ visible: !isMobile(info) });
});

test("shell placeholders render but are inert and announced as unavailable", async ({ page }, info) => {
  await signIn(page, "/");
  const expectInert = async (names: string[]) => {
    for (const name of names) {
      const control = page.getByRole(name === "Search products" ? "searchbox" : "button", { name });
      await expect(control).toBeVisible();
      await expect(control).toBeDisabled();
      await control.click({ force: true });
    }
  };
  // Top bar / header placeholders.
  await expectInert(isMobile(info) ? ["Notifications"] : ["Search products", "Notifications", "Help"]);
  // Sidebar (desktop) or menu (mobile) placeholders.
  if (isMobile(info)) await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByText("Hub: Helsinki Sörnäinen").filter({ visible: true })).toBeVisible();
  await expectInert(["Switch account", "Account Settings"]);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Welcome" })).toBeVisible();
});

test("the mock notice bar is on every screen, including sign-in", async ({ page }, info) => {
  const notice = page.getByRole("note").filter({ hasText: /mock data/i });
  const shot = (name: string) =>
    page.screenshot({ path: `test-results/screens/${info.project.name}-${name}.png`, fullPage: true, animations: "disabled" });

  await page.goto("/login");
  await expect(notice).toBeVisible();

  await signIn(page, "/");
  await expect(page.getByRole("heading", { level: 1, name: "Welcome" })).toBeVisible();
  await expect(notice).toBeVisible();
  await shot("shell-home");

  await (await mainNav(page, info)).getByRole("link", { name: "Request" }).click();
  await expect(page).toHaveURL(/\/request$/);
  await expect(notice).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot("shell-request");

  await (await mainNav(page, info)).getByRole("link", { name: "Past Orders" }).click();
  await expect(page).toHaveURL(/\/purchases$/);
  await expect(notice).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot("shell-past-orders");
});
