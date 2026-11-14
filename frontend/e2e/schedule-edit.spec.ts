import { expect, test, type Page } from "@playwright/test";
import {
  cream,
  detail,
  disruptedRun,
  ids,
  json,
  milk,
  orders,
  ordersPage,
  problem,
  schedule,
  stoppedSchedule,
} from "./support/schedulerFixtures";
import {
  created,
  delay,
  detailHandler,
  mockApi,
  termsWith,
  type Handler,
} from "./support/scheduleEditorMock";
import type { OrderListItem, Schedule } from "../src/shared/api/types";

// "Edit / replace and restart": mocked at the browser/API edge only. Dates are in the far future
// so the specs do not depend on the day they run. 2030-03-15 is a Friday (weekday 4).
const FRIDAY = "2030-03-15";
const AUTH =
  "I agree to these exact terms, this price ceiling per run and this recurrence.";
const RESTART = "Restart standing order";
const id = ids.schedule;
const GET = `GET /api/schedules/${id}`;
const PREVIEW = `POST /api/schedules/${id}/preview`;
const REPLACE = `POST /api/schedules/${id}/replace`;
const ORDERS = "GET /api/orders";
const SUCCESSOR = `GET /api/schedules/${ids.successor}`;

const active: Schedule = {
  ...schedule,
  first_run_date: "2030-03-01",
  next_run_date: FRIDAY,
  valid_until: "2031-03-01",
};
const stopped: Schedule = {
  ...stoppedSchedule,
  id,
  first_run_date: "2030-03-01",
  next_run_date: null,
  last_run: disruptedRun,
};
const revisedOrderId = "8e3a0b21-7d4c-4f9a-b2c3-d4e5f6071829";
const placedOrders: OrderListItem[] = [
  ...orders,
  {
    ...orders[3]!,
    title: "Hotel breakfast (revised)",
    order_id: revisedOrderId,
  },
];

const getSchedule =
  (s: Schedule): Handler =>
  (route) =>
    json(route, detail(s));
const previewOk: Handler = (route) =>
  json(
    route,
    termsWith({
      lines: [milk, cream],
      source_order_id: ids.sourceOrder,
      next_dates: [FRIDAY, "2030-03-22"],
    }),
  );
const replaceOk: Handler = (route) => json(route, created());

async function openEdit(
  page: Page,
  query = "",
  heading = "Edit standing order",
) {
  await page.goto(`/schedules/${id}/edit${query}`);
  await expect(
    page.getByRole("heading", { name: heading, level: 1 }),
  ).toBeVisible();
}
const termsRegion = (page: Page) => page.getByRole("region", { name: "Terms" });

test("the form is prefilled from the standing order and the lines are read-only", async ({
  page,
}) => {
  await mockApi(page, { [GET]: getSchedule(active), [PREVIEW]: previewOk });
  await openEdit(page);
  await expect(page.getByRole("radio", { name: "Weekly" })).toBeChecked();
  await expect(page.getByLabel("First run date")).toHaveValue(FRIDAY);

  const products = page.getByRole("region", { name: "Products" });
  await expect(products).toContainText("Whole milk 10 L");
  await expect(products).toContainText("Cream 1 L");
  await expect(products).toContainText("cannot be changed here");
  await expect(products.getByRole("spinbutton")).toHaveCount(0);

  const milkRules = page.getByRole("group", { name: "Whole milk 10 L" });
  await expect(milkRules.getByLabel("Accepted price range (%)")).toHaveValue(
    "7.50",
  );
  await expect(milkRules.getByText("Organic whole milk 10 L")).toBeVisible();
  const creamRules = page.getByRole("group", { name: "Cream 1 L" });
  await expect(creamRules.getByLabel("Accepted price range (%)")).toHaveValue(
    "0.00",
  );
});

