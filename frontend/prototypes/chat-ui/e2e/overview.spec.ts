import { expect, test, type Page, type TestInfo } from "@playwright/test";

async function signIn(page: Page, path: string) {
  await page.goto(path);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password").fill("pw");
  await page.getByRole("button", { name: "Sign in" }).click();
}

const isMobile = (info: TestInfo) => info.project.name === "mobile";

// The Overview panel is a right-hand column on desktop and an expandable
// bottom drawer on mobile; returns it expanded.
async function overview(page: Page, info: TestInfo) {
  const panel = page.getByRole("complementary", { name: "Overview" });
  await expect(panel).toBeVisible();
  if (isMobile(info)) {
    const toggle = panel.getByRole("button", { name: "Expand overview" });
    if (await toggle.isVisible()) await toggle.click();
  }
  return panel;
}

async function shot(page: Page, info: TestInfo, name: string) {
  await page.screenshot({
    path: `test-results/screens/${info.project.name}-${name}.png`,
    fullPage: true,
    animations: "disabled",
  });
}

test("Overview lists the staged items and the total, and Approve confirms the proposal", async ({ page }, info) => {
  await signIn(page, "/conversations/conv-carbonara");
  const panel = await overview(page, info);
  await expect(panel.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(panel.getByText("5 items staged")).toBeVisible();
  await expect(panel.getByText("Spaghetti 1kg")).toBeVisible();
  await expect(panel.getByText("Guanciale 500g")).toBeVisible();
  await expect(panel.getByText("Incl. VAT")).toBeVisible();
  await expect(panel.getByText("€627.50")).toBeVisible();
  await expect(panel.getByText("€561.42")).toBeVisible();
  await shot(page, info, "request-overview");

  await panel.getByRole("button", { name: "Approve & Push to Dispatch" }).click();
  await expect(panel.getByText("Accepted by demo order service")).toBeVisible();
  await expect(panel.getByText(/DEMO-ORD-\d+/)).toBeVisible();
  await expect(panel.getByRole("button", { name: "Approve & Push to Dispatch" })).toHaveCount(0);
  await shot(page, info, "request-overview-receipt");
});

test("Reject declines the proposal", async ({ page }, info) => {
  await signIn(page, "/conversations/conv-carbonara");
  const panel = await overview(page, info);
  await panel.getByRole("button", { name: "Reject" }).click();
  await expect(panel.getByText("Rejection recorded. This purchase cannot be committed.")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Approve & Push to Dispatch" })).toHaveCount(0);
});

test("a revised proposal shows an alert and needs a second approval of the new revision", async ({ page }, info) => {
  await signIn(page, "/conversations/conv-oat-restock");
  const panel = await overview(page, info);
  await panel.getByRole("button", { name: "Approve & Push to Dispatch" }).click();
  const alert = panel.getByRole("alert").filter({ hasText: "Terms changed" });
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("confirm again");
  await expect(panel).toContainText("536");
  await shot(page, info, "request-overview-revised");

  await panel.getByRole("button", { name: "Approve & Push to Dispatch" }).click();
  await expect(panel.getByText("Accepted by demo order service")).toBeVisible();
});

test("a blocked proposal explains why and cannot be approved", async ({ page }, info) => {
  await signIn(page, "/conversations/conv-blocked");
  const panel = await overview(page, info);
  const alert = panel.getByRole("alert");
  await expect(alert).toContainText("cannot be approved");
  await expect(alert).toContainText("above the 150.00 EUR budget");
  await expect(panel.getByRole("button", { name: "Approve & Push to Dispatch" })).toHaveCount(0);
  await shot(page, info, "request-overview-blocked");
});

test("an expired proposal is greyed out with an Expired tag and cannot be approved", async ({ page }, info) => {
  await signIn(page, "/conversations/conv-expired");
  const panel = await overview(page, info);
  await expect(panel.getByText("Expired", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Approve & Push to Dispatch" })).toHaveCount(0);
  await shot(page, info, "request-overview-expired");
});

test("Save as Draft, Export Manifest, Substitutions and the account manager are inert placeholders", async ({ page }, info) => {
  await signIn(page, "/conversations/conv-carbonara");
  const panel = await overview(page, info);
  await expect(panel.getByRole("button", { name: "Save as Draft" })).toBeDisabled();
  await expect(panel.getByRole("button", { name: "Export Manifest" })).toBeDisabled();
  await expect(panel.getByRole("switch", { name: "Substitutions allowed" })).toBeDisabled();
  await expect(panel.getByText("Account Manager")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Call account manager" })).toBeDisabled();
});

test("a new request has no staged items to approve yet", async ({ page }, info) => {
  await signIn(page, "/request");
  const panel = await overview(page, info);
  await expect(panel.getByText("No items staged yet")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Approve & Push to Dispatch" })).toHaveCount(0);
});
