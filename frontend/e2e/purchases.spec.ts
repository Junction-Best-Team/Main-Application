import { expect, test, type Page } from "@playwright/test";
import type { OrderListItem } from "../src/shared/api/types";
import { json, mockSignedIn, ordersPage } from "./support/schedulerFixtures";

// Past Orders search, period, sort and status (person 1's controls) over the rows of
// GET /api/orders. The mock honours `status` and `q` like the server; period and sort run in the
// browser. Everything is mocked; nothing here proves the live backend.

function placedOrder(
  overrides: Partial<OrderListItem> & {
    order_id: string;
    title: string;
    placed_at: string;
    gross_total: string;
  },
): OrderListItem {
  return {
    status: "placed",
    proposal_id: `proposal-${overrides.order_id}`,
    paused: false,
    currency: "EUR",
    line_count: 1,
    line_names: ["Spaghetti 5 kg"],
    updated_at: overrides.placed_at,
    ...overrides,
  };
}

async function mockOrderList(page: Page, items: OrderListItem[]) {
  await mockSignedIn(page);
  await page.route("**/api/orders?*", (route) => {
    const url = new URL(route.request().url());
    const status = url.searchParams.get("status");
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const matching = items.filter(
      (o) =>
        (!status || status.split(",").includes(o.status)) &&
        (!q ||
          [o.title, o.order_id, o.proposal_id, ...(o.line_names ?? [])]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(q)),
    );
    return json(route, ordersPage(matching, null, matching.length));
  });
}

test("Past Orders search, period, sort and status filter the orders", async ({
  page,
}) => {
  const day = 24 * 60 * 60 * 1000;
  const recent = placedOrder({
    order_id: "VA-1001",
    title: "Carbonara for 200",
    placed_at: new Date().toISOString(),
    gross_total: "114.00",
  });
  const older = placedOrder({
    order_id: "VA-2002",
    title: "Weekend tasting cheeses",
    placed_at: new Date(Date.now() - 40 * day).toISOString(),
    gross_total: "382.00",
  });
  const ancient = placedOrder({
    order_id: "VA-3003",
    title: "Spring pantry restock",
    placed_at: new Date(Date.now() - 120 * day).toISOString(),
    gross_total: "50.00",
  });
  await mockOrderList(page, [recent, older, ancient]);
  await page.goto("/purchases");
  await expect(
    page.getByRole("heading", { name: "Past Orders" }),
  ).toBeVisible();
  const rows = page.locator(".purchase-row");
  // Default period is last 90 days: recent + older, newest first.
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("VA-1001");
  await expect(rows.nth(1)).toContainText("VA-2002");

  await page.getByLabel("Period").selectOption("all");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(2)).toContainText("VA-3003");

  await page.getByLabel("Sort").selectOption("total_desc");
  await expect(rows.nth(0)).toContainText("VA-2002");
  await expect(rows.nth(1)).toContainText("VA-1001");
  await expect(rows.nth(2)).toContainText("VA-3003");

  await page.getByLabel("Search past orders").fill("VA-3003");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("Spring pantry restock");

  await page.getByLabel("Search past orders").fill("no-such-order");
  await expect(rows).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "No matching past orders" }),
  ).toBeVisible();

  await page.getByLabel("Search past orders").fill("");
  await page.getByLabel("Period").selectOption("7d");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("VA-1001");

  await page.getByLabel("Period").selectOption("all");
  await page.getByLabel("Status").selectOption("placed");
  await expect(rows).toHaveCount(3);
});

test("Past Orders search also finds a line name (the server matches it)", async ({
  page,
}) => {
  const cheese = placedOrder({
    order_id: "VA-4004",
    title: "Weekend order",
    placed_at: new Date().toISOString(),
    gross_total: "99.00",
    line_names: ["Salaneuvos 12 month aged cheese"],
  });
  const pasta = placedOrder({
    order_id: "VA-5005",
    title: "Kitchen restock",
    placed_at: new Date().toISOString(),
    gross_total: "20.00",
  });
  await mockOrderList(page, [cheese, pasta]);
  await page.goto("/purchases");
  const rows = page.locator(".purchase-row");
  await expect(rows).toHaveCount(2);
  await page.getByLabel("Search past orders").fill("salaneuvos");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("VA-4004");
});
