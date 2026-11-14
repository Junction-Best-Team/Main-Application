import { expect, test, type Page } from "@playwright/test";
import { addDays, FRIDAY, MONDAY, printed } from "./support/dates";
import { cream, ids, json, milk, problem } from "./support/schedulerFixtures";
import {
  created,
  delay,
  detailHandler,
  mockApi,
  termsWith,
  type Handler,
} from "./support/scheduleEditorMock";

// "Standing order from a past order": create flow. Everything is mocked at the browser/API edge;
// nothing here proves the live backend. Dates are derived from today (see support/dates.ts).
const AUTH =
  "I agree to these exact terms, this price ceiling per run and this recurrence.";
const PREVIEW = "POST /api/schedules/preview";
const CREATE = "POST /api/schedules";
const NEW_PATH = `/schedules/new?order=${ids.sourceOrder}`;

const previewOk: Handler = (route) =>
  json(route, termsWith({ lines: [milk, cream] }));
const candidates: Handler = (route) =>
  json(route, {
    product_id: milk.product_id,
    candidates: [
      {
        product_id: "464398",
        name: "Organic whole milk 10 L",
        unit_gross: "14.10",
        sales_unit: "BIB",
      },
      {
        product_id: "464399",
        name: "Lactose-free milk 10 L",
        unit_gross: "15.20",
        sales_unit: "BIB",
      },
    ],
  });

async function openCreate(page: Page) {
  await page.goto(NEW_PATH);
  await expect(
    page.getByRole("heading", { name: "Create standing order", level: 1 }),
  ).toBeVisible();
}
async function preview(page: Page, date = FRIDAY) {
  await page.getByLabel("First run date").fill(date);
  await page.getByRole("button", { name: "Preview terms" }).click();
  await expect(page.getByRole("region", { name: "Terms" })).toBeVisible();
}
const idempotencyKey = (body: Record<string, unknown> | null) =>
  String(body?.idempotency_key);

test("preview then create posts the exact terms and opens the new standing order", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route) => json(route, created()),
    [`GET /api/schedules/${ids.successor}`]: detailHandler,
  });
  await openCreate(page);
  await preview(page);

  const termsRegion = page.getByRole("region", { name: "Terms" });
  await expect(termsRegion.getByText("Breakfast dairy")).toBeVisible();
  await expect(termsRegion.getByText("Whole milk 10 L")).toBeVisible();
  await expect(termsRegion.getByText("€109.44").first()).toBeVisible();
  await expect(termsRegion.getByText("€132.24").first()).toBeVisible();
  await expect(termsRegion.getByText("Valid until")).toBeVisible();
  await expect(
    termsRegion.getByText(printed(addDays(FRIDAY, 7))),
  ).toBeVisible();

  // The ceiling defaults to the gross total; the button waits for the explicit agreement.
  await expect(page.getByLabel("Price ceiling per run (EUR)")).toHaveValue(
    "132.24",
  );
  await expect(
    page.getByText("A run never commits above this total."),
  ).toBeVisible();
  const create = page.getByRole("button", { name: "Create standing order" });
  await expect(create).toBeDisabled();
  await page.getByLabel(AUTH).check();
  await expect(create).toBeEnabled();
  await create.click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));

  expect(api.bodies(PREVIEW)).toEqual([
    {
      order_id: ids.sourceOrder,
      recurrence: { kind: "weekdays", weekdays: [4], every_weeks: 1 },
      first_run_date: FRIDAY,
      line_rules: {},
    },
  ]);
  const [body] = api.bodies(CREATE);
  expect(body).toEqual({
    order_id: ids.sourceOrder,
    recurrence: { kind: "weekdays", weekdays: [4], every_weeks: 1 },
    first_run_date: FRIDAY,
    line_rules: {},
    price_ceiling_gross: "132.24",
    agreed_terms_fingerprint: "f".repeat(64),
    idempotency_key: expect.stringMatching(/^customer-.{8,}/),
  });
  expect(api.unmocked).toEqual([]);
});