test("preview then replace posts the full new terms and opens the new standing order", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [GET]: getSchedule(active),
    [PREVIEW]: previewOk,
    [REPLACE]: replaceOk,
    [SUCCESSOR]: detailHandler,
  });
  await openEdit(page);
  await page.getByRole("radio", { name: "Every 4 days" }).check();
  await page.getByRole("button", { name: "Preview terms" }).click();
  await expect(termsRegion(page)).toBeVisible();

  // The ceiling starts at the one already agreed.
  await expect(page.getByLabel("Price ceiling per run (EUR)")).toHaveValue(
    "150.00",
  );
  const replace = page.getByRole("button", { name: "Replace standing order" });
  await expect(replace).toBeDisabled();
  await page.getByLabel(AUTH).check();
  await replace.click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));

  const lineRules = {
    [milk.product_id]: {
      accepted_substitutes: ["464398"],
      price_range_pct: "7.50",
    },
    [cream.product_id]: { accepted_substitutes: [], price_range_pct: "0.00" },
  };
  expect(api.bodies(PREVIEW)).toEqual([
    {
      recurrence: { kind: "days", interval: 4, every_weeks: 1 },
      first_run_date: FRIDAY,
      line_rules: lineRules,
    },
  ]);
  expect(api.bodies(REPLACE)).toEqual([
    {
      recurrence: { kind: "days", interval: 4, every_weeks: 1 },
      first_run_date: FRIDAY,
      line_rules: lineRules,
      price_ceiling_gross: "150.00",
      agreed_terms_fingerprint: "f".repeat(64),
      idempotency_key: expect.stringMatching(/^customer-.{8,}/),
    },
  ]);
  expect(api.unmocked).toEqual([]);
});

test("loading, a missing standing order and an expired session", async ({
  page,
}) => {
  await mockApi(page, {
    [GET]: async (route) => {
      await delay(500);
      return problem(route, 404, "NOT_FOUND", "Standing order not found.");
    },
  });
  await page.goto(`/schedules/${id}/edit`);
  await expect(page.getByRole("status")).toContainText("Loading");
  await expect(page.getByRole("alert")).toContainText(
    "We could not find this standing order.",
  );
  await expect(
    page.getByRole("link", { name: "Back to standing orders" }),
  ).toHaveAttribute("href", "/schedules");
});

test("a load failure other than not-found shows the server message", async ({
  page,
}) => {
  await mockApi(page, {
    [GET]: (route) => problem(route, 500, "INTERNAL", "Something broke."),
  });
  await page.goto(`/schedules/${id}/edit`);
  await expect(page.getByRole("alert")).toContainText("Something broke.");
});

test("an expired session while loading sends the buyer to sign in", async ({
  page,
}) => {
  await mockApi(page, {
    [GET]: (route) =>
      problem(route, 401, "UNAUTHENTICATED", "Sign in to continue."),
  });
  await page.goto(`/schedules/${id}/edit`);
  await expect(page).toHaveURL(/\/login/);
});

test("an expired session on replace sends the buyer to sign in", async ({
  page,
}) => {
  await mockApi(page, {
    [GET]: getSchedule(active),
    [PREVIEW]: previewOk,
    [REPLACE]: (route) =>
      problem(route, 401, "UNAUTHENTICATED", "Sign in to continue."),
  });
  await openEdit(page);
  await page.getByRole("button", { name: "Preview terms" }).click();
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Replace standing order" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("a paused standing order can be edited too", async ({ page }) => {
  await mockApi(page, {
    [GET]: getSchedule({ ...active, status: "paused" }),
    [PREVIEW]: previewOk,
  });
  await openEdit(page);
  await expect(
    page.getByRole("button", { name: "Preview terms" }),
  ).toBeEnabled();
});

