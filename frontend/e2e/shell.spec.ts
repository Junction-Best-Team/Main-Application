import { expect, test, type Page } from "@playwright/test";

// Isolated API fixtures for the navigation shell, not a production login fallback.
async function mockShell(page: Page, signedIn = true) {
  await page.route("**/api/session", (route) =>
    route.fulfill({
      status: signedIn ? 200 : 401,
      json: signedIn
        ? { username: "buyer", buyer_id: "demo-hotel", csrf_token: "test-csrf" }
        : { error: { message: "Sign in" } },
    }),
  );
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
  await page.route("**/api/purchases?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
}

test("desktop sidebar navigates between existing pages and marks the active section", async ({
  page,
}, testInfo) => {
  await mockShell(page);
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  await expect(
    navigation.getByRole("link", { name: "Request", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeHidden();
  await expect(
    page.getByRole("heading", { name: "What are we cooking?" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("shell-desktop.png"),
    fullPage: true,
  });
  await navigation
    .getByRole("link", { name: "Purchases", exact: true })
    .click();
  await expect(page).toHaveURL(/\/purchases$/);
  await expect(
    navigation.getByRole("link", { name: "Purchases", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    navigation.getByRole("link", { name: "Request", exact: true }),
  ).not.toHaveAttribute("aria-current");
  await expect(
    page.getByRole("heading", { name: "Your purchases" }),
  ).toBeVisible();
  await navigation.getByRole("link", { name: "Request", exact: true }).click();
  await expect(
    page.getByLabel("Your meal or purchasing request"),
  ).toBeVisible();
});

test("mobile drawer traps focus, closes with Escape and closes after navigation", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockShell(page);
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "Open navigation" });
  const drawer = page.getByRole("dialog", { name: "Navigation menu" });
  await trigger.click();
  await expect(drawer).toBeVisible();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(
    drawer.getByRole("button", { name: "Close navigation" }),
  ).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    drawer.getByRole("link", { name: "Valio Aimo home" }),
  ).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    drawer.getByRole("link", { name: "Purchases", exact: true }),
  ).toBeFocused();
  await page.screenshot({
    path: testInfo.outputPath("shell-mobile-drawer.png"),
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await trigger.click();
  await drawer.getByRole("link", { name: "Purchases", exact: true }).click();
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL(/\/purchases$/);
  await expect(
    page.getByRole("heading", { name: "Your purchases" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("shell-mobile.png"),
    fullPage: true,
  });
});

test("resizing to desktop dismisses the modal so the page stays usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await mockShell(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "Purchases", exact: true })
    .click();
  await expect(page).toHaveURL(/\/purchases$/);
});

test("signed-out buyers see the branded sign-in page without account navigation", async ({
  page,
}) => {
  await mockShell(page, false);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole("link", { name: "Valio Aimo home" }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Username")).toBeVisible();
});

test("the shell fits narrow phones, tablets and small desktops", async ({
  page,
}) => {
  await mockShell(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What are we cooking?" }),
  ).toBeVisible();
  for (const width of [320, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      `horizontal overflow at ${width}px`,
    ).toBe(true);
  }
});