test("the CSRF token from the session is sent on preview and create", async ({
  page,
}) => {
  const seen: string[] = [];
  const wrap =
    (handler: Handler): Handler =>
    (route, body, nth) => {
      seen.push(route.request().headers()["x-csrf-token"] ?? "");
      return handler(route, body, nth);
    };
  await mockApi(page, {
    [PREVIEW]: wrap(previewOk),
    [CREATE]: wrap((route) => json(route, created())),
    [`GET /api/schedules/${ids.successor}`]: detailHandler,
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));
  expect(seen).toEqual(["test-csrf", "test-csrf"]);
});

test("shows a loading state while prices are being checked", async ({
  page,
}) => {
  await mockApi(page, {
    [PREVIEW]: async (route) => {
      await delay(600);
      return json(route, termsWith({ lines: [milk, cream] }));
    },
  });
  await openCreate(page);
  await page.getByLabel("First run date").fill(FRIDAY);
  const button = page.getByRole("button", { name: "Preview terms" });
  await button.click();
  await expect(page.getByRole("status")).toContainText(
    "Checking prices and availability",
  );
  await expect(button).toBeDisabled();
  await expect(page.getByRole("region", { name: "Terms" })).toBeVisible();
});

test("without an order in the link it explains how to start", async ({
  page,
}) => {
  const api = await mockApi(page, {});
  await page.goto("/schedules/new");
  await expect(page.getByRole("alert")).toContainText("Choose a past order");
  await expect(
    page.getByRole("link", { name: "Open past orders" }),
  ).toHaveAttribute("href", "/purchases");
  expect(api.calls).toEqual([]);
});

