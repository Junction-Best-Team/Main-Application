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
  page.screenshot({
    path: `test-results/screens/${info.project.name}-${name}.png`,
    fullPage: true,
    animations: "disabled",
  });

async function openRequest(page: Page, info: TestInfo) {
  await signIn(page, "/");
  await (await mainNav(page, info)).getByRole("link", { name: "Request" }).click();
  await expect(page).toHaveURL(/\/request$/);
}

test("request screen shows the assistant header, context header and quota badge", async ({ page }, info) => {
  await openRequest(page, info);
  await expect(page.getByRole("heading", { level: 1, name: "Aimo Kitchen Assistant" })).toBeVisible();
  await expect(page.getByText(/Service Context/)).toBeVisible();
  const quota = page.getByText(/Account Quota Active/);
  await expect(quota).toBeVisible();
  await shot(page, info, "request-empty");
});

test("composer has a Send Order Request button and inert attach, voice and barcode icons", async ({ page }, info) => {
  await openRequest(page, info);
  await expect(page.getByRole("textbox", { name: /request/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send Order Request" })).toBeDisabled(); // nothing typed yet
  for (const name of ["Attach file", "Voice input", "Scan barcode"]) {
    const control = page.getByRole("button", { name });
    await expect(control).toBeVisible();
    await expect(control).toBeDisabled();
    await control.click({ force: true });
  }
  await expect(page).toHaveURL(/\/request$/);
});

test("sending a message shows it in the thread and the assistant reply renders", async ({ page }, info) => {
  await openRequest(page, info);
  await page.getByRole("textbox", { name: /request/i }).fill("What do I need for a brunch for 40 people?");
  await page.getByRole("button", { name: "Send Order Request" }).click();

  const thread = page.getByRole("log", { name: "Conversation messages" });
  await expect(thread.getByText("What do I need for a brunch for 40 people?")).toBeVisible();
  await expect(thread.getByText(/Could you tell me the meal, portion count/)).toBeVisible();
  await expect(page).toHaveURL(/\/conversations\/conv-/);
  await expect(page.getByRole("textbox", { name: /request/i })).toHaveValue("");
  await shot(page, info, "request-thread");
});

test("a proposal in the thread renders SKU cards with quantity and prices excl. and incl. VAT", async ({ page }, info) => {
  await signIn(page, "/conversations/conv-carbonara");
  const cards = page.getByRole("list", { name: "Proposed items" });
  await expect(cards.getByRole("listitem")).toHaveCount(5);

  // Spaghetti 1kg: 22 kg, gross 41.80 with 3.99 VAT -> 37.81 excl. VAT.
  const spaghetti = cards.getByRole("listitem").filter({ hasText: "Spaghetti 1kg" });
  await expect(spaghetti.getByText("SKU P-1001")).toBeVisible();
  await expect(spaghetti.getByText("22 kg")).toBeVisible();
  await expect(spaghetti.getByText("€37.81")).toBeVisible();
  await expect(spaghetti.getByText("€41.80")).toBeVisible();
  await expect(spaghetti.getByText(/excl\. VAT/)).toBeVisible();
  await expect(spaghetti.getByText(/incl\. VAT/)).toBeVisible();

  // The link to the full purchasing checks stays; the thread has no decision buttons.
  await expect(page.getByRole("link", { name: "Review basket and purchasing checks" })).toBeVisible();
  await expect(page.getByRole("button", { name: /confirm this purchase/i })).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  await shot(page, info, "request-sku-cards");
});

test("existing conversations stay reachable from the request screen", async ({ page }, info) => {
  await openRequest(page, info);
  const conversations = page.getByRole("navigation", { name: "Conversations" });
  await conversations.getByRole("link", { name: "Weekly oat milk restock" }).click();
  await expect(page).toHaveURL(/\/conversations\/conv-oat-restock$/);
  await expect(page.getByRole("log", { name: "Conversation messages" }).getByText(/usual oat products/)).toBeVisible();
});

test("the conversation leaves a labelled region for the Overview panel", async ({ page }, info) => {
  await signIn(page, "/conversations/conv-carbonara");
  await expect(page.getByTestId("overview-slot")).toBeAttached();
  if (!isMobile(info)) {
    const box = await page.getByRole("log", { name: "Conversation messages" }).boundingBox();
    expect(box!.width).toBeLessThan(1000); // column, not the full 1440 viewport
  }
});
