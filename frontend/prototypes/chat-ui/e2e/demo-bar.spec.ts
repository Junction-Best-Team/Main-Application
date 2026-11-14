import { expect, test, type Page } from "./test";

async function signIn(page: Page, path: string) {
  await page.goto(path);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password").fill("pw");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("the end of a page scrolls clear of the prototype controls", async ({ page }) => {
  await signIn(page, "/purchases");
  await page.getByLabel("Scenario").selectOption({ label: "Many past orders (paged)" });
  const controls = page.getByRole("toolbar", { name: "Prototype controls" });
  await expect(controls.getByRole("button", { name: "Reset demo data" })).toBeVisible();
  const last = page.getByRole("button", { name: "Show more orders" });
  await expect(last).toBeVisible();

  await page.evaluate(() => window.scrollTo(0, document.scrollingElement!.scrollHeight));
  const lastBox = (await last.boundingBox())!;
  const barBox = (await controls.boundingBox())!;
  expect(lastBox.y + lastBox.height).toBeLessThanOrEqual(barBox.y);
});
