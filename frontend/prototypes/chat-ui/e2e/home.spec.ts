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
  page.screenshot({ path: `test-results/screens/${info.project.name}-${name}.png`, fullPage: true, animations: "disabled" });

const recent = (page: Page) => page.getByRole("region", { name: "Recent Past Orders" });

test("shows a welcome heading and the order banner", async ({ page }, info) => {
  await signIn(page, "/");
  await expect(page.getByRole("heading", { level: 1, name: /^Welcome/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Make a New Order in Seconds" })).toBeVisible();
  await expect(recent(page).getByRole("link", { name: /REQ-PREV-0017/ })).toBeVisible();
  await shot(page, info, "home");
});

test("Start Restock Request goes to /request", async ({ page }) => {
  await signIn(page, "/");
  await page.getByRole("link", { name: "Start Restock Request" }).click();
  await expect(page).toHaveURL(/\/request$/);
  await expect(page.getByRole("heading", { name: "Aimo Kitchen Assistant" })).toBeVisible();
});

test("Recent Past Orders lists accepted orders only, each linking to its purchase", async ({ page }) => {
  await signIn(page, "/");
  const section = recent(page);
  const rows = section.getByRole("link").filter({ hasText: "REQ-" });
  await expect(rows).toHaveCount(1);
  const row = rows.first();
  await expect(row).toContainText("REQ-PREV-0017");
  await expect(row).toContainText("2 items");
  await expect(row).toContainText("€239.80");
  await expect(row).toHaveAttribute("href", "/purchases/prop-done");
  for (const id of ["REQ-CARB-200", "REQ-OAT-RESTOCK", "REQ-PREV-0022"]) {
    await expect(page.getByText(id)).toHaveCount(0);
  }
  await row.click();
  await expect(page).toHaveURL(/\/purchases\/prop-done$/);
  await expect(page.getByRole("button", { name: "Order details: REQ-PREV-0017" })).toHaveAttribute("aria-expanded", "true");
});

test("View All Past Orders goes to /purchases", async ({ page }) => {
  await signIn(page, "/");
  await page.getByRole("link", { name: "View All Past Orders" }).click();
  await expect(page).toHaveURL(/\/purchases$/);
});

test("with many proposals, only the latest few accepted orders show", async ({ page }, info) => {
  await signIn(page, "/request");
  await page.getByLabel("Scenario").selectOption({ label: "Many past orders (paged)" });
  await (await mainNav(page, info)).getByRole("link", { name: "Home" }).click();
  const rows = recent(page).getByRole("link").filter({ hasText: "REQ-" });
  await expect(rows).toHaveCount(3);
  await expect(page.getByText("REQ-REJ-")).toHaveCount(0);
  await expect(page.getByText("Loading past orders")).toHaveCount(0);
  await shot(page, info, "home-many-orders");
});

test("the Active Delivery Schedule card is shown from MOCK content and does nothing", async ({ page }) => {
  await signIn(page, "/");
  const card = page.getByRole("region", { name: "Active Delivery Schedule" });
  await expect(card).toBeVisible();
  await expect(card.getByText("Fresh Dairy & Morning Bakery Cadence")).toBeVisible();
  await expect(card.getByRole("link")).toHaveCount(0);
  const buttons = card.getByRole("button");
  await expect(buttons.first()).toBeDisabled();
  const url = page.url();
  await buttons.first().click({ force: true });
  expect(page.url()).toBe(url);
});
