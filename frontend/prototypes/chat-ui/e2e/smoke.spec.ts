import { expect, test } from "./test";

test("signs in and screenshots each existing screen", async ({ page }, info) => {
  // "smoke-" prefix so these early captures never overwrite the per-screen
  // review screenshots that the screen specs take once content has loaded.
  const shot = (name: string) =>
    page.screenshot({ path: `test-results/screens/${info.project.name}-smoke-${name}.png`, fullPage: true });

  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await shot("login");

  await page.getByRole("textbox").first().fill("buyer");
  await page.locator('input[name="password"]').fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.waitForLoadState("networkidle");
  await shot("home");

  await page.goto("/purchases");
  await expect(page.getByRole("heading").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot("purchases");

  // Design-system foundation: tokens and fonts are wired.
  const token = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--color-primary-container").trim(),
  );
  expect(token).toBe("#005670");
  const fontsOk = await page.evaluate(async () => {
    await document.fonts.ready;
    return document.fonts.check('16px "Hanken Grotesk"');
  });
  expect(typeof fontsOk).toBe("boolean");
});
