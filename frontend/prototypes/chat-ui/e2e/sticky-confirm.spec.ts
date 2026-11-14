import { expect, test, type Page } from "@playwright/test";

async function signIn(page: Page, path: string) {
  await page.goto(path);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password").fill("pw");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("there is no variant switcher and links never carry ?variant=", async ({ page }, info) => {
  await signIn(page, "/conversations/conv-carbonara");
  await expect(page.getByText("Confirmation variant")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Modal" })).toHaveCount(0);
  if (info.project.name === "mobile") await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Past Orders" }).click();
  await expect(page).toHaveURL(/\/purchases$/);
  for (const href of await page.locator("a").evaluateAll((as) => as.map((a) => a.getAttribute("href")))) {
    expect(href).not.toContain("variant");
  }
});

test("the chat thread card only links to the basket, with no decision buttons", async ({ page }) => {
  await signIn(page, "/conversations/conv-carbonara");
  await expect(page.getByRole("link", { name: "Review basket and purchasing checks" })).toBeVisible();
  await expect(page.getByRole("button", { name: /confirm this purchase/i })).toHaveCount(0);
});
