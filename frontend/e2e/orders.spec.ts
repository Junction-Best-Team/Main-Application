import { expect, test, type Page } from "@playwright/test";
import type { OrderListItem } from "../src/shared/api/types";
import { placedProposal, proposal } from "./support/proposalFixture";
import {
  ids,
  json,
  mockSignedIn,
  orders,
  ordersPage,
  problem,
  session,
} from "./support/schedulerFixtures";

// Past Orders reads GET /api/orders (scheduled, pending, placed, cancelled rows). All API
// traffic is mocked; nothing here proves the live backend.

const row = (page: Page, title: string) =>
  page.locator(".purchase-row").filter({ hasText: title });

async function mockOrders(page: Page, items: OrderListItem[] = orders) {
  await mockSignedIn(page);
  const requests: string[] = [];
  await page.route("**/api/orders?*", (route) => {
    requests.push(new URL(route.request().url()).search);
    return json(route, ordersPage(items));
  });
  await page.route(`**/api/purchases/${ids.proposal}`, (route) =>
    json(route, placedProposal),
  );
  return requests;
}

test("every row kind shows its status chip, date and link", async ({
  page,
}) => {
  const requests = await mockOrders(page);
  await page.goto("/purchases");
  await expect(
    page.getByRole("heading", { name: "Past Orders" }),
  ).toBeVisible();
  await expect(page.locator(".purchase-row")).toHaveCount(5);
  expect(requests[0]).toBe("?offset=0&limit=20");

  const scheduled = row(page, "Breakfast dairy");
  await expect(scheduled.locator(".badge.scheduled")).toHaveText("Scheduled");
  await expect(scheduled).toContainText("20 Nov 2026");
  await expect(scheduled).toContainText("2 lines");
  await expect(scheduled).toContainText("€132.24");
  await expect(scheduled).toContainText("14 Nov 2026");
  await expect(scheduled.locator(".badge.paused")).toHaveCount(0);
  await expect(
    scheduled.getByRole("link", { name: "Breakfast dairy" }),
  ).toHaveAttribute("href", `/schedules/${ids.schedule}`);

  const paused = row(page, "Weekend cheeses");
  await expect(paused.locator(".badge.scheduled")).toHaveText("Scheduled");
  await expect(paused.locator(".badge.paused")).toHaveText("Paused");
  await expect(paused).toContainText("24 Nov 2026");
  await expect(
    paused.getByRole("link", { name: "Weekend cheeses" }),
  ).toHaveAttribute("href", `/schedules/${ids.pausedSchedule}`);

  const pending = row(page, "Carbonara for 200");
  await expect(pending.locator(".badge.pending")).toHaveText("Pending");
  await expect(
    pending.getByRole("link", { name: "Carbonara for 200" }),
  ).toHaveAttribute("href", `/purchases/${ids.proposal}`);
  await expect(
    pending.getByRole("button", { name: "Cancel request" }),
  ).toBeVisible();

  const placed = row(page, "Hotel breakfast");
  await expect(placed.locator(".badge.placed")).toHaveText("Placed");
  await expect(
    placed.getByRole("button", { name: "Cancel request" }),
  ).toHaveCount(0);

  const cancelled = row(page, "Old basket");
  await expect(cancelled.locator(".badge.cancelled")).toHaveText("Cancelled");
  await expect(cancelled).toContainText("Cancelled by you");
  await expect(
    cancelled.getByRole("button", { name: "Cancel request" }),
  ).toHaveCount(0);
});

test("placed rows offer Schedule this order and expand to the receipt details", async ({
  page,
}) => {
  await mockOrders(page);
  await page.goto("/purchases");
  const placed = row(page, "Hotel breakfast");
  await expect(
    placed.getByRole("link", { name: "Schedule this order" }),
  ).toHaveAttribute("href", `/schedules/new?order=${ids.sourceOrder}`);
  await placed
    .getByRole("button", { name: "Order details: Hotel breakfast" })
    .click();
  await expect(
    placed.getByText("Ordered items", { exact: true }),
  ).toBeVisible();
  await expect(placed.locator(".purchase-sheet")).toContainText(
    "Spaghetti 5 kg",
  );
  await expect(placed).toContainText("Accepted by demo order service");
  await expect(
    placed.getByRole("button", { name: "Order details: Hotel breakfast" }),
  ).toHaveAttribute("aria-expanded", "true");
  // Only placed rows can be scheduled.
  await expect(
    page.getByRole("link", { name: "Schedule this order" }),
  ).toHaveCount(1);
});