test("an expired session on preview sends the buyer to sign in", async ({
  page,
}) => {
  await mockApi(page, {
    [PREVIEW]: (route) =>
      problem(route, 401, "UNAUTHENTICATED", "Sign in to continue."),
  });
  await openCreate(page);
  await page.getByLabel("First run date").fill(FRIDAY);
  await page.getByRole("button", { name: "Preview terms" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test.describe("recurrence presets send the exact Recurrence JSON", () => {
  const cases: {
    name: string;
    date: string;
    pick: (page: Page) => Promise<void>;
    expected: unknown;
  }[] = [
    {
      name: "weekly uses the weekday of the first run date",
      date: FRIDAY,
      pick: async (page) => {
        await page.getByRole("radio", { name: "Weekly" }).check();
      },
      expected: { kind: "weekdays", weekdays: [4], every_weeks: 1 },
    },
    {
      name: "twice a week with two weekdays",
      date: FRIDAY,
      pick: async (page) => {
        await page.getByRole("radio", { name: "Twice a week" }).check();
        const days = page.getByRole("group", { name: "Weekdays" });
        await days.getByLabel("Tuesday").check();
        await days.getByLabel("Friday").check();
      },
      expected: { kind: "weekdays", weekdays: [1, 4], every_weeks: 1 },
    },
    {
      name: "every other week",
      date: MONDAY,
      pick: async (page) => {
        await page.getByRole("radio", { name: "Every other week" }).check();
      },
      expected: { kind: "weekdays", weekdays: [0], every_weeks: 2 },
    },
    {
      name: "every 4 days",
      date: FRIDAY,
      pick: async (page) => {
        await page.getByRole("radio", { name: "Every 4 days" }).check();
      },
      expected: { kind: "days", interval: 4, every_weeks: 1 },
    },
    {
      name: "custom weekdays every 3 weeks",
      date: FRIDAY,
      pick: async (page) => {
        await page.getByRole("radio", { name: "Custom" }).check();
        await page.getByRole("radio", { name: "Days of the week" }).check();
        const days = page.getByRole("group", { name: "Weekdays" });
        await days.getByLabel("Sunday").check();
        await days.getByLabel("Wednesday").check();
        await page.getByLabel("Repeat every (weeks)").fill("3");
      },
      expected: { kind: "weekdays", weekdays: [2, 6], every_weeks: 3 },
    },
    {
      name: "custom every 10 days",
      date: FRIDAY,
      pick: async (page) => {
        await page.getByRole("radio", { name: "Custom" }).check();
        await page.getByRole("radio", { name: "Every few days" }).check();
        await page.getByLabel("Repeat every (days)").fill("10");
      },
      expected: { kind: "days", interval: 10, every_weeks: 1 },
    },
  ];
  for (const c of cases) {
    test(c.name, async ({ page }) => {
      const api = await mockApi(page, { [PREVIEW]: previewOk });
      await openCreate(page);
      await page.getByLabel("First run date").fill(c.date);
      await c.pick(page);
      await page.getByRole("button", { name: "Preview terms" }).click();
      await expect(page.getByRole("region", { name: "Terms" })).toBeVisible();
      expect(api.bodies(PREVIEW)[0]?.recurrence).toEqual(c.expected);
    });
  }

  test("twice a week needs two different weekdays and custom needs a valid number", async ({
    page,
  }) => {
    const api = await mockApi(page, { [PREVIEW]: previewOk });
    await openCreate(page);
    await page.getByLabel("First run date").fill(FRIDAY);
    const button = page.getByRole("button", { name: "Preview terms" });
    await page.getByRole("radio", { name: "Twice a week" }).check();
    await page
      .getByRole("group", { name: "Weekdays" })
      .getByLabel("Monday")
      .check();
    await expect(button).toBeDisabled();
    await expect(page.getByText("Choose exactly two weekdays.")).toBeVisible();
    await page.getByRole("radio", { name: "Custom" }).check();
    await page.getByRole("radio", { name: "Every few days" }).check();
    await page.getByLabel("Repeat every (days)").fill("366");
    await expect(button).toBeDisabled();
    await expect(
      page.getByText("Enter a whole number from 1 to 365."),
    ).toBeVisible();
    expect(api.calls).toEqual([]);
  });
});

// The first run date must be tomorrow or later and at most 365 days ahead (owner Q-103). The
// allowed range is shown in the form. Dates are Helsinki calendar dates.
const helsinkiDay = (offsetDays: number) =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Helsinki" }).format(
    new Date(Date.now() + offsetDays * 86_400_000),
  );

test("the form shows the allowed range for the first run date", async ({
  page,
}) => {
  await mockApi(page, { [PREVIEW]: previewOk });
  await openCreate(page);
  const input = page.getByLabel("First run date");
  await expect(input).toHaveAttribute("min", helsinkiDay(1));
  await expect(input).toHaveAttribute("max", helsinkiDay(365));
  await expect(page.getByText(/Allowed: .* to .*/)).toBeVisible();
});

for (const [name, offset] of [
  ["in the past", -3],
  ["today", 0],
  ["more than 365 days ahead", 366],
] as const) {
  test(`a first run date ${name} cannot be previewed`, async ({ page }) => {
    const api = await mockApi(page, { [PREVIEW]: previewOk });
    await openCreate(page);
    await page.getByLabel("First run date").fill(helsinkiDay(offset));
    await expect(
      page.getByText(/The first run date must be from .* to .*\./),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Preview terms" }),
    ).toBeDisabled();
    expect(api.calls).toEqual([]);
  });
}

for (const offset of [1, 365]) {
  test(`a first run date ${offset} day(s) ahead is accepted`, async ({
    page,
  }) => {
    await mockApi(page, { [PREVIEW]: previewOk });
    await openCreate(page);
    await page.getByLabel("First run date").fill(helsinkiDay(offset));
    await expect(page.getByText(/The first run date must be from/)).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", { name: "Preview terms" }),
    ).toBeEnabled();
  });
}

test("terms become invalid when any input changes and need a new preview", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route) => json(route, created()),
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  await expect(
    page.getByRole("button", { name: "Create standing order" }),
  ).toBeEnabled();

  await page.getByRole("radio", { name: "Every 4 days" }).check();
  await expect(page.getByRole("region", { name: "Terms" })).toHaveCount(0);
  await expect(page.getByText("You changed the terms.")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create standing order" }),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Preview terms" }).click();
  await expect(page.getByRole("region", { name: "Terms" })).toBeVisible();
  // The agreement belongs to the terms the customer saw: it has to be given again.
  await expect(page.getByLabel(AUTH)).not.toBeChecked();
  expect(api.bodies(PREVIEW)).toHaveLength(2);
  expect(api.bodies(CREATE)).toHaveLength(0);
});

