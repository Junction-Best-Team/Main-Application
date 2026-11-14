import { expect, test, type Page } from "@playwright/test";
import type { Schedule, ScheduleRun } from "../src/shared/api/types";
import {
  committedRun,
  detail,
  disruptedRun,
  ids,
  json,
  mockSignedIn,
  pausedSchedule,
  problem,
  schedule,
  session,
  skippedRun,
  stoppedSchedule,
} from "./support/schedulerFixtures";

// List and detail screens of the standing orders. Everything is mocked at the browser/API edge.
const listUrl = /\/api\/schedules(\?|$)/;
const detailUrl = (id: string) => new RegExp(`/api/schedules/${id}(\\?|$)`);

async function mockList(
  page: Page,
  items: Schedule[],
  next: number | null = null,
) {
  await mockSignedIn(page);
  await page.route(listUrl, (route) =>
    json(route, { items, next_offset: next }),
  );
}

async function mockDetail(page: Page, s: Schedule, runs: ScheduleRun[] = []) {
  await mockSignedIn(page);
  await page.route(detailUrl(s.id), (route) => json(route, detail(s, runs)));
}

test.describe("schedule list", () => {
  test("shows each standing order with its cadence, next run, total and links", async ({
    page,
  }) => {
    await mockList(page, [schedule, pausedSchedule, stoppedSchedule]);
    await page.goto("/schedules");
    await expect(
      page.getByRole("heading", { name: "Standing orders", level: 1 }),
    ).toBeVisible();
    const cards = page.getByRole("article");
    await expect(cards).toHaveCount(3);

    const active = cards.filter({ hasText: "Breakfast dairy" });
    await expect(active.getByText("Scheduled", { exact: true })).toBeVisible();
    await expect(active).toContainText("Every week on Friday");
    await expect(active).toContainText("20 Nov 2026");
    await expect(active).toContainText("€132.24");
    await expect(active).toContainText("2 lines");
    await expect(
      active.getByRole("link", { name: "Breakfast dairy" }),
    ).toHaveAttribute("href", `/schedules/${ids.schedule}`);

    const paused = cards.filter({ hasText: "Weekend cheeses" });
    await expect(paused.getByText("Paused", { exact: true })).toBeVisible();
    await expect(paused).toContainText("Every 4 days");

    const stopped = cards.filter({ hasText: "Seasonal vegetables" });
    await expect(stopped).toContainText("Stopped, needs attention");
    await expect(stopped).toContainText("No further runs");
    await expect(stopped).toContainText("outside the range you accepted");
    await expect(stopped).toContainText("Last run: Needs your attention");
    await expect(
      stopped.getByRole("link", { name: "Open the conversation" }),
    ).toHaveAttribute("href", `/conversations/${ids.conversation}`);

    await expect(
      page.getByRole("link", { name: "Schedule an order", exact: true }),
    ).toHaveAttribute("href", "/purchases");
  });

  test("hides a stopped schedule that already has a successor", async ({
    page,
  }) => {
    await mockList(page, [
      schedule,
      {
        ...stoppedSchedule,
        id: "5e1c6c33-4a0b-4c0e-9d2b-0f1f6c0a7a09",
        title: "Old vegetables",
        replaced_by: ids.successor,
      },
      { ...schedule, id: ids.successor, title: "New vegetables" },
    ]);
    await page.goto("/schedules");
    await expect(page.getByRole("article")).toHaveCount(2);
    await expect(page.getByText("Old vegetables")).toHaveCount(0);
    await expect(page.getByText("New vegetables")).toBeVisible();
  });

  test("shows a loading status before the list arrives", async ({ page }) => {
    await mockSignedIn(page);
    await page.route(listUrl, async (route) => {
      await new Promise((r) => setTimeout(r, 600));
      await json(route, { items: [schedule], next_offset: null });
    });
    await page.goto("/schedules");
    await expect(page.getByRole("status")).toContainText(
      "Loading standing orders",
    );
    await expect(page.getByRole("article")).toHaveCount(1);
    await expect(page.getByRole("status")).toHaveCount(0);
  });

  test("empty state points to the orders page", async ({ page }) => {
    await mockList(page, []);
    await page.goto("/schedules");
    await expect(
      page.getByRole("heading", { name: "No standing orders yet" }),
    ).toBeVisible();
    await expect(page.getByRole("article")).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Schedule an order", exact: true }).last(),
    ).toHaveAttribute("href", "/purchases");
  });

  test("a failed load shows the server message, not an empty state", async ({
    page,
  }) => {
    await mockSignedIn(page);
    await page.route(listUrl, (route) =>
      problem(route, 503, "UPSTREAM_UNAVAILABLE", "Standing orders are down."),
    );
    await page.goto("/schedules");
    await expect(page.getByRole("alert")).toContainText(
      "Standing orders are down.",
    );
    await expect(page.getByText("No standing orders yet")).toHaveCount(0);
  });

  test("a network failure is a plain sentence, not the browser's raw text", async ({
    page,
  }) => {
    await mockSignedIn(page);
    await page.route(listUrl, (route) => route.abort("connectionrefused"));
    await page.goto("/schedules");
    await expect(page.getByRole("alert")).toContainText(
      "Could not reach the service. Check your connection and try again.",
    );
    await expect(page.getByRole("alert")).not.toContainText("Failed to fetch");
  });

  test("an expired session returns to sign-in", async ({ page }) => {
    await mockSignedIn(page);
    await page.route(listUrl, (route) =>
      problem(route, 401, "UNAUTHENTICATED", "Sign in to continue."),
    );
    await page.goto("/schedules");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("Show more loads the next page by offset", async ({ page }) => {
    await mockSignedIn(page);
    const offsets: (string | null)[] = [];
    await page.route(listUrl, (route) => {
      const url = new URL(route.request().url());
      const offset = url.searchParams.get("offset");
      offsets.push(offset);
      expect(url.searchParams.get("limit")).toBe("20");
      return offset === "0"
        ? json(route, { items: [schedule], next_offset: 20 })
        : json(route, {
            items: [{ ...pausedSchedule }],
            next_offset: null,
          });
    });
    await page.goto("/schedules");
    await expect(page.getByRole("article")).toHaveCount(1);
    await page.getByRole("button", { name: "Show more" }).click();
    await expect(page.getByRole("article")).toHaveCount(2);
    // Dev StrictMode may load the first page twice; the next page is requested once.
    expect(offsets.filter((o) => o !== "0")).toEqual(["20"]);
    await expect(page.getByRole("button", { name: "Show more" })).toHaveCount(
      0,
    );
  });

  test("Pause and Resume work from the card", async ({ page }) => {
    await mockList(page, [schedule]);
    const sent: Record<string, string>[] = [];
    await page.route(`**/api/schedules/${ids.schedule}/pause`, (route) => {
      sent.push(route.request().headers());
      return json(route, { ...schedule, status: "paused" });
    });
    await page.route(`**/api/schedules/${ids.schedule}/resume`, (route) =>
      json(route, schedule),
    );
    await page.goto("/schedules");
    const card = page.getByRole("article");
    await card.getByRole("button", { name: "Pause" }).click();
    await expect(card.getByText("Paused", { exact: true })).toBeVisible();
    expect(sent[0]["x-csrf-token"]).toBe(session.csrf_token);
    await card.getByRole("button", { name: "Resume" }).click();
    await expect(card.getByText("Scheduled", { exact: true })).toBeVisible();
  });

  test("cards stack and stay reachable at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockList(page, [schedule, pausedSchedule]);
    await page.goto("/schedules");
    const cards = page.getByRole("article");
    await expect(cards).toHaveCount(2);
    const a = await cards.nth(0).boundingBox();
    const b = await cards.nth(1).boundingBox();
    expect(a && b && b.y >= a.y + a.height - 1).toBe(true);
    expect(a && a.width <= 390).toBe(true);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await expect(
      page.getByRole("link", { name: "Schedule an order", exact: true }),
    ).toBeVisible();
  });
});