test("cancelled rows explain why, and rows from a standing order link to it", async ({
  page,
}) => {
  const from = {
    schedule_id: ids.schedule,
    schedule_title: "Breakfast dairy",
  };
  await mockOrders(page, [
    {
      ...orders[4],
      title: "Disrupted run",
      cancel_reason: "run_disrupted",
      ...from,
    },
    {
      ...orders[4],
      title: "Revised basket",
      cancel_reason: "customer_revised",
    },
    { ...orders[4], title: "Own cancel", cancel_reason: "customer_cancelled" },
    { ...orders[3], title: "Placed by schedule", ...from },
  ]);
  await page.goto("/purchases");
  await expect(row(page, "Disrupted run")).toContainText(
    "Cancelled because a standing-order run was disrupted",
  );
  await expect(row(page, "Revised basket")).toContainText(
    "Replaced by a revised request",
  );
  await expect(row(page, "Own cancel")).toContainText("Cancelled by you");
  await expect(row(page, "Revised basket")).not.toContainText(
    "From standing order",
  );
  for (const title of ["Disrupted run", "Placed by schedule"]) {
    const scheduleLink = row(page, title).getByRole("link", {
      name: /From standing order Breakfast dairy/,
    });
    await expect(scheduleLink).toHaveAttribute(
      "href",
      `/schedules/${ids.schedule}`,
    );
  }
});

