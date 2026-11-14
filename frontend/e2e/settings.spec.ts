import { expect, test, type Page } from "@playwright/test";
import type { components } from "../src/shared/api/schema";

const settings: components["schemas"]["PolicySettings"] = {
  buyer_id: "demo-hotel",
  policy_version: 1,
  can_edit: true,
  rules: {
    currency: "EUR",
    destinations: ["hotel-helsinki"],
    approved_product_ids: ["464306"],
    substitution: "requires_approval",
    overbuy: "requires_approval",
    whole_sales_units: true,
  },
  approval_authority: {
    currency: "EUR",
    max_gross: "5000.00",
    exceptions: ["substitution", "overbuy"],
  },
  history: [],
};
async function session(page: Page) {
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
  await page.route("**/api/session", (route) =>
    route.fulfill({
      json: {
        username: "buyer",
        buyer_id: "demo-hotel",
        csrf_token: "settings-csrf",
      },
    }),
  );
}

test("manager changes rules and sees the saved version after a reload", async ({
  page,
}) => {
  await session(page);
  let current = structuredClone(settings);
  await page.route("**/api/settings/policy", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route
        .request()
        .postDataJSON() as components["schemas"]["PolicyUpdate"];
      expect(route.request().headers()["x-csrf-token"]).toBe("settings-csrf");
      expect(body.expected_version).toBe(1);
      expect(body.rules.approved_product_ids).toEqual(["464306", "464398"]);
      expect(body.rules.substitution).toBe("forbidden");
      current = {
        ...current,
        policy_version: 2,
        rules: body.rules,
        history: [
          { version: 2, actor_id: "buyer", created_at: "2026-11-14T12:00:00Z" },
        ],
      };
    }
    await route.fulfill({ json: current });
  });
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Purchasing settings" }),
  ).toBeVisible();
  const save = page.getByRole("button", { name: "Save purchasing rules" });
  await expect(save).toBeDisabled();
  await page
    .getByLabel("Approved product codes")
    .fill("464398, 464306, 464398");
  await page
    .getByLabel("Substitutions & products outside this list")
    .selectOption("forbidden");
  await save.click();
  await expect(page.getByRole("status")).toContainText(
    "Purchasing rules saved",
  );
  await expect(page.getByText("Policy version 2")).toBeVisible();
  await expect(save).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel("Approved product codes")).toHaveValue(
    "464306, 464398",
  );
  await expect(page.getByText("Version 2", { exact: true })).toBeVisible();
});

test("ordinary approver sees rules read-only", async ({ page }) => {
  await session(page);
  await page.route("**/api/settings/policy", (route) =>
    route.fulfill({ json: { ...settings, can_edit: false } }),
  );
  await page.goto("/settings");
  await expect(page.getByLabel("Approved product codes")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Save purchasing rules" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("A policy manager", { exact: false }),
  ).toBeVisible();
});

test("conflict keeps edits until the buyer explicitly reloads", async ({
  page,
}) => {
  await session(page);
  let version = 1;
  await page.route("**/api/settings/policy", (route) => {
    if (route.request().method() === "PUT") {
      version = 2;
      return route.fulfill({
        status: 409,
        json: {
          error: {
            message:
              "Settings changed since you opened them. Reload before saving.",
          },
        },
      });
    }
    return route.fulfill({ json: { ...settings, policy_version: version } });
  });
  await page.goto("/settings");
  await page.getByLabel("Approved product codes").fill("464398");
  await page.getByRole("button", { name: "Save purchasing rules" }).click();
  await expect(page.getByRole("alert")).toContainText("Reload before saving");
  await expect(page.getByLabel("Approved product codes")).toHaveValue("464398");
  await page.getByRole("button", { name: "Reload settings" }).click();
  await expect(page.getByText("Policy version 2")).toBeVisible();
  await expect(page.getByLabel("Approved product codes")).toHaveValue("464306");
});

test("expired session returns to sign in", async ({ page }) => {
  await session(page);
  await page.route("**/api/settings/policy", (route) =>
    route.fulfill({ status: 401, json: { error: { message: "Sign in" } } }),
  );
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login$/);
});

for (const [name, width] of [
  ["desktop", 1440],
  ["small-desktop", 1024],
  ["tablet", 768],
  ["mobile", 390],
  ["small-mobile", 320],
] as const) {
  test(`settings layout on ${name}`, async ({ page }, testInfo) => {
    await session(page);
    await page.setViewportSize({ width, height: 1000 });
    await page.route("**/api/settings/policy", (route) =>
      route.fulfill({ json: settings }),
    );
    await page.goto("/settings");
    await expect(page.getByLabel("Approved product codes")).toBeVisible();
    const trigger = page.getByRole("button", { name: "User menu" });
    const account = page.getByRole("navigation", { name: "User account" });
    const sidebar = page.getByRole("complementary", { name: "Sidebar" });
    await expect(
      sidebar.getByRole("link", { name: "Account Settings" }),
    ).toHaveCount(0);
    await expect(sidebar.getByRole("button", { name: "Sign out" })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", { name: "Switch account" }),
    ).toHaveCount(0);
    if (width < 768) {
      await page.getByRole("button", { name: "Open menu" }).click();
      const drawer = page.getByRole("dialog", { name: "Menu", exact: true });
      await expect(
        drawer.getByRole("link", { name: "Account Settings" }),
      ).toHaveCount(0);
      await expect(
        drawer.getByRole("link", { name: "Assistant preferences" }),
      ).toHaveCount(0);
      await expect(
        drawer.getByRole("button", { name: "Sign out" }),
      ).toHaveCount(0);
      await page.getByRole("button", { name: "Close menu" }).click();
    }
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await trigger.focus();
    await page.keyboard.press("Enter");
    const settingsLink = account.getByRole("link", {
      name: "Account Settings",
    });
    await expect(settingsLink).toBeFocused();
    await expect(settingsLink).toHaveAttribute("aria-current", "page");
    await page.keyboard.press("Tab");
    await expect(
      account.getByRole("link", { name: "Assistant preferences" }),
    ).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(
      account.getByRole("button", { name: "Sign out" }),
    ).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(account).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await trigger.click();
    await trigger.click();
    await expect(account).toHaveCount(0);
    await trigger.click();
    await page.getByLabel("Approved product codes").click();
    await expect(account).toHaveCount(0);
    await trigger.click();
    await settingsLink.click();
    await expect(account).toHaveCount(0);
    await trigger.click();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`${name}.png`),
      fullPage: true,
    });
  });
}