test("the same idempotency key is reused on retry and a new one follows a new preview", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route, _body, nth) =>
      nth === 0
        ? problem(route, 503, "UPSTREAM_UNAVAILABLE", "Try again in a moment.")
        : json(route, created()),
    [`GET /api/schedules/${ids.successor}`]: detailHandler,
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  const create = page.getByRole("button", { name: "Create standing order" });
  await create.click();
  await expect(page.getByRole("alert")).toContainText("Try again in a moment.");
  // The terms stay and the agreement is kept: it is the same attempt.
  await expect(page.getByLabel(AUTH)).toBeChecked();
  await create.click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));
  const [first, second] = api.bodies(CREATE);
  expect(idempotencyKey(first)).toMatch(/^customer-/);
  expect(idempotencyKey(second)).toBe(idempotencyKey(first));
});

test("changing an input and previewing again generates a new idempotency key", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route, _body, nth) =>
      nth === 0
        ? problem(route, 503, "UPSTREAM_UNAVAILABLE", "Try again in a moment.")
        : json(route, created()),
    [`GET /api/schedules/${ids.successor}`]: detailHandler,
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("radio", { name: "Every 4 days" }).check();
  await page.getByRole("button", { name: "Preview terms" }).click();
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));
  const [first, second] = api.bodies(CREATE);
  expect(idempotencyKey(second)).not.toBe(idempotencyKey(first));
});

test("a ceiling below the gross total is blocked in the browser", async ({
  page,
}) => {
  const api = await mockApi(page, { [PREVIEW]: previewOk });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  const ceiling = page.getByLabel("Price ceiling per run (EUR)");
  const create = page.getByRole("button", { name: "Create standing order" });
  await ceiling.fill("120.00");
  await expect(
    page.getByText("The ceiling must be at least the total of €132.24."),
  ).toBeVisible();
  await expect(create).toBeDisabled();
  await ceiling.fill("132.245");
  await expect(
    page.getByText("Enter an amount with up to 2 decimals."),
  ).toBeVisible();
  await expect(create).toBeDisabled();
  await ceiling.fill("140,5");
  await expect(create).toBeEnabled();
  expect(api.bodies(CREATE)).toHaveLength(0);
});

test("a comma or short ceiling is sent as a two-decimal string", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route) => json(route, created()),
    [`GET /api/schedules/${ids.successor}`]: detailHandler,
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel("Price ceiling per run (EUR)").fill("140,5");
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));
  expect(api.bodies(CREATE)[0]?.price_ceiling_gross).toBe("140.50");
});

test("SCHEDULE_CEILING_TOO_LOW from the server is a field error on the ceiling", async ({
  page,
}) => {
  await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route) =>
      problem(
        route,
        422,
        "SCHEDULE_CEILING_TOO_LOW",
        "The ceiling is below the gross total of these terms.",
      ),
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();
  const ceiling = page.getByLabel("Price ceiling per run (EUR)");
  await expect(ceiling).toHaveAttribute("aria-invalid", "true");
  await expect(
    page.getByText("The ceiling is below the gross total of these terms."),
  ).toBeVisible();
});