test.describe("cancel request", () => {
  test("asks for confirmation, can be dismissed, then cancels with the CSRF token", async ({
    page,
  }) => {
    await mockSignedIn(page);
    let cancelled = false;
    let loads = 0;
    const posts: { csrf: string | undefined }[] = [];
    await page.route("**/api/orders?*", (route) => {
      if (cancelled) loads++;
      return json(
        route,
        ordersPage(
          cancelled
            ? [
                {
                  ...orders[2],
                  status: "cancelled",
                  cancel_reason: "customer_cancelled",
                },
              ]
            : [orders[2]],
        ),
      );
    });
    await page.route(`**/api/purchases/${ids.proposal}/cancel`, (route) => {
      posts.push({ csrf: route.request().headers()["x-csrf-token"] });
      cancelled = true;
      return json(route, {
        proposal_id: ids.proposal,
        reason: "customer_cancelled",
        cancelled_by: "buyer",
        cancelled_at: "2026-11-14T10:00:00+02:00",
      });
    });
    await page.goto("/purchases");
    const pending = row(page, "Carbonara for 200");
    await pending.getByRole("button", { name: "Cancel request" }).click();
    await expect(pending).toContainText("Cancel this request?");
    await pending.getByRole("button", { name: "Keep request" }).click();
    await expect(pending).not.toContainText("Cancel this request?");
    expect(posts).toEqual([]);

    await pending.getByRole("button", { name: "Cancel request" }).click();
    await pending.getByRole("button", { name: "Yes, cancel request" }).click();
    await expect(pending.locator(".badge.cancelled")).toHaveText("Cancelled");
    await expect(pending).toContainText("Cancelled by you");
    expect(posts).toEqual([{ csrf: session.csrf_token }]);
    // The list is reloaded once after the cancel request.
    expect(loads).toBe(1);
  });

  test("an order that was already placed says so and refreshes the list", async ({
    page,
  }) => {
    await mockSignedIn(page);
    let placed = false;
    await page.route("**/api/orders?*", (route) =>
      json(
        route,
        ordersPage(
          placed ? [{ ...orders[3], title: "Carbonara for 200" }] : [orders[2]],
        ),
      ),
    );
    await page.route(`**/api/purchases/${ids.proposal}/cancel`, (route) => {
      placed = true;
      return problem(
        route,
        409,
        "ORDER_ALREADY_PLACED",
        "Order already placed.",
      );
    });
    await page.goto("/purchases");
    const pending = row(page, "Carbonara for 200");
    await pending.getByRole("button", { name: "Cancel request" }).click();
    await pending.getByRole("button", { name: "Yes, cancel request" }).click();
    const placedRow = row(page, "Carbonara for 200");
    await expect(placedRow.locator(".badge.placed")).toHaveText("Placed");
    await expect(placedRow).toContainText("This order was already placed.");
  });

  test("a request that no longer exists is reported and the list refreshes", async ({
    page,
  }) => {
    await mockSignedIn(page);
    let gone = false;
    let loads = 0;
    await page.route("**/api/orders?*", (route) => {
      if (gone) loads++;
      return json(route, ordersPage(gone ? [] : [orders[2]]));
    });
    await page.route(`**/api/purchases/${ids.proposal}/cancel`, (route) => {
      gone = true;
      return problem(route, 404, "NOT_FOUND", "Not found.");
    });
    await page.goto("/purchases");
    const pending = row(page, "Carbonara for 200");
    await pending.getByRole("button", { name: "Cancel request" }).click();
    await pending.getByRole("button", { name: "Yes, cancel request" }).click();
    await expect(page.getByRole("alert")).toContainText(
      "This request no longer exists.",
    );
    await expect(page.locator(".purchase-row")).toHaveCount(0);
    // The list is reloaded once after the cancel request.
    expect(loads).toBe(1);
  });

  test("another failure keeps the row and shows the server message", async ({
    page,
  }) => {
    await mockOrders(page, [orders[2]]);
    await page.route(`**/api/purchases/${ids.proposal}/cancel`, (route) =>
      problem(route, 503, "UNAVAILABLE", "Cancelling is unavailable."),
    );
    await page.goto("/purchases");
    const pending = row(page, "Carbonara for 200");
    await pending.getByRole("button", { name: "Cancel request" }).click();
    await pending.getByRole("button", { name: "Yes, cancel request" }).click();
    await expect(pending).toContainText("Cancelling is unavailable.");
    await expect(pending.locator(".badge.pending")).toBeVisible();
  });
});

test("status filter chips narrow the loaded rows", async ({ page }) => {
  await mockOrders(page);
  await page.goto("/purchases");
  const filters = page.getByRole("group", { name: "Filter orders by status" });
  await expect(filters.getByRole("button", { name: "All" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await filters.getByRole("button", { name: "Scheduled" }).click();
  await expect(page.locator(".purchase-row")).toHaveCount(2);
  await filters.getByRole("button", { name: "Pending" }).click();
  await expect(page.locator(".purchase-row")).toHaveCount(1);
  await expect(page.locator(".purchase-row")).toContainText(
    "Carbonara for 200",
  );
  await filters.getByRole("button", { name: "Placed" }).click();
  await expect(page.locator(".purchase-row")).toContainText("Hotel breakfast");
  await filters.getByRole("button", { name: "Cancelled" }).click();
  await expect(page.locator(".purchase-row")).toContainText("Old basket");
  await filters.getByRole("button", { name: "All" }).click();
  await expect(page.locator(".purchase-row")).toHaveCount(5);
});

test("a filter with no loaded rows says so", async ({ page }) => {
  await mockOrders(page, [orders[0]]);
  await page.goto("/purchases");
  await page
    .getByRole("group", { name: "Filter orders by status" })
    .getByRole("button", { name: "Cancelled" })
    .click();
  await expect(page.locator(".purchase-row")).toHaveCount(0);
  await expect(page.getByText("No cancelled orders loaded")).toBeVisible();
});

test("Show more orders pages the list by next_offset", async ({ page }) => {
  await mockSignedIn(page);
  const requests: string[] = [];
  await page.route("**/api/orders?*", (route) => {
    const search = new URL(route.request().url()).search;
    requests.push(search);
    return json(
      route,
      search.includes("offset=0")
        ? ordersPage([orders[0], orders[2]], 20)
        : ordersPage([orders[4]], null),
    );
  });
  await page.goto("/purchases");
  await expect(page.locator(".purchase-row")).toHaveCount(2);
  await page.getByRole("button", { name: "Show more orders" }).click();
  await expect(page.locator(".purchase-row")).toHaveCount(3);
  await expect(
    page.getByRole("button", { name: "Show more orders" }),
  ).toHaveCount(0);
  // React StrictMode may repeat the first request in development.
  expect([...new Set(requests)]).toEqual([
    "?offset=0&limit=20",
    "?offset=20&limit=20",
  ]);
});

test("a placed deep link expands its row even when the list does not contain it", async ({
  page,
}) => {
  await mockOrders(page, [orders[0]]);
  await page.goto(`/purchases/${ids.proposal}`);
  const placed = page.getByRole("button", {
    name: "Order details: Hotel breakfast",
  });
  await expect(placed).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".purchase-sheet")).toBeVisible();
  await expect(page.locator(".purchase-row")).toHaveCount(2);
});

test("a placed deep link expands the matching listed row once", async ({
  page,
}) => {
  await mockOrders(page);
  await page.goto(`/purchases/${ids.proposal}`);
  await expect(
    page.getByRole("button", { name: "Order details: Hotel breakfast" }),
  ).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".purchase-sheet")).toHaveCount(1);
  await expect(page.locator(".purchase-row")).toHaveCount(5);
});