for (const status of ["cancelled", "expired"] as const) {
  test(`a ${status} standing order cannot be edited`, async ({ page }) => {
    await mockApi(page, { [GET]: getSchedule({ ...active, status }) });
    await openEdit(page);
    await expect(page.getByRole("alert")).toContainText(
      `A ${status} standing order cannot be changed.`,
    );
    await expect(
      page.getByRole("button", { name: "Preview terms" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("link", {
        name: "Back to the standing order",
        exact: true,
      }),
    ).toHaveAttribute("href", `/schedules/${id}`);
  });
}

test("a standing order that was already replaced links to its successor", async ({
  page,
}) => {
  await mockApi(page, {
    [GET]: getSchedule({
      ...active,
      status: "superseded",
      replaced_by: ids.successor,
    }),
  });
  await openEdit(page);
  await expect(page.getByRole("alert")).toContainText("already been replaced");
  await expect(
    page.getByRole("link", { name: "Open the new standing order" }),
  ).toHaveAttribute("href", `/schedules/${ids.successor}`);
});

test("SCHEDULE_NOT_ACTIVE on replace reloads the standing order and explains", async ({
  page,
}) => {
  let cancelled = false;
  const api = await mockApi(page, {
    [GET]: (route) =>
      json(
        route,
        detail(cancelled ? { ...active, status: "cancelled" } : active),
      ),
    [PREVIEW]: previewOk,
    [REPLACE]: (route) => {
      cancelled = true;
      return problem(
        route,
        409,
        "SCHEDULE_NOT_ACTIVE",
        "A cancelled standing order cannot be changed.",
      );
    },
  });
  await openEdit(page);
  await page.getByRole("button", { name: "Preview terms" }).click();
  await page.getByLabel(AUTH).check();
  const loadsBefore = api.bodies(GET).length;
  await page.getByRole("button", { name: "Replace standing order" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "This standing order was changed elsewhere and is now cancelled.",
  );
  await expect(
    page.getByRole("button", { name: "Replace standing order" }),
  ).toHaveCount(0);
  expect(api.bodies(GET).length).toBeGreaterThan(loadsBefore);
});

test("SCHEDULE_TERMS_CHANGED on replace previews again once and asks again", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [GET]: getSchedule(active),
    [PREVIEW]: (route, _b, nth) =>
      json(
        route,
        termsWith({
          lines: [milk, cream],
          gross_total: nth === 0 ? "132.24" : "135.00",
          terms_fingerprint: (nth === 0 ? "f" : "d").repeat(64),
        }),
      ),
    [REPLACE]: (route, _b, nth) =>
      nth === 0
        ? problem(route, 409, "SCHEDULE_TERMS_CHANGED", "Prices changed.")
        : json(route, created()),
    [SUCCESSOR]: detailHandler,
  });
  await openEdit(page);
  await page.getByRole("button", { name: "Preview terms" }).click();
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Replace standing order" }).click();
  await expect(
    page.getByText("Prices or availability changed. Review the new terms."),
  ).toBeVisible();
  await expect(termsRegion(page).getByText("€135.00").first()).toBeVisible();
  await expect(page.getByLabel(AUTH)).not.toBeChecked();
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Replace standing order" }).click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));
  expect(api.bodies(PREVIEW)).toHaveLength(2);
  expect(api.bodies(REPLACE)[1]?.agreed_terms_fingerprint).toBe("d".repeat(64));
});