test("SCHEDULE_TERMS_CHANGED clears the terms and previews again once", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [PREVIEW]: (route, _body, nth) =>
      json(
        route,
        nth === 0
          ? termsWith({ lines: [milk, cream] })
          : termsWith({
              lines: [milk, cream],
              gross_total: "140.00",
              terms_fingerprint: "e".repeat(64),
            }),
      ),
    [CREATE]: (route, _body, nth) =>
      nth === 0
        ? problem(route, 409, "SCHEDULE_TERMS_CHANGED", "Prices changed.")
        : json(route, created()),
    [`GET /api/schedules/${ids.successor}`]: detailHandler,
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();

  await expect(
    page.getByText("Prices or availability changed. Review the new terms."),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Terms" }).getByText("€140.00").first(),
  ).toBeVisible();
  expect(api.bodies(PREVIEW)).toHaveLength(2);
  // New terms need a new agreement, and the old ceiling no longer covers the new total.
  await expect(page.getByLabel(AUTH)).not.toBeChecked();
  await expect(
    page.getByRole("button", { name: "Create standing order" }),
  ).toBeDisabled();
  await expect(page.getByLabel("Price ceiling per run (EUR)")).toHaveValue(
    "140.00",
  );
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));
  const [first, second] = api.bodies(CREATE);
  expect(first?.agreed_terms_fingerprint).toBe("f".repeat(64));
  expect(second?.agreed_terms_fingerprint).toBe("e".repeat(64));
  expect(idempotencyKey(second)).not.toBe(idempotencyKey(first));
});

test("SCHEDULE_NOT_REORDERABLE shows the message and blocking reasons and disables create", async ({
  page,
}) => {
  await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route) =>
      problem(
        route,
        422,
        "SCHEDULE_NOT_REORDERABLE",
        "This order cannot be repeated as it stands.",
        {
          blocking_reasons: [
            { code: "PRODUCT_WITHDRAWN", message: "Cream 1 L was withdrawn." },
          ],
        },
      ),
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText(
    "This order cannot be repeated as it stands.",
  );
  await expect(alert).toContainText("Cream 1 L was withdrawn.");
  await expect(
    page.getByRole("button", { name: "Create standing order" }),
  ).toBeDisabled();
});

test("a preview that is not ready to commit lists why and disables create", async ({
  page,
}) => {
  await mockApi(page, {
    [PREVIEW]: (route) =>
      json(
        route,
        termsWith({
          lines: [milk, cream],
          policy_outcome: "approval_required",
          blocking_reasons: [
            { code: "PRODUCT_SCOPE", message: "Cream is outside your scope." },
          ],
        }),
      ),
  });
  await openCreate(page);
  await page.getByLabel("First run date").fill(FRIDAY);
  await page.getByRole("button", { name: "Preview terms" }).click();
  const termsRegion = page.getByRole("region", { name: "Terms" });
  await expect(termsRegion).toContainText("Cream is outside your scope.");
  await expect(termsRegion).toContainText("cannot be created");
  await expect(
    page.getByRole("button", { name: "Create standing order" }),
  ).toBeDisabled();
  await expect(page.getByLabel(AUTH)).toBeDisabled();
});

test("SCHEDULE_LIMIT explains the maximum of 20", async ({ page }) => {
  await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route) =>
      problem(route, 429, "SCHEDULE_LIMIT", "Too many standing orders."),
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "You already have the maximum of 20 active standing orders. Cancel one first.",
  );
});

test("IDEMPOTENCY_CONFLICT generates a new key and asks to review and submit again", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route, _body, nth) =>
      nth === 0
        ? problem(route, 409, "IDEMPOTENCY_CONFLICT", "Key already used.")
        : json(route, created()),
    [`GET /api/schedules/${ids.successor}`]: detailHandler,
  });
  await openCreate(page);
  await preview(page);
  await page.getByLabel(AUTH).check();
  const create = page.getByRole("button", { name: "Create standing order" });
  await create.click();
  await expect(page.getByRole("alert")).toContainText(
    "Review the terms and submit again.",
  );
  // Terms are still valid; the agreement has to be given again with the new key.
  await expect(page.getByLabel(AUTH)).not.toBeChecked();
  await page.getByLabel(AUTH).check();
  await create.click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));
  const [first, second] = api.bodies(CREATE);
  expect(idempotencyKey(second)).not.toBe(idempotencyKey(first));
  expect(api.bodies(PREVIEW)).toHaveLength(1);
});

