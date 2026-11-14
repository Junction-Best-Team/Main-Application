import { expect, test, type Page, type TestInfo } from "@playwright/test";

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
  page.screenshot({ path: `test-results/screens/${info.project.name}-${name}.png`, fullPage: true, animations: "disabled" });

const orderToggles = (page: Page) => page.getByRole("button", { name: /^Order details:/ });

test("lists only accepted orders, with an Accepted (demo) badge and totals", async ({ page }, info) => {
  await signIn(page, "/purchases");
  await expect(page.getByRole("heading", { level: 1, name: "Past Orders" })).toBeVisible();
  await expect(orderToggles(page)).toHaveCount(1);
  const row = page.getByRole("article").filter({ hasText: "REQ-PREV-0017" });
  await expect(row).toBeVisible();
  await expect(row.getByText("Accepted (demo)")).toBeVisible();
  await expect(row.getByText("2 items")).toBeVisible();
  await expect(row.getByText("€239.80")).toBeVisible();
  await expect(row.getByText(/€215\.81 excl\. VAT/)).toBeVisible();
  for (const id of ["REQ-CARB-200", "REQ-OAT-RESTOCK", "REQ-PREV-0022", "REQ-PREV-0031", "REQ-PREV-0040"]) {
    await expect(page.getByText(id)).toHaveCount(0);
  }
  await expect(page.getByRole("button", { name: /confirm|reject|approve/i })).toHaveCount(0);
  await shot(page, info, "past-orders");
});

test("a row expands in place to show ordered items and collapses again", async ({ page }) => {
  await signIn(page, "/purchases");
  const toggle = orderToggles(page).first();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByText("Spaghetti 1kg")).toHaveCount(0);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("Spaghetti 1kg")).toBeVisible();
  await expect(page.getByText("Guanciale 500g")).toBeVisible();
  await toggle.click();
  await expect(page.getByText("Spaghetti 1kg")).toHaveCount(0);
});

test("keeps fetching pages until the list is filled, then offers more", async ({ page }, info) => {
  await signIn(page, "/");
  await page.getByLabel("Scenario").selectOption({ label: "Many past orders (paged)" });
  await (await mainNav(page, info)).getByRole("link", { name: "Past Orders" }).click();
  // The first API pages hold no accepted orders at all; the screen keeps paging.
  // Whole API pages are kept, so a full page of 5 can overshoot to 7.
  await expect(orderToggles(page)).toHaveCount(7);
  await shot(page, info, "past-orders-paged");
  await page.getByRole("button", { name: "Show more orders" }).click();
  await expect(orderToggles(page)).toHaveCount(8);
  await expect(page.getByRole("button", { name: "Show more orders" })).toHaveCount(0);
  await expect(page.getByText("REQ-REJ-")).toHaveCount(0);
});

test("/purchases/:id opens Past Orders with that order expanded and in view", async ({ page }, info) => {
  await signIn(page, "/purchases/prop-done");
  await expect(page).toHaveURL(/\/purchases\/prop-done$/);
  await expect(page.getByRole("heading", { level: 1, name: "Past Orders" })).toBeVisible();
  const toggle = page.getByRole("button", { name: "Order details: REQ-PREV-0017" });
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("Spaghetti 1kg")).toBeInViewport();
  await shot(page, info, "past-orders-deep-link");
});

test("/purchases/:id for a proposal that is not accepted shows the not-placed notice", async ({ page }, info) => {
  await signIn(page, "/purchases/prop-ready");
  await expect(
    page.getByText("This purchase hasn't been placed yet — confirm it in the request it came from"),
  ).toBeVisible();
  await expect(orderToggles(page).first()).toHaveAttribute("aria-expanded", "false");
  await shot(page, info, "past-orders-not-placed");
});

test("the chat's basket link lands on Past Orders", async ({ page }) => {
  await signIn(page, "/conversations/conv-carbonara");
  await page.getByRole("link", { name: "Review basket and purchasing checks" }).click();
  await expect(page).toHaveURL(/\/purchases\/prop-ready$/);
  await expect(page.getByText(/hasn't been placed yet/)).toBeVisible();
});

test("/approvals/:id redirects to the matching purchase", async ({ page }) => {
  await signIn(page, "/approvals/appr-done");
  await expect(page).toHaveURL(/\/purchases\/prop-done$/);
  await expect(page.getByRole("button", { name: "Order details: REQ-PREV-0017" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
});