test("an unplaced deep link opens the review instead of the list", async ({
  page,
}) => {
  await mockOrders(page);
  await page.route(`**/api/purchases/${ids.proposal}`, (route) =>
    json(route, { ...proposal, can_decide: true }),
  );
  await page.goto(`/purchases/${ids.proposal}`);
  await expect(page.getByText("hasn't been placed yet")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve & Push to Dispatch" }),
  ).toBeVisible();
});

test("shows loading, empty and error states", async ({ page }) => {
  await mockSignedIn(page);
  let mode: "slow" | "empty" | "fail" = "slow";
  await page.route("**/api/orders?*", async (route) => {
    if (mode === "slow") {
      await new Promise((r) => setTimeout(r, 500));
      return json(route, ordersPage([]));
    }
    if (mode === "fail")
      return problem(route, 503, "UNAVAILABLE", "Orders are unavailable.");
    return json(route, ordersPage([]));
  });
  await page.goto("/purchases");
  await expect(page.getByRole("status")).toContainText("Loading orders");
  await expect(page.getByText("No orders yet")).toBeVisible();
  mode = "fail";
  await page.getByRole("button", { name: "Refresh purchases" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Orders are unavailable.",
  );
  await expect(page.getByText("No orders yet")).toHaveCount(0);
});

test("an expired session returns to sign-in", async ({ page }) => {
  await mockSignedIn(page);
  await page.route("**/api/orders?*", (route) =>
    problem(route, 401, "UNAUTHENTICATED", "Sign in to continue."),
  );
  await page.goto("/purchases");
  await expect(page).toHaveURL(/\/login$/);
});

test("the toolbar keeps search, period and sort inert and labelled", async ({
  page,
}) => {
  await mockOrders(page);
  await page.goto("/purchases");
  await expect(
    page.getByRole("searchbox", { name: "Search past orders" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Last 90 days" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Sort: Most recent" }),
  ).toBeDisabled();
});

test("the orders list fits a 390px phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockOrders(page);
  await page.goto("/purchases");
  await expect(page.locator(".purchase-row")).toHaveCount(5);
  await row(page, "Hotel breakfast")
    .getByRole("button", { name: "Order details: Hotel breakfast" })
    .click();
  await row(page, "Carbonara for 200")
    .getByRole("button", { name: "Cancel request" })
    .click();
  await expect(
    row(page, "Carbonara for 200").getByRole("button", {
      name: "Yes, cancel request",
    }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  for (const r of await page.locator(".purchase-row").all()) {
    const box = await r.boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= 390).toBeTruthy();
  }
});