test("a missing order is a plain message with a link to the past orders", async ({
  page,
}) => {
  await mockApi(page, {
    [PREVIEW]: (route) => problem(route, 404, "NOT_FOUND", "Order not found."),
  });
  await openCreate(page);
  await page.getByLabel("First run date").fill(FRIDAY);
  await page.getByRole("button", { name: "Preview terms" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "We could not find this order.",
  );
  await expect(
    page.getByRole("alert").getByRole("link", { name: "Open past orders" }),
  ).toHaveAttribute("href", "/purchases");
});

test("INVALID_FIRST_RUN_DATE, INVALID_RECURRENCE and INVALID_LINE_RULE show the server message", async ({
  page,
}) => {
  const codes = [
    ["INVALID_FIRST_RUN_DATE", "The first run date is in the past."],
    ["INVALID_RECURRENCE", "This pattern has no date within a year."],
    ["INVALID_LINE_RULE", "Line rule for 464306 is not valid."],
  ] as const;
  await mockApi(page, {
    [PREVIEW]: (route, _body, nth) =>
      problem(route, 422, codes[nth]![0], codes[nth]![1]),
  });
  await openCreate(page);
  await page.getByLabel("First run date").fill(FRIDAY);
  const button = page.getByRole("button", { name: "Preview terms" });
  for (const [, message] of codes) {
    await button.click();
    await expect(page.getByRole("alert")).toContainText(message);
  }
});

test("substitutes are loaded lazily, limited to five and sent with the price range", async ({
  page,
}) => {
  const api = await mockApi(page, {
    [PREVIEW]: previewOk,
    [CREATE]: (route) => json(route, created()),
    "GET /api/schedules/substitute-candidates": candidates,
    [`GET /api/schedules/${ids.successor}`]: detailHandler,
  });
  await openCreate(page);
  await preview(page);
  // Nothing is requested before a line is opened.
  expect(api.bodies("GET /api/schedules/substitute-candidates")).toHaveLength(
    0,
  );

  const milkRules = page.getByRole("group", { name: "Whole milk 10 L" });
  await milkRules.getByRole("button", { name: "Choose substitutes" }).click();
  await expect(milkRules.getByLabel("Organic whole milk 10 L")).toBeVisible();
  await expect(milkRules.getByText("€14.10")).toBeVisible();
  expect(
    api.calls.filter(
      (c) => c.key === "GET /api/schedules/substitute-candidates",
    ),
  ).toHaveLength(1);
  await milkRules.getByLabel("Organic whole milk 10 L").check();
  await milkRules.getByLabel("Accepted price range (%)").fill("7.5");
  await expect(
    page.getByText(
      "A substitute or price within this range is used automatically and noted on the order. Otherwise the standing order stops and starts a chat.",
    ),
  ).toBeVisible();

  // Changing a rule invalidates the previewed terms.
  await expect(page.getByRole("region", { name: "Terms" })).toHaveCount(0);
  await page.getByRole("button", { name: "Preview terms" }).click();
  await expect(page.getByRole("region", { name: "Terms" })).toBeVisible();
  await page.getByLabel(AUTH).check();
  await page.getByRole("button", { name: "Create standing order" }).click();
  await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));

  const lineRules = {
    [milk.product_id]: {
      accepted_substitutes: ["464398"],
      price_range_pct: "7.50",
    },
    [cream.product_id]: { accepted_substitutes: [], price_range_pct: "0.00" },
  };
  expect(api.bodies(PREVIEW)[1]?.line_rules).toEqual(lineRules);
  expect(api.bodies(CREATE)[0]?.line_rules).toEqual(lineRules);
});

