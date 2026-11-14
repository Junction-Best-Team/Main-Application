import { expect, test } from "@playwright/test";

test("buyer signs in and lands on Home", async ({ page }, info) => {
  await page.goto("/login");
  await expect(page.getByRole("main").getByText("aimo.", { exact: true })).toBeVisible();
  const username = page.getByLabel("Username");
  const password = page.getByLabel("Password");
  const signIn = page.getByRole("button", { name: "Sign in" });

  // Design-system input and button rules: 44px fields, no horizontal overflow.
  expect((await username.boundingBox())!.height).toBe(44);
  expect((await password.boundingBox())!.height).toBe(44);
  expect((await signIn.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `test-results/screens/${info.project.name}-login.png`, fullPage: true });

  await username.fill("buyer");
  await password.fill("demo");
  await signIn.click();
  await expect(page).toHaveURL((u) => u.pathname === "/");
  await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0);
});

test("a failed sign-in shows the error", async ({ page }, info) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("baduser");
  await page.getByLabel("Password").fill("x");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.screenshot({ path: `test-results/screens/${info.project.name}-login-error.png`, fullPage: true });
});

for (const path of ["/request", "/purchases"]) {
  test(`signing in from a ${path} deep link returns there`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveURL((u) => u.pathname === "/login");
    await page.getByLabel("Username").fill("buyer");
    await page.getByLabel("Password").fill("demo");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL((u) => u.pathname === path);
  });
}
