import { expect, test } from "@playwright/test";
import { json, mockSignedIn, problem, ids } from "./support/schedulerFixtures";

test("the Schedule item is in the navigation and opens the standing orders", async ({
  page,
}) => {
  await mockSignedIn(page);
  await page.route("**/api/schedules?*", (route) =>
    json(route, { items: [], next_offset: null }),
  );
  await page.goto("/");
  const link = page.getByRole("link", { name: "Schedule" }).first();
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/\/schedules$/);
  await expect(
    page.getByRole("heading", { name: "Standing orders", level: 1 }),
  ).toBeVisible();
});

test("an unknown schedule id is a plain not-found screen, not a crash", async ({
  page,
}) => {
  await mockSignedIn(page);
  await page.route(`**/api/schedules/${ids.schedule}*`, (route) =>
    problem(route, 404, "NOT_FOUND", "Standing order not found."),
  );
  await page.goto(`/schedules/${ids.schedule}`);
  await expect(page.getByRole("main")).toBeVisible();
});
