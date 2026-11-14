import { expect, test } from "@playwright/test";
import type { Conversation } from "../src/shared/api/types";

// Authored snapshots exercise the actual EventSource consumer, without a provider.
const cid = "fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";
const tid = "aa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";
const timestamp = "2026-11-14T12:00:00Z";
type ActivityEvent = NonNullable<Conversation["activity"]>["events"];
const initialEvents: ActivityEvent = [
  { sequence: 1, kind: "started", label: "Checking your request" },
  { sequence: 2, kind: "tool_started", label: "Searching recipes" },
];
const productEvents: ActivityEvent = [
  ...initialEvents,
  { sequence: 3, kind: "tool_completed", label: "Searching recipes" },
  { sequence: 4, kind: "tool_started", label: "Searching products" },
  { sequence: 5, kind: "tool_failed", label: "Searching products" },
  { sequence: 6, kind: "tool_started", label: "Checking a product" },
];

for (const width of [1440, 390, 320]) {
  test(`tool activity streams, survives reload and stops at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.route("**/api/session", (route) =>
      route.fulfill({
        json: {
          username: "buyer",
          buyer_id: "demo-hotel",
          csrf_token: "test-csrf",
        },
      }),
    );
    await page.route("**/api/conversations?*", (route) =>
      route.fulfill({ json: { items: [], next_offset: null } }),
    );
    let snapshot: Conversation = {
      id: cid,
      title: "Lunch",
      created_at: timestamp,
      updated_at: timestamp,
      messages: [
        { id: 1, role: "user", text: "Plan lunch", created_at: timestamp },
      ],
      purchases: [],
      busy: true,
      activity: { turn_id: tid, state: "running", events: initialEvents },
    };
    await page.route(`**/api/conversations/${cid}`, (route) =>
      route.fulfill({ json: snapshot }),
    );
    let publish: () => void = () => {};
    const streamReady = new Promise<void>((resolve) => {
      publish = resolve;
    });
    await page.route(`**/api/conversations/${cid}/events`, async (route) => {
      await streamReady;
      await route.fulfill({
        contentType: "text/event-stream",
        body: `event: conversation\ndata: ${JSON.stringify(snapshot)}\n\n`,
      });
    });
    await page.goto(`/conversations/${cid}`);
    const activity = page.getByRole("region", { name: "Aimo activity" });
    await expect(activity.getByRole("status")).toHaveText("Searching recipes…");
    await expect(
      page.getByRole("button", { name: "Start voice mode" }),
    ).toBeDisabled();
    await expect(activity.locator(".activity-sweep")).toHaveCSS(
      "animation-name",
      "activity-sweep",
    );
    snapshot = {
      ...snapshot,
      activity: { turn_id: tid, state: "running", events: productEvents },
    };
    publish();
    await expect(activity.getByRole("status")).toHaveText(
      "Checking a product…",
    );
    await activity.getByText("3 steps", { exact: true }).click();
    const steps = activity.getByRole("list", { name: "Tool activity" });
    await expect(steps.getByRole("listitem")).toHaveCount(3);
    await expect(steps.getByRole("listitem").nth(0)).toContainText(
      "Searching recipes · Done",
    );
    await expect(steps.getByRole("listitem").nth(1)).toContainText(
      "Searching products · Couldn't finish",
    );
    await expect(steps.getByRole("listitem").nth(2)).toContainText(
      "Checking a product · In progress",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`activity-${width}.png`),
    });

    await page.reload();
    await expect(activity.getByRole("status")).toHaveText(
      "Checking a product…",
    );
    await activity.getByText("3 steps", { exact: true }).click();
    await expect(steps.getByRole("listitem")).toHaveCount(3);
    if (width === 320) {
      await page.emulateMedia({ reducedMotion: "reduce" });
      await expect(activity.locator(".activity-sweep")).toHaveCSS(
        "animation-name",
        "none",
      );
    }
    // The next SSE connection carries the saved final result and every rapid tool event.
    snapshot = {
      ...snapshot,
      busy: false,
      messages: [
        ...snapshot.messages,
        {
          id: 2,
          role: "assistant",
          text: "What delivery date?",
          created_at: timestamp,
        },
      ],
      activity: {
        turn_id: tid,
        state: "complete",
        events: [
          ...(productEvents ?? []),
          { sequence: 7, kind: "tool_completed", label: "Checking a product" },
          { sequence: 8, kind: "complete", label: "Finishing the response" },
        ],
      },
    };
    await expect(activity.getByRole("status")).toHaveText("Finished", {
      timeout: 10_000,
    });
    await expect(
      page.getByText("What delivery date?", { exact: true }),
    ).toBeVisible();
    await expect(activity.locator(".activity-sweep")).toHaveCount(0);
    await expect(steps.getByRole("listitem").nth(2)).toContainText(
      "Checking a product · Done",
    );
    await page.reload();
    await expect(activity.getByRole("status")).toHaveText("Finished");
    await activity.getByText("3 steps", { exact: true }).click();
    await expect(steps.getByRole("listitem")).toHaveCount(3);
  });
}

test("interrupted activity stops moving and never marks an unfinished tool done", async ({
  page,
}) => {
  await page.route("**/api/session", (route) =>
    route.fulfill({
      json: { username: "buyer", buyer_id: "demo-hotel", csrf_token: "test" },
    }),
  );
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
  await page.route(`**/api/conversations/${cid}`, (route) =>
    route.fulfill({
      json: {
        id: cid,
        title: "Lunch",
        created_at: timestamp,
        updated_at: timestamp,
        messages: [],
        purchases: [],
        busy: false,
        retry_message: {
          text: "Plan lunch",
          idempotency_key: "interrupted-key",
        },
        activity: { turn_id: tid, state: "failed", events: initialEvents },
      },
    }),
  );
  await page.route(`**/api/conversations/${cid}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": heartbeat\n\n",
    }),
  );
  await page.goto(`/conversations/${cid}`);
  const activity = page.getByRole("region", { name: "Aimo activity" });
  await expect(activity.getByRole("status")).toHaveText("Response interrupted");
  await expect(activity.locator(".activity-sweep")).toHaveCount(0);
  await activity.getByText("1 step", { exact: true }).click();
  await expect(activity.getByRole("listitem")).toContainText(
    "Searching recipes · Interrupted",
  );
  await expect(
    page.getByRole("button", { name: "Retry request" }),
  ).toBeEnabled();
});