test.describe("schedule detail", () => {
  test("shows the terms, the agreed lines and the accepted substitutes with their range", async ({
    page,
  }) => {
    await mockDetail(page, schedule);
    await page.goto(`/schedules/${ids.schedule}`);
    await expect(
      page.getByRole("heading", { name: "Breakfast dairy", level: 1 }),
    ).toBeVisible();
    await expect(page.getByText("Scheduled", { exact: true })).toBeVisible();
    const terms = page.getByRole("region", { name: "Terms" });
    await expect(terms).toContainText("Every week on Friday");
    await expect(terms).toContainText("20 Nov 2026");
    await expect(terms).toContainText("20 Nov 2027");
    await expect(terms).toContainText("€150.00");
    await expect(terms).toContainText("€132.24");

    const lines = page.getByRole("region", { name: "Agreed lines" });
    const milkLine = lines.getByRole("listitem").filter({
      hasText: "Whole milk 10 L",
    });
    await expect(milkLine).toContainText("8 L");
    await expect(milkLine).toContainText("€13.68 per BIB incl. tax");
    await expect(milkLine).not.toContainText("per L");
    await expect(milkLine).toContainText("€109.44");
    await expect(milkLine).toContainText("Organic whole milk 10 L");
    await expect(milkLine).toContainText("7.50 %");
    await expect(lines.getByText("Cream 1 L")).toBeVisible();
    await expect(page.getByText("No runs yet")).toBeVisible();
  });

  test("run history is newest first with order link and a muted paused run", async ({
    page,
  }) => {
    await mockDetail(page, schedule, [skippedRun, committedRun]);
    await page.goto(`/schedules/${ids.schedule}`);
    const history = page.getByRole("region", { name: "Run history" });
    const runs = history.getByRole("listitem");
    await expect(runs).toHaveCount(2);
    await expect(runs.nth(0)).toContainText("9 Nov 2026");
    await expect(runs.nth(0)).toContainText("Skipped (paused)");
    await expect(runs.nth(0)).toContainText("Paused");
    await expect(runs.nth(0)).toHaveClass(/opacity-/);
    await expect(runs.nth(1)).toContainText("6 Nov 2026");
    await expect(runs.nth(1)).toContainText("Delivery 8 Nov 2026");
    await expect(runs.nth(1)).toContainText("Order placed");
    await expect(
      runs.nth(1).getByRole("link", { name: "View order" }),
    ).toHaveAttribute("href", `/purchases/${ids.proposal}`);
  });

  test("Show older runs asks for the next runs offset", async ({ page }) => {
    await mockSignedIn(page);
    const offsets: (string | null)[] = [];
    await page.route(detailUrl(ids.schedule), (route) => {
      const offset = new URL(route.request().url()).searchParams.get(
        "runs_offset",
      );
      offsets.push(offset);
      return json(
        route,
        offset === "0"
          ? { ...detail(schedule, [skippedRun]), runs_next_offset: 10 }
          : detail(schedule, [committedRun]),
      );
    });
    await page.goto(`/schedules/${ids.schedule}`);
    const runs = page
      .getByRole("region", { name: "Run history" })
      .getByRole("listitem");
    await expect(runs).toHaveCount(1);
    await page.getByRole("button", { name: "Show older runs" }).click();
    await expect(runs).toHaveCount(2);
    await expect(runs.nth(1)).toContainText("6 Nov 2026");
    expect(offsets.filter((o) => o !== "0")).toEqual(["10"]);
    await expect(
      page.getByRole("button", { name: "Show older runs" }),
    ).toHaveCount(0);
  });

  test("rarer stop reasons have a sentence and an unknown one falls back to its code", async ({
    page,
  }) => {
    const runs: ScheduleRun[] = [
      { ...disruptedRun, id: "r1", reason_code: "UPSTREAM_RATE_LIMITED" },
      { ...disruptedRun, id: "r2", reason_code: "COMMIT_BLOCKED" },
      { ...disruptedRun, id: "r3", reason_code: "RUN_FAILED" },
      { ...disruptedRun, id: "r4", reason_code: "SOMETHING_NEW" },
    ];
    await mockDetail(page, stoppedSchedule, runs);
    await page.goto(`/schedules/${ids.stoppedSchedule}`);
    const history = page.getByRole("region", { name: "Run history" });
    await expect(history).toContainText("after several automatic retries");
    await expect(history).not.toContainText(
      "will not be retried automatically",
    );
    await expect(history).toContainText("Your purchasing policy blocked");
    await expect(history).toContainText("kept failing");
    await expect(history).toContainText("Stopped (SOMETHING_NEW).");
  });

  test("a skipped run says why it was skipped", async ({ page }) => {
    const runs: ScheduleRun[] = [
      { ...skippedRun, id: "s1", reason_code: "PAUSED" },
      { ...skippedRun, id: "s2", reason_code: "AUTHORIZATION_CANCELLED" },
      { ...skippedRun, id: "s3", reason_code: "AUTHORIZATION_EXPIRED" },
    ];
    await mockDetail(page, schedule, runs);
    await page.goto(`/schedules/${ids.schedule}`);
    const history = page.getByRole("region", { name: "Run history" });
    await expect(history).toContainText("Reason: Paused");
    await expect(history).toContainText("The standing order was cancelled");
    await expect(history).toContainText("The standing order had expired");
  });

  test("further reason codes are listed: known ones as a sentence, unknown ones as the code", async ({
    page,
  }) => {
    const run: ScheduleRun = {
      ...disruptedRun,
      reason: {
        ...disruptedRun.reason,
        codes: ["PRICE_OUTSIDE_RANGE", "CEILING_EXCEEDED", "SOMETHING_NEW"],
      },
    };
    await mockDetail(page, stoppedSchedule, [run]);
    await page.goto(`/schedules/${ids.stoppedSchedule}`);
    const item = page
      .getByRole("region", { name: "Run history" })
      .getByRole("listitem")
      .first();
    const more = item.getByTestId("run-codes");
    await expect(more).toContainText(
      "The total went above the price ceiling you agreed.",
    );
    await expect(more).toContainText("SOMETHING_NEW");
    // The code that is already the main reason is not repeated.
    await expect(more).not.toContainText("moved outside the range");
  });

  test("a disrupted run shows every line status, prices and totals", async ({
    page,
  }) => {
    const run: ScheduleRun = {
      ...disruptedRun,
      reason: {
        ...disruptedRun.reason,
        lines: [
          ...(disruptedRun.reason?.lines ?? []),
          {
            product_id: "464500",
            name: "Butter 500 g",
            status: "substituted",
            agreed_gross: "4.00",
            current_gross: "4.20",
            substitute_product_id: "464501",
            note: "Same brand, new pack size",
          },
        ],
      },
    };
    await mockDetail(page, stoppedSchedule, [run]);
    await page.goto(`/schedules/${ids.stoppedSchedule}`);
    const item = page
      .getByRole("region", { name: "Run history" })
      .getByRole("listitem")
      .first();
    await expect(item).toContainText("Needs your attention");
    const milkRow = item.getByTestId("run-line").filter({
      hasText: "Whole milk 10 L",
    });
    await expect(milkRow).toContainText("Price outside your range");
    await expect(milkRow).toContainText("Agreed €13.68");
    await expect(milkRow).toContainText("now €16.40");
    await expect(
      item.getByTestId("run-line").filter({ hasText: "Cream 1 L" }),
    ).toContainText("Available at the agreed price");
    const butter = item.getByTestId("run-line").filter({
      hasText: "Butter 500 g",
    });
    await expect(butter).toContainText("Substitute used");
    await expect(butter).toContainText("464501");
    await expect(butter).toContainText("Same brand, new pack size");
    await expect(item).toContainText("Agreed total €132.24");
    await expect(item).toContainText("current total €154.00");
  });

  test("a committed run with a substitution says which one was used", async ({
    page,
  }) => {
    await mockDetail(page, schedule, [
      {
        ...committedRun,
        substitutions: [
          {
            product_id: "464306",
            name: "Whole milk 10 L",
            status: "substituted",
            substitute_product_id: "464398",
            note: "Organic whole milk 10 L",
          },
        ],
      },
    ]);
    await page.goto(`/schedules/${ids.schedule}`);
    await expect(page.getByTestId("run-line")).toContainText("Substitute used");
    await expect(page.getByTestId("run-line")).toContainText("464398");
  });

  test.describe("demo mode: Run now (demo)", () => {
    const runNowUrl = (id: string) =>
      new RegExp(`/api/schedules/${id}/run-now$`);

    test("the control is absent when the demo flag is off", async ({
      page,
    }) => {
      await mockDetail(page, schedule);
      await page.goto(`/schedules/${ids.schedule}`);
      await expect(
        page.getByRole("heading", { name: schedule.title, level: 1 }),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: /Run now/ })).toHaveCount(
        0,
      );
    });

    test("with the flag on it shows on an active schedule only, styled as a demo command", async ({
      page,
    }) => {
      await mockSignedIn(page, true);
      await page.route(detailUrl(ids.schedule), (route) =>
        json(route, detail(schedule)),
      );
      await page.route(detailUrl(ids.pausedSchedule), (route) =>
        json(route, detail(pausedSchedule)),
      );
      await page.goto(`/schedules/${ids.schedule}`);
      await expect(
        page.getByRole("button", { name: "Run now (demo)" }),
      ).toBeVisible();
      await expect(page.getByText("Demo command")).toBeVisible();
      await page.goto(`/schedules/${ids.pausedSchedule}`);
      await expect(
        page.getByRole("heading", { name: pausedSchedule.title, level: 1 }),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: /Run now/ })).toHaveCount(
        0,
      );
    });

    test("clicking it calls run-now with the CSRF token and then shows the finished run", async ({
      page,
    }) => {
      await mockSignedIn(page, true);
      let started = false;
      let csrf: string | undefined;
      await page.route(detailUrl(ids.schedule), (route) =>
        json(
          route,
          started
            ? detail({ ...schedule, last_run: committedRun }, [committedRun])
            : detail(schedule),
        ),
      );
      await page.route(runNowUrl(ids.schedule), (route) => {
        started = true;
        csrf = route.request().headers()["x-csrf-token"];
        return json(route, {
          ...schedule,
          last_run: { ...committedRun, status: "due", order_id: null },
        });
      });
      await page.goto(`/schedules/${ids.schedule}`);
      await page.getByRole("button", { name: "Run now (demo)" }).click();
      await expect(
        page
          .getByRole("region", { name: "Run history" })
          .getByText("Order placed"),
      ).toBeVisible({ timeout: 15_000 });
      expect(csrf).toBe("test-csrf");
    });

    test("a refused run says why", async ({ page }) => {
      await mockSignedIn(page, true);
      await page.route(detailUrl(ids.schedule), (route) =>
        json(route, detail(schedule)),
      );
      await page.route(runNowUrl(ids.schedule), (route) =>
        problem(route, 403, "SCHEDULE_DEMO_DISABLED", "Demo mode is off."),
      );
      await page.goto(`/schedules/${ids.schedule}`);
      await page.getByRole("button", { name: "Run now (demo)" }).click();
      await expect(page.getByRole("alert")).toContainText("Demo mode is off.");
    });
  });

  test("a run that ran late after an outage says so, as a note and not a problem", async ({
    page,
  }) => {
    const late: ScheduleRun = {
      ...committedRun,
      reason: { codes: ["RAN_LATE"], lines: [] },
    };
    await mockDetail(page, schedule, [late]);
    await page.goto(`/schedules/${ids.schedule}`);
    const item = page
      .getByRole("region", { name: "Run history" })
      .getByRole("listitem")
      .first();
    await expect(item).toContainText("Order placed");
    await expect(item).toContainText("Ran late after an outage");
    await expect(item).not.toContainText("Needs your attention");
  });

  test("a stopped schedule explains why and offers a restart from a new order", async ({
    page,
  }) => {
    await mockDetail(page, stoppedSchedule, [disruptedRun]);
    await page.goto(`/schedules/${ids.stoppedSchedule}`);
    await expect(page.getByText("Stopped, needs attention")).toBeVisible();
    await expect(
      page.getByRole("note").filter({ hasText: "stopped" }),
    ).toContainText("A price moved outside the range you accepted");
    await expect(
      page.getByRole("link", { name: "Restart from a new order" }),
    ).toHaveAttribute(
      "href",
      `/schedules/${ids.stoppedSchedule}/edit?restart=1`,
    );
    await expect(
      page.getByRole("link", { name: "Open the conversation" }).first(),
    ).toHaveAttribute("href", `/conversations/${ids.conversation}`);
    await expect(page.getByRole("button", { name: "Pause" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Edit" })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Cancel standing order" }),
    ).toBeVisible();
  });

  test("a retryable stop reason offers plain Restart", async ({ page }) => {
    await mockDetail(
      page,
      { ...stoppedSchedule, stop_reason: "UPSTREAM_UNAVAILABLE" },
      [],
    );
    await page.goto(`/schedules/${ids.stoppedSchedule}`);
    await expect(
      page.getByRole("link", { name: "Restart", exact: true }),
    ).toHaveAttribute(
      "href",
      `/schedules/${ids.stoppedSchedule}/edit?restart=1`,
    );
    await expect(
      page.getByRole("link", { name: "Restart from a new order" }),
    ).toHaveCount(0);
  });

  test("Pause then Resume updates the chip and sends the CSRF token", async ({
    page,
  }) => {
    await mockDetail(page, schedule);
    const calls: { url: string; csrf: string | undefined }[] = [];
    await page.route(
      `**/api/schedules/${ids.schedule}/pause`,
      async (route) => {
        calls.push({
          url: route.request().url(),
          csrf: route.request().headers()["x-csrf-token"],
        });
        await new Promise((r) => setTimeout(r, 300));
        await json(route, { ...schedule, status: "paused" });
      },
    );
    await page.route(`**/api/schedules/${ids.schedule}/resume`, (route) => {
      calls.push({
        url: route.request().url(),
        csrf: route.request().headers()["x-csrf-token"],
      });
      return json(route, schedule);
    });
    await page.goto(`/schedules/${ids.schedule}`);
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Pausing…" })).toBeDisabled();
    await expect(page.getByText("Paused", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Pause" })).toHaveCount(0);
    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.getByText("Scheduled", { exact: true })).toBeVisible();
    expect(calls.map((c) => c.csrf)).toEqual(["test-csrf", "test-csrf"]);
    expect(calls[0].url).toContain("/pause");
    expect(calls[1].url).toContain("/resume");
  });

  test("Edit is offered for active and paused schedules only", async ({
    page,
  }) => {
    await mockDetail(page, pausedSchedule);
    await page.goto(`/schedules/${ids.pausedSchedule}`);
    await expect(page.getByRole("link", { name: "Edit" })).toHaveAttribute(
      "href",
      `/schedules/${ids.pausedSchedule}/edit`,
    );
    await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
  });

  test("Cancel needs a confirmation and leaves a Cancelled schedule without actions", async ({
    page,
  }) => {
    await mockDetail(page, schedule);
    let cancelled = 0;
    await page.route(`**/api/schedules/${ids.schedule}/cancel`, (route) => {
      cancelled += 1;
      return json(route, {
        ...schedule,
        status: "cancelled",
        next_run_date: null,
      });
    });
    await page.goto(`/schedules/${ids.schedule}`);
    await page.getByRole("button", { name: "Cancel standing order" }).click();
    await expect(
      page.getByText("Cancel this standing order? Later runs will not happen."),
    ).toBeVisible();
    expect(cancelled).toBe(0);
    await page.getByRole("button", { name: "Keep it" }).click();
    await expect(page.getByText("Cancel this standing order?")).toHaveCount(0);
    expect(cancelled).toBe(0);

    await page.getByRole("button", { name: "Cancel standing order" }).click();
    await page.getByRole("button", { name: "Yes, cancel" }).click();
    await expect(page.getByText("Cancelled", { exact: true })).toBeVisible();
    expect(cancelled).toBe(1);
    await expect(page.getByRole("button", { name: "Pause" })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Cancel standing order" }),
    ).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Edit" })).toHaveCount(0);
  });

  test("a STOPPED standing order can be cancelled (the backend allows cancel from stopped)", async ({
    page,
  }) => {
    await mockDetail(page, stoppedSchedule, [disruptedRun]);
    let csrf: string | undefined;
    let cancelled = 0;
    await page.route(
      `**/api/schedules/${ids.stoppedSchedule}/cancel`,
      (route) => {
        cancelled += 1;
        csrf = route.request().headers()["x-csrf-token"];
        return json(route, {
          ...stoppedSchedule,
          status: "cancelled",
          next_run_date: null,
        });
      },
    );
    await page.goto(`/schedules/${ids.stoppedSchedule}`);
    // A stopped schedule offers Restart and Cancel, but no Pause, Resume or Edit.
    await expect(
      page.getByRole("link", { name: "Restart from a new order" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Pause" })).toHaveCount(0);
    await page.getByRole("button", { name: "Cancel standing order" }).click();
    await page.getByRole("button", { name: "Yes, cancel" }).click();
    await expect(page.getByText("Cancelled", { exact: true })).toBeVisible();
    expect(cancelled).toBe(1);
    expect(csrf).toBe("test-csrf");
    await expect(
      page.getByRole("button", { name: "Cancel standing order" }),
    ).toHaveCount(0);
  });

  test("SCHEDULE_NOT_ACTIVE reloads the schedule and shows the message", async ({
    page,
  }) => {
    await mockSignedIn(page);
    let state: Schedule = schedule;
    await page.route(detailUrl(ids.schedule), (route) =>
      json(route, detail(state)),
    );
    await page.route(`**/api/schedules/${ids.schedule}/pause`, (route) => {
      state = { ...schedule, status: "stopped", stop_reason: "RUN_MISSED" };
      return problem(
        route,
        409,
        "SCHEDULE_NOT_ACTIVE",
        "This standing order is no longer active.",
      );
    });
    await page.goto(`/schedules/${ids.schedule}`);
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("alert").first()).toContainText(
      "This standing order is no longer active.",
    );
    await expect(page.getByText("Stopped, needs attention")).toBeVisible();
    await expect(page.getByRole("button", { name: "Pause" })).toHaveCount(0);
  });

  test("another action failure is shown with the server message", async ({
    page,
  }) => {
    await mockDetail(page, schedule);
    await page.route(`**/api/schedules/${ids.schedule}/pause`, (route) =>
      problem(route, 500, "INTERNAL", "Could not pause right now."),
    );
    await page.goto(`/schedules/${ids.schedule}`);
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("alert")).toContainText(
      "Could not pause right now.",
    );
    await expect(page.getByRole("button", { name: "Pause" })).toBeEnabled();
  });

  test("a missing schedule shows the server message and a way back", async ({
    page,
  }) => {
    await mockSignedIn(page);
    await page.route(detailUrl(ids.schedule), (route) =>
      problem(route, 404, "NOT_FOUND", "Standing order not found."),
    );
    await page.goto(`/schedules/${ids.schedule}`);
    await expect(page.getByRole("alert")).toContainText(
      "Standing order not found.",
    );
    await expect(
      page.getByRole("link", { name: "All standing orders" }),
    ).toHaveAttribute("href", "/schedules");
  });

  test("an expired session on the detail returns to sign-in", async ({
    page,
  }) => {
    await mockSignedIn(page);
    await page.route(detailUrl(ids.schedule), (route) =>
      problem(route, 401, "UNAUTHENTICATED", "Sign in to continue."),
    );
    await page.goto(`/schedules/${ids.schedule}`);
    await expect(page).toHaveURL(/\/login$/);
  });

  test("a non-approver role sees no write buttons", async ({ page }) => {
    await page.route("**/api/session", (route) =>
      json(route, { ...session, role: "viewer" }),
    );
    await page.route("**/api/conversations?*", (route) =>
      json(route, { items: [], next_offset: null }),
    );
    await page.route(detailUrl(ids.schedule), (route) =>
      json(route, detail(schedule)),
    );
    await page.goto(`/schedules/${ids.schedule}`);
    await expect(
      page.getByRole("heading", { name: "Breakfast dairy", level: 1 }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Pause" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Edit" })).toHaveCount(0);
  });

  test("phone width keeps the primary action reachable without side scrolling", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockDetail(page, stoppedSchedule, [disruptedRun]);
    await page.goto(`/schedules/${ids.stoppedSchedule}`);
    const restart = page.getByRole("link", {
      name: "Restart from a new order",
    });
    await restart.scrollIntoViewIfNeeded();
    await expect(restart).toBeVisible();
    const box = await restart.boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= 390).toBe(true);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