test("an agreed ceiling below the new total is flagged before replacing", async ({
  page,
}) => {
  await mockApi(page, {
    [GET]: getSchedule(active),
    [PREVIEW]: (route) =>
      json(route, termsWith({ lines: [milk, cream], gross_total: "160.00" })),
  });
  await openEdit(page);
  await page.getByRole("button", { name: "Preview terms" }).click();
  await page.getByLabel(AUTH).check();
  await expect(
    page.getByText("The ceiling must be at least the total of €160.00."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Replace standing order" }),
  ).toBeDisabled();
  await page.getByLabel("Price ceiling per run (EUR)").fill("160");
  await expect(
    page.getByRole("button", { name: "Replace standing order" }),
  ).toBeEnabled();
});

test("SCHEDULE_CEILING_TOO_LOW and SCHEDULE_NOT_REORDERABLE keep their own places", async ({
  page,
}) => {
  await mockApi(page, {
    [GET]: getSchedule(active),
    [PREVIEW]: previewOk,
    [REPLACE]: (route, _b, nth) =>
      nth === 0
        ? problem(route, 422, "SCHEDULE_CEILING_TOO_LOW", "Ceiling too low.")
        : problem(
            route,
            422,
            "SCHEDULE_NOT_REORDERABLE",
            "Cannot be repeated.",
            { blocking_reasons: ["Cream 1 L was withdrawn."] },
          ),
  });
  await openEdit(page);
  await page.getByRole("button", { name: "Preview terms" }).click();
  await page.getByLabel(AUTH).check();
  const replace = page.getByRole("button", { name: "Replace standing order" });
  await replace.click();
  await expect(page.getByLabel("Price ceiling per run (EUR)")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.getByText("Ceiling too low.")).toBeVisible();
  await replace.click();
  await expect(page.getByRole("alert")).toContainText(
    "Cream 1 L was withdrawn.",
  );
  await expect(replace).toBeDisabled();
});

test.describe("restart after a disruption", () => {
  test("the buyer picks the confirmed revised order from a list of placed orders", async ({
    page,
  }) => {
    const api = await mockApi(page, {
      [GET]: getSchedule(stopped),
      [ORDERS]: (route) => json(route, ordersPage(placedOrders)),
      [PREVIEW]: previewOk,
      [REPLACE]: replaceOk,
      [SUCCESSOR]: detailHandler,
    });
    await openEdit(page, "", RESTART);
    await expect(
      page.getByText("outside the range you accepted"),
    ).toBeVisible();
    const select = page.getByLabel("Revised order to restart from");
    const labels = await select.locator("option").allTextContents();
    // Only placed orders are offered (not scheduled, pending or cancelled ones).
    expect(labels.filter((l) => l.includes("Hotel breakfast"))).toHaveLength(2);
    expect(labels.join("|")).not.toContain("Carbonara");
    expect(labels.join("|")).not.toContain("Old basket");
    expect(labels.join("|")).not.toContain("Weekend cheeses");

    const preview = page.getByRole("button", { name: "Preview terms" });
    await expect(preview).toBeDisabled();
    await expect(
      page.getByText("Choose the confirmed revised order to restart from."),
    ).toBeVisible();
    await select.selectOption(revisedOrderId);
    await expect(preview).toBeEnabled();
    await preview.click();
    await expect(termsRegion(page)).toBeVisible();
    await page.getByLabel(AUTH).check();
    await page.getByRole("button", { name: "Restart standing order" }).click();
    await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));

    expect(api.bodies(ORDERS).length).toBeGreaterThan(0);
    const [previewBody] = api.bodies(PREVIEW);
    expect(previewBody).toMatchObject({
      source_order_id: revisedOrderId,
      first_run_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    });
    // The lines of the new order are not the old ones: no stale rules are sent.
    expect(previewBody).not.toHaveProperty("line_rules");
    expect(api.bodies(REPLACE)[0]).toMatchObject({
      source_order_id: revisedOrderId,
      agreed_terms_fingerprint: "f".repeat(64),
      price_ceiling_gross: "132.24",
    });
  });

  test("?restart=1 on an active standing order uses the same order select", async ({
    page,
  }) => {
    await mockApi(page, {
      [GET]: getSchedule(active),
      [ORDERS]: (route) => json(route, ordersPage(placedOrders)),
    });
    await openEdit(page, "?restart=1", RESTART);
    await expect(
      page.getByLabel("Revised order to restart from"),
    ).toBeVisible();
  });

  test("a restart without any placed order points to the past orders", async ({
    page,
  }) => {
    await mockApi(page, {
      [GET]: getSchedule(stopped),
      [ORDERS]: (route) => json(route, ordersPage([orders[0]!, orders[2]!])),
    });
    await openEdit(page, "", RESTART);
    await expect(page.getByText("No placed orders yet.")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Preview terms" }),
    ).toBeDisabled();
  });

  test("an order list failure is shown and can be retried", async ({
    page,
  }) => {
    let failing = true;
    await mockApi(page, {
      [GET]: getSchedule(stopped),
      [ORDERS]: (route) =>
        failing
          ? problem(route, 500, "INTERNAL", "Orders unavailable.")
          : json(route, ordersPage(placedOrders)),
    });
    await openEdit(page, "", RESTART);
    await expect(page.getByRole("alert")).toContainText("Orders unavailable.");
    failing = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(
      page.getByLabel("Revised order to restart from"),
    ).toBeVisible();
  });
});

test.describe("mobile 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("edit and replace fit the screen", async ({ page }) => {
    const api = await mockApi(page, {
      [GET]: getSchedule(active),
      [PREVIEW]: previewOk,
      [REPLACE]: replaceOk,
      [SUCCESSOR]: detailHandler,
    });
    await openEdit(page);
    const overflow = () =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
    expect(await overflow()).toBeLessThanOrEqual(0);
    await page.getByRole("button", { name: "Preview terms" }).click();
    await expect(termsRegion(page)).toBeVisible();
    await page.getByLabel(AUTH).check();
    const replace = page.getByRole("button", {
      name: "Replace standing order",
    });
    await replace.scrollIntoViewIfNeeded();
    await expect(replace).toBeInViewport();
    expect(await overflow()).toBeLessThanOrEqual(0);
    await replace.click();
    await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));
    expect(api.bodies(REPLACE)).toHaveLength(1);
  });
});