test("a delayed queued response cannot replace streamed tool activity", async ({
  page,
}) => {
  await page.route("**/api/session", (route) =>
    route.fulfill({
      json: { username: "buyer", buyer_id: "demo-hotel", csrf_token: "test" },
    }),
  );
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
  const blank: Conversation = {
    id: cid,
    title: "Lunch",
    created_at: timestamp,
    updated_at: timestamp,
    messages: [],
    purchases: [],
    busy: false,
  };
  const queued: Conversation = {
    ...blank,
    busy: true,
    activity: { turn_id: tid, state: "queued", events: [] },
  };
  const running: Conversation = {
    ...queued,
    activity: { turn_id: tid, state: "running", events: productEvents },
  };
  await page.route(`**/api/conversations/${cid}`, (route) =>
    route.fulfill({ json: blank }),
  );
  let publish: () => void = () => {};
  const streamReady = new Promise<void>((resolve) => {
    publish = resolve;
  });
  let respond: () => void = () => {};
  const responseReady = new Promise<void>((resolve) => {
    respond = resolve;
  });
  await page.route(`**/api/conversations/${cid}/events`, async (route) => {
    await streamReady;
    await route.fulfill({
      contentType: "text/event-stream",
      body: `event: conversation\ndata: ${JSON.stringify(running)}\n\n`,
    });
  });
  await page.route(`**/api/conversations/${cid}/messages`, async (route) => {
    publish();
    await responseReady;
    await route.fulfill({ json: queued });
  });
  await page.goto(`/conversations/${cid}`);
  await page.getByLabel("Continue the conversation").fill("Plan lunch");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  const status = page
    .getByRole("region", { name: "Aimo activity" })
    .getByRole("status");
  await expect(status).toHaveText("Checking a product…");
  const response = page.waitForResponse((r) => r.url().endsWith("/messages"));
  respond();
  await response;
  await expect(page.getByLabel("Continue the conversation")).toHaveValue("");
  await expect(status).toHaveText("Checking a product…");
});