test("at most five substitutes can be chosen", async ({ page }) => {
  const many = Array.from({ length: 7 }, (_, i) => ({
    product_id: `9000${i}`,
    name: `Candidate ${i + 1}`,
    unit_gross: "10.00",
    sales_unit: "BIB",
  }));
  await mockApi(page, {
    [PREVIEW]: previewOk,
    "GET /api/schedules/substitute-candidates": (route) =>
      json(route, { product_id: cream.product_id, candidates: many }),
  });
  await openCreate(page);
  await preview(page);
  const creamRules = page.getByRole("group", { name: "Cream 1 L" });
  await creamRules.getByRole("button", { name: "Choose substitutes" }).click();
  for (let i = 1; i <= 5; i++)
    await creamRules.getByLabel(`Candidate ${i}`).check();
  await expect(creamRules.getByLabel("Candidate 6")).toBeDisabled();
  await expect(
    creamRules.getByText("You can accept up to 5 substitutes."),
  ).toBeVisible();
  await creamRules.getByLabel("Candidate 1").uncheck();
  await expect(creamRules.getByLabel("Candidate 6")).toBeEnabled();
});

test("a product without catalog substitutes says so, and a failed lookup can be retried", async ({
  page,
}) => {
  let milkFails = true;
  await mockApi(page, {
    [PREVIEW]: previewOk,
    "GET /api/schedules/substitute-candidates": (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("product_id") === cream.product_id)
        return json(route, { product_id: cream.product_id, candidates: [] });
      return milkFails
        ? problem(route, 500, "INTERNAL", "Lookup failed.")
        : json(route, { product_id: milk.product_id, candidates: [] });
    },
  });
  await openCreate(page);
  await preview(page);
  const creamRules = page.getByRole("group", { name: "Cream 1 L" });
  await creamRules.getByRole("button", { name: "Choose substitutes" }).click();
  await expect(
    creamRules.getByText("No catalog substitutes for this product."),
  ).toBeVisible();

  const milkRules = page.getByRole("group", { name: "Whole milk 10 L" });
  await milkRules.getByRole("button", { name: "Choose substitutes" }).click();
  await expect(milkRules.getByRole("alert")).toContainText("Lookup failed.");
  milkFails = false;
  await milkRules.getByRole("button", { name: "Try again" }).click();
  await expect(
    milkRules.getByText("No catalog substitutes for this product."),
  ).toBeVisible();
});

test("an invalid price range blocks the preview", async ({ page }) => {
  await mockApi(page, { [PREVIEW]: previewOk });
  await openCreate(page);
  await preview(page);
  const milkRules = page.getByRole("group", { name: "Whole milk 10 L" });
  await milkRules.getByLabel("Accepted price range (%)").fill("101");
  await expect(
    milkRules.getByText(
      "Enter a percentage from 0 to 100 with up to 2 decimals.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Preview terms" }),
  ).toBeDisabled();
});

test.describe("mobile 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("the whole flow fits the screen and creates the standing order", async ({
    page,
  }) => {
    const api = await mockApi(page, {
      [PREVIEW]: previewOk,
      [CREATE]: (route) => json(route, created()),
      [`GET /api/schedules/${ids.successor}`]: detailHandler,
    });
    await openCreate(page);
    await preview(page);
    await page.getByRole("radio", { name: "Custom" }).check();
    const overflow = () =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
    expect(await overflow()).toBeLessThanOrEqual(0);
    await page.getByRole("radio", { name: "Weekly" }).check();
    await page.getByRole("button", { name: "Preview terms" }).click();
    const milkRules = page.getByRole("group", { name: "Whole milk 10 L" });
    await milkRules.getByRole("button", { name: "Choose substitutes" }).click();
    expect(await overflow()).toBeLessThanOrEqual(0);
    await page.getByRole("button", { name: "Preview terms" }).click();
    await page.getByLabel(AUTH).check();
    const create = page.getByRole("button", { name: "Create standing order" });
    await create.scrollIntoViewIfNeeded();
    await expect(create).toBeInViewport();
    expect(await overflow()).toBeLessThanOrEqual(0);
    await create.click();
    await expect(page).toHaveURL(new RegExp(`/schedules/${ids.successor}$`));
    expect(api.bodies(CREATE)).toHaveLength(1);
  });
});
