import { expect, test, type Page } from "@playwright/test";
import type { Schedule } from "../src/shared/api/types";
import {
  ids,
  json,
  mockSignedIn,
  orders,
  ordersPage,
  pausedSchedule,
  problem,
  schedule,
  stoppedSchedule,
} from "./support/schedulerFixtures";

// The Home "Standing orders" card reads GET /api/schedules (first three). Mocked API.

async function mockHome(page: Page, items: Schedule[] = [schedule]) {
  await mockSignedIn(page);
  const requests: string[] = [];
  await page.route("**/api/schedules?*", (route) => {
    requests.push(new URL(route.request().url()).search);
    return json(route, { items, next_offset: null });
  });
  await page.route("**/api/orders?*", (route) => json(route, ordersPage()));
  return requests;
}
const card = (page: Page) =>
  page.getByRole("region", { name: "Standing orders" });

test("the card lists real standing orders with chip, cadence, next run and total", async ({
  page,
}) => {
  const requests = await mockHome(page, [
    schedule,
    pausedSchedule,
    stoppedSchedule,
  ]);
  await page.goto("/");
  await expect(page.getByText("Active Delivery Schedule")).toHaveCount(0);
  await expect(card(page)).not.toContainText("Placeholder");

  const first = card(page).getByRole("link", { name: /Breakfast dairy/ });
  await expect(first).toHaveAttribute("href", `/schedules/${ids.schedule}`);
  // React StrictMode may repeat the first request in development.
  expect(new Set(requests)).toEqual(new Set(["?offset=0&limit=3"]));
  await expect(first).toContainText("Scheduled");
  await expect(first).toContainText("Every week on Friday");
  await expect(first).toContainText("20 Nov 2026");
  await expect(first).toContainText("€132.24");

  const paused = card(page).getByRole("link", { name: /Weekend cheeses/ });
  await expect(paused).toContainText("Paused");
  await expect(paused).toContainText("Every 4 days");

  const stopped = card(page).getByRole("link", { name: /Seasonal vegetables/ });
  await expect(stopped).toContainText("Stopped, needs attention");
  await expect(stopped).toContainText("No upcoming run");
});

test("replaced schedules are hidden from the card", async ({ page }) => {
  await mockHome(page, [
    { ...stoppedSchedule, replaced_by: ids.successor },
    schedule,
  ]);
  await page.goto("/");
  await expect(
    card(page).getByRole("link", { name: /Breakfast dairy/ }),
  ).toBeVisible();
  await expect(card(page).getByText("Seasonal vegetables")).toHaveCount(0);
});

test("View all standing orders is a real link", async ({ page }) => {
  await mockHome(page);
  await page.route("**/api/schedules?offset=0&limit=20", (route) =>
    json(route, { items: [schedule], next_offset: null }),
  );
  await page.goto("/");
  const link = card(page).getByRole("link", {
    name: "View all standing orders",
  });
  await expect(link).toHaveAttribute("href", "/schedules");
  await link.click();
  await expect(page).toHaveURL(/\/schedules$/);
});

test("an empty card points to the past orders to schedule one", async ({
  page,
}) => {
  await mockHome(page, []);
  await page.goto("/");
  await expect(card(page)).toContainText("No standing orders yet");
  await card(page).getByRole("link", { name: "Schedule a past order" }).click();
  await expect(page).toHaveURL(/\/purchases$/);
});

test("the card shows an error without breaking the rest of Home", async ({
  page,
}) => {
  await mockSignedIn(page);
  await page.route("**/api/schedules?*", (route) =>
    problem(route, 503, "UNAVAILABLE", "Standing orders are unavailable."),
  );
  await page.route("**/api/orders?*", (route) => json(route, ordersPage()));
  await page.goto("/");
  await expect(card(page).getByRole("alert")).toContainText(
    "Standing orders are unavailable.",
  );
  await expect(
    page.getByRole("heading", { name: "Welcome, demo-hotel" }),
  ).toBeVisible();
});

test("the card shows loading", async ({ page }) => {
  await mockSignedIn(page);
  await page.route("**/api/schedules?*", async (route) => {
    await new Promise((r) => setTimeout(r, 500));
    return json(route, { items: [], next_offset: null });
  });
  await page.route("**/api/orders?*", (route) => json(route, ordersPage()));
  await page.goto("/");
  await expect(card(page).getByRole("status")).toContainText(
    "Loading standing orders",
  );
  await expect(card(page)).toContainText("No standing orders yet");
});

test("an expired session on the card returns to sign-in", async ({ page }) => {
  await mockSignedIn(page);
  await page.route("**/api/schedules?*", (route) =>
    problem(route, 401, "UNAUTHENTICATED", "Sign in to continue."),
  );
  await page.route("**/api/orders?*", (route) => json(route, ordersPage()));
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("Recent Past Orders shows the placed rows of GET /api/orders", async ({
  page,
}) => {
  await mockSignedIn(page);
  await page.route("**/api/schedules?*", (route) =>
    json(route, { items: [], next_offset: null }),
  );
  const requests: string[] = [];
  await page.route("**/api/orders?*", (route) => {
    requests.push(new URL(route.request().url()).search);
    return json(route, ordersPage());
  });
  await page.goto("/");
  const recent = page.getByRole("region", { name: "Recent Past Orders" });
  const link = recent.getByRole("link", { name: /Hotel breakfast/ });
  await expect(link).toHaveAttribute("href", `/purchases/${ids.proposal}`);
  await expect(link).toContainText("Accepted (demo)");
  await expect(link).toContainText("€132.24");
  await expect(link).toContainText("2 items");
  // Scheduled, pending and cancelled rows are not recent accepted orders.
  await expect(recent.getByRole("link", { name: /Old basket/ })).toHaveCount(0);
  await expect(recent.getByRole("link", { name: /Carbonara/ })).toHaveCount(0);
  expect(requests[0]).toMatch(/^\?offset=0&limit=/);
  expect(orders.filter((o) => o.status === "placed")).toHaveLength(1);
});

test("Recent Past Orders keeps reading until it finds placed rows", async ({
  page,
}) => {
  await mockSignedIn(page);
  await page.route("**/api/schedules?*", (route) =>
    json(route, { items: [], next_offset: null }),
  );
  const offsets: string[] = [];
  await page.route("**/api/orders?*", (route) => {
    const offset = new URL(route.request().url()).searchParams.get("offset");
    offsets.push(String(offset));
    return json(
      route,
      offset === "0"
        ? ordersPage([orders[0], orders[2]], 20)
        : ordersPage([orders[3]], null),
    );
  });
  await page.goto("/");
  await expect(
    page
      .getByRole("region", { name: "Recent Past Orders" })
      .getByRole("link", { name: /Hotel breakfast/ }),
  ).toBeVisible();
  expect(new Set(offsets)).toEqual(new Set(["0", "20"]));
});

test("Home fits a 390px phone with the standing orders card", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockHome(page, [schedule, pausedSchedule, stoppedSchedule]);
  await page.goto("/");
  await expect(
    card(page).getByRole("link", { name: /Breakfast dairy/ }),
  ).toBeVisible();
  // The card itself must not scroll sideways. (The page-wide check is skipped: without the
  // icon font the pre-existing banner button overflows in offline test runs.)
  expect(
    await card(page).evaluate((el) => el.scrollWidth <= el.clientWidth),
  ).toBeTruthy();
  const box = await card(page).boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBeTruthy();
});
