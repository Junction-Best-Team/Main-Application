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
    max_order_gross: "5000.00",
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

test("signed-in buyer saves cap and basket rules without sending hidden scope or authority", async ({
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
      expect(body).toEqual({
        expected_version: 1,
        rules: {
          max_order_gross: "250.50",
          substitution: "forbidden",
          overbuy: "requires_approval",
          whole_sales_units: true,
        },
      });
      current = {
        ...current,
        policy_version: 2,
        rules: {
          ...current.rules,
          ...body.rules,
          max_order_gross:
            body.rules.max_order_gross == null
              ? null
              : String(body.rules.max_order_gross),
        },
        history: [
          { version: 2, actor_id: "buyer", created_at: "2026-11-14T12:00:00Z" },
        ],
      };
    }
    await route.fulfill({ json: current });
  });
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Purchasing rules" }),
  ).toBeVisible();
  const save = page.getByRole("button", { name: "Save changes" });
  await expect(save).toBeDisabled();
  await expect(page.getByText("You confirm every order.")).toBeVisible();
  await expect(
    page.getByText(
      /Change history|Policy version|Approved product codes|Delivery destinations|managed by your administrator|You can edit/,
    ),
  ).toHaveCount(0);
  await page.getByLabel("Maximum per order").fill("250.50");
  await page
    .getByLabel("Other products & alternatives")
    .selectOption("forbidden");
  await save.click();
  await expect(page.getByRole("status")).toContainText("Changes saved");
  await expect(save).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel("Maximum per order")).toHaveValue("250.50");
  await expect(page.getByLabel("Other products & alternatives")).toHaveValue(
    "forbidden",
  );
});

test("legacy account without a cap shows blank and can save basket rules", async ({
  page,
}) => {
  await session(page);
  await page.route("**/api/settings/policy", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      expect(body.rules.max_order_gross).toBeNull();
      await route.fulfill({
        json: {
          ...settings,
          rules: { ...settings.rules, ...body.rules },
          policy_version: 2,
        },
      });
    } else
      await route.fulfill({
        json: {
          ...settings,
          rules: { ...settings.rules, max_order_gross: null },
        },
      });
  });
  await page.goto("/settings");
  await expect(page.getByLabel("Maximum per order")).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Save changes" }),
  ).toBeDisabled();
  await page.getByLabel("Extra quantities").selectOption("allowed");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status")).toContainText("Changes saved");
});

test("discard restores cap, rules and advanced pack setting", async ({
  page,
}) => {
  await session(page);
  await page.route("**/api/settings/policy", (route) =>
    route.fulfill({ json: settings }),
  );
  await page.goto("/settings");
  await page.getByLabel("Maximum per order").fill("");
  await page.getByLabel("Extra quantities").selectOption("allowed");
  await page.getByText("Advanced rules", { exact: false }).click();
  await page.getByLabel("Require whole sales units").uncheck();
  await page.getByRole("button", { name: "Discard", exact: true }).click();
  await expect(page.getByLabel("Maximum per order")).toHaveValue("5000.00");
  await expect(page.getByLabel("Extra quantities")).toHaveValue(
    "requires_approval",
  );
  await expect(page.getByLabel("Require whole sales units")).toBeChecked();
  await expect(
    page.getByRole("button", { name: "Save changes" }),
  ).toBeDisabled();
});

test("negative cap cannot be saved", async ({ page }) => {
  await session(page);
  await page.route("**/api/settings/policy", (route) =>
    route.fulfill({ json: settings }),
  );
  await page.goto("/settings");
  await page.getByLabel("Maximum per order").fill("-1");
  await expect(
    page.getByRole("button", { name: "Save changes" }),
  ).toBeDisabled();
});

test("conflict keeps edits until explicit reload", async ({ page }) => {
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
  await page.getByLabel("Maximum per order").fill("250");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("alert")).toContainText("Reload before saving");
  await expect(page.getByLabel("Maximum per order")).toHaveValue("250");
  await page.getByRole("button", { name: "Reload settings" }).click();
  await expect(page.getByLabel("Maximum per order")).toHaveValue("5000.00");
  await expect(
    page.getByRole("button", { name: "Save changes" }),
  ).toBeDisabled();
});

test("expired session returns to sign in", async ({ page }) => {
  await session(page);
  await page.route("**/api/settings/policy", (route) =>
    route.fulfill({ status: 401, json: { error: { message: "Sign in" } } }),
  );
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login$/);
});

for (const [name, width, height] of [
  ["desktop", 1440, 1000],
  ["small-desktop", 1024, 1000],
  ["tablet", 768, 1000],
  ["mobile", 390, 1000],
  ["small-mobile", 320, 1000],
  ["short-desktop", 1440, 480],
  ["short-mobile", 390, 568],
] as const) {
  test(`settings layout on ${name}`, async ({ page }, testInfo) => {
    await session(page);
    await page.setViewportSize({ width, height });
    await page.route("**/api/settings/policy", (route) =>
      route.fulfill({ json: settings }),
    );
    await page.goto("/settings");
    await expect(page.getByLabel("Maximum per order")).toBeVisible();
    await expect(page.getByLabel("Extra quantities")).toBeVisible();
    const sidebar = page.getByRole("complementary", { name: "Sidebar" });
    let navigation = sidebar;
    if (width < 768) {
      await page.getByRole("button", { name: "Open menu" }).click();
      navigation = page.getByRole("dialog", { name: "Menu", exact: true });
    } else {
      await expect(page.getByRole("banner")).toHaveCount(0);
    }
    const trigger = navigation.getByRole("button", { name: "User menu" });
    const account = navigation.getByRole("navigation", {
      name: "User account",
    });
    await expect(trigger).toHaveText(/Account/);
    const triggerBox = await trigger.boundingBox();
    expect(triggerBox!.y).toBeGreaterThan(height - 100);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await trigger.focus();
    await page.keyboard.press("Enter");
    const settingsLink = account.getByRole("link", {
      name: "Account Settings",
    });
    await expect(settingsLink).toBeFocused();
    await expect(settingsLink).toHaveAttribute("aria-current", "page");
    await page.keyboard.press("Tab");
    await expect(account.getByRole("link", { name: "Memory" })).toBeFocused();
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
    // Moving focus outside the account popup dismisses it.
    await navigation.getByRole("link", { name: "New request" }).focus();
    await expect(account).toHaveCount(0);
    await trigger.click();
    await settingsLink.click();
    await expect(account).toHaveCount(0);
    if (width < 768) {
      await expect(navigation).toHaveCount(0);
      await page.getByRole("button", { name: "Open menu" }).click();
    }
    await trigger.click();
    const popupBox = await account.boundingBox();
    expect(popupBox!.y).toBeGreaterThanOrEqual(0);
    expect(popupBox!.y + popupBox!.height).toBeLessThanOrEqual(triggerBox!.y);
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
