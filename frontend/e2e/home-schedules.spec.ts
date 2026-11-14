import { expect, test, type Page } from "@playwright/test";
import type { Schedule } from "../src/shared/api/types";
import {
  ids,
  json,
  mockSignedIn,
  pausedSchedule,
  problem,
  schedule,
  stoppedSchedule,
} from "./support/schedulerFixtures";

// The Home "Scheduled deliveries" strip reads GET /api/schedules (first three). Mocked API.

async function mockHome(page: Page, items: Schedule[] = [schedule]) {
  await mockSignedIn(page);
  const requests: string[] = [];
  await page.route("**/api/schedules?*", (route) => {
    requests.push(new URL(route.request().url()).search);
    return json(route, { items, next_offset: null });
  });
  return requests;
}
const strip = (page: Page) =>
  page.getByRole("region", { name: "Scheduled deliveries" });

test("the strip lists real standing orders with their next run and cadence", async ({
  page,
}) => {
  const requests = await mockHome(page, [
    schedule,
    pausedSchedule,
    stoppedSchedule,
  ]);
  await page.goto("/");
  await expect(strip(page)).not.toContainText("Placeholder");

  const first = strip(page).getByRole("link", { name: /Breakfast dairy/ });
  await expect(first).toHaveAttribute("href", `/schedules/${ids.schedule}`);
  await expect(first).toContainText("Every week on Friday");
  // React StrictMode may repeat the first request in development.
  expect(new Set(requests)).toEqual(new Set(["?offset=0&limit=3"]));
  await expect(strip(page).getByText("20 Nov 2026").first()).toBeVisible();

  // A paused schedule keeps advancing its date on the server; a stopped one has none.
  await expect(
    strip(page).getByRole("link", { name: /Weekend cheeses/ }),
  ).toContainText("Every 4 days");
  await expect(
    strip(page).getByRole("link", { name: /Seasonal vegetables/ }),
  ).toBeVisible();
  await expect(strip(page).getByText("Paused")).toBeVisible();
});

test("View all opens the standing orders", async ({ page }) => {
  await mockHome(page);
  await page.goto("/");
  await expect(
    strip(page).getByRole("link", { name: "View all" }),
  ).toHaveAttribute("href", "/schedules");
});

test("replaced schedules are hidden from the strip", async ({ page }) => {
  const replaced: Schedule = {
    ...stoppedSchedule,
    id: "7a7a7a7a-0000-4000-8000-000000000001",
    title: "Old stopped one",
    replaced_by: ids.successor,
  };
  await mockHome(page, [schedule, replaced]);
  await page.goto("/");
  await expect(strip(page)).toContainText("Breakfast dairy");
  await expect(strip(page)).not.toContainText("Old stopped one");
});

test("with no standing orders it points to the past orders", async ({
  page,
}) => {
  await mockHome(page, []);
  await page.goto("/");
  await expect(strip(page)).toContainText("No standing orders yet.");
  await expect(
    strip(page).getByRole("link", { name: "Schedule a past order" }),
  ).toHaveAttribute("href", "/purchases");
});

test("a failed load shows the message and not the empty state", async ({
  page,
}) => {
  await mockSignedIn(page);
  await page.route("**/api/schedules?*", (route) =>
    problem(route, 503, "UPSTREAM_UNAVAILABLE", "Standing orders are down."),
  );
  await page.goto("/");
  await expect(strip(page).getByRole("alert")).toContainText(
    "Standing orders are down.",
  );
  await expect(strip(page)).not.toContainText("No standing orders yet.");
});

test("an expired session returns to sign-in", async ({ page }) => {
  await mockSignedIn(page);
  await page.route("**/api/schedules?*", (route) =>
    problem(route, 401, "UNAUTHENTICATED", "Sign in to continue."),
  );
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("the strip fits a 390px phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockHome(page, [schedule, pausedSchedule, stoppedSchedule]);
  await page.goto("/");
  await expect(strip(page)).toContainText("Breakfast dairy");
  const box = await strip(page).boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBeTruthy();
});
