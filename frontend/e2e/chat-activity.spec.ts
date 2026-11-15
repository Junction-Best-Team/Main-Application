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
  {
    sequence: 3,
    kind: "tool_completed",
    label: "Searching recipes",
    detail: "Found 2 recipes: Carbonara, Lasagne",
  },
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
      cart_editable: false,
      messages: [
        { id: 1, role: "user", text: "Plan lunch", created_at: timestamp },
      ],
      purchases: [],
      busy: true,
      activity: {
        turn_id: tid,
        state: "running",
        events: [
          ...initialEvents,
          { sequence: 3, kind: "tool_completed", label: "Searching recipes" },
        ],
      },
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
    await expect(activity.getByRole("status")).toHaveText(
      "Searching recipes · Done",
    );
    // A running turn stays one live status line until the customer opens it.
    const toggle = activity.getByRole("button");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(
      activity.getByRole("list", { name: "Activity steps" }),
    ).toHaveCount(0);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toContainText("Hide 2 steps");
    const steps = activity.getByRole("list", { name: "Activity steps" });
    await expect(steps.getByRole("listitem")).toHaveCount(2);
    await page.screenshot({
      path: testInfo.outputPath(`latest-step-${width}.png`),
    });
    await expect(
      page.getByRole("button", { name: "Stop", exact: true }),
    ).toBeEnabled();
    // The composer stays enabled while Aimo works so messages can be queued.
    await expect(page.getByLabel("Continue the conversation")).toBeEnabled();
    await expect(activity.locator(".activity-dot").first()).toHaveCSS(
      "animation-name",
      "activity-dot",
    );
    snapshot = {
      ...snapshot,
      activity: { turn_id: tid, state: "running", events: productEvents },
    };
    publish();
    await expect(activity.getByRole("status")).toHaveText(
      "Checking a product…",
    );
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(steps.getByRole("listitem")).toHaveCount(4);
    await expect(steps.getByRole("listitem").nth(0)).toContainText(
      "Checking your request · Done",
    );
    await expect(steps.getByRole("listitem").nth(1)).toContainText(
      "Searching recipes · Done",
    );
    await expect(steps.getByRole("listitem").nth(1)).toContainText(
      "Found 2 recipes: Carbonara, Lasagne",
    );
    await expect(steps.getByRole("listitem").nth(2)).toContainText(
      "Searching products · Couldn't finish",
    );
    await expect(steps.getByRole("listitem").nth(3)).toContainText(
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
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(steps.getByRole("listitem")).toHaveCount(4);
    if (width === 320) {
      await page.emulateMedia({ reducedMotion: "reduce" });
      await expect(activity.locator(".activity-dot").first()).toHaveCSS(
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
      page.getByRole("button", { name: "Start voice mode" }),
    ).toBeEnabled();
    await expect(
      page.getByText("What delivery date?", { exact: true }),
    ).toBeVisible();
    await expect(activity.locator(".activity-dot")).toHaveCount(0);
    // The customer's own toggle stays for the rest of this turn.
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(steps.getByRole("listitem").nth(3)).toContainText(
      "Checking a product · Done",
    );
    await page.reload();
    await expect(activity.getByRole("status")).toHaveText("Finished");
    await toggle.click();
    await expect(steps.getByRole("listitem")).toHaveCount(4);
  });
}

test("activity header follows the latest saved step between tool calls", async ({
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
  let events: ActivityEvent = [initialEvents[0]];
  await page.route(`**/api/conversations/${cid}`, (route) =>
    route.fulfill({
      json: {
        id: cid,
        title: "Lunch",
        created_at: timestamp,
        updated_at: timestamp,
        cart_editable: false,
        messages: [],
        purchases: [],
        busy: true,
        activity: { turn_id: tid, state: "running", events },
      } satisfies Conversation,
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
  await expect(activity.getByRole("status")).toHaveText(
    "Checking your request…",
  );

  events = productEvents.slice(0, -1);
  await page.reload();
  await expect(activity.getByRole("status")).toHaveText(
    "Searching products · Couldn't finish",
  );

  events = Array.from({ length: 15 }, (_, i) => [
    {
      sequence: i * 2 + 1,
      kind: "tool_started" as const,
      label: "Checking prices and availability",
    },
    {
      sequence: i * 2 + 2,
      kind: "tool_completed" as const,
      label: "Checking prices and availability",
    },
  ]).flat();
  await page.reload();
  await expect(activity.getByRole("status")).toHaveText(
    "Checking prices and availability · Done",
  );
  await activity.getByRole("button", { name: /Show 15 steps/ }).click();
  await expect(activity.getByRole("listitem")).toHaveCount(15);
  // The newest step stays in view as the list grows.
  await expect(activity.getByRole("listitem").last()).toBeInViewport();
  await activity.getByRole("button", { name: /Hide 15 steps/ }).click();
  await expect(activity.getByRole("list")).not.toBeVisible();
  await activity.getByRole("button", { name: /Show 15 steps/ }).click();
  await expect(activity.getByRole("listitem")).toHaveCount(15);

  events = [
    ...events,
    { sequence: 31, kind: "complete", label: "Finishing the response" },
  ];
  await page.reload();
  await expect(activity.getByRole("status")).toHaveText(
    "Finishing the response…",
  );
});

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
  await expect(activity.locator(".activity-dot")).toHaveCount(0);
  await activity.getByRole("button", { name: /Show 2 steps/ }).click();
  await expect(activity.getByRole("listitem").nth(1)).toContainText(
    "Searching recipes · Interrupted",
  );
  await expect(page.getByRole("button", { name: "Retry" })).toBeEnabled();
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
    cart_editable: false,
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

test("model stages show as one ticking line that expands to every step", async ({
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
  let events: ActivityEvent = [
    initialEvents[0],
    { sequence: 2, kind: "thinking", label: "Thinking" },
  ];
  await page.route(`**/api/conversations/${cid}`, (route) =>
    route.fulfill({
      json: {
        id: cid,
        title: "Hey",
        created_at: timestamp,
        updated_at: timestamp,
        messages: [],
        purchases: [],
        cart_editable: false,
        busy: true,
        activity: { turn_id: tid, state: "running", events },
      } satisfies Conversation,
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
  await expect(activity.getByRole("status")).toHaveText("Thinking…");
  const toggle = activity.getByRole("button");
  // The elapsed time is this browser's own clock, not a predicted completion time.
  await expect(toggle.locator(".tabular-nums")).toHaveText(/^[12]s$/, {
    timeout: 3_000,
  });

  events = [
    ...(events ?? []),
    { sequence: 3, kind: "reviewing", label: "Reviewing the reply" },
  ];
  await page.reload();
  await expect(activity.getByRole("status")).toHaveText("Reviewing the reply…");
  await toggle.click();
  const steps = activity.getByRole("list", { name: "Activity steps" });
  await expect(steps.getByRole("listitem")).toHaveText([
    /Checking your request/,
    /Thinking/,
    /Reviewing the reply · In progress/,
  ]);
  await expect(steps.locator(".activity-spin")).toHaveCount(1);
});
for (const width of [1440, 390]) {
  test(`parallel calls retain individual completion states at ${width}px`, async ({
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
    const snapshot: Conversation = {
      id: cid,
      title: "Parallel reads",
      cart_editable: false,
      created_at: timestamp,
      updated_at: timestamp,
      messages: [
        { id: 1, role: "user", text: "Plan lunch", created_at: timestamp },
      ],
      purchases: [],
      busy: false,
      activity: {
        turn_id: tid,
        state: "complete",
        events: [
          { sequence: 1, kind: "started", label: "Checking your request" },
          { sequence: 2, kind: "tool_started", label: "Searching products" },
          {
            sequence: 3,
            kind: "tool_started",
            label: "Checking purchasing rules",
          },
          { sequence: 4, kind: "tool_started", label: "Searching products" },
          { sequence: 5, kind: "tool_completed", label: "Searching products" },
          {
            sequence: 6,
            kind: "tool_failed",
            label: "Checking purchasing rules",
          },
          { sequence: 7, kind: "tool_completed", label: "Searching products" },
          { sequence: 8, kind: "complete", label: "Finishing the response" },
        ],
      },
    };
    await page.route(`**/api/conversations/${cid}`, (route) =>
      route.fulfill({ json: snapshot }),
    );
    await page.route(`**/api/conversations/${cid}/events`, (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: `event: conversation\ndata: ${JSON.stringify(snapshot)}\n\n`,
      }),
    );
    await page.goto(`/conversations/${cid}`);
    const activity = page.getByRole("region", { name: "Aimo activity" });
    await activity.getByRole("button", { name: /Show 4 steps/ }).click();
    const steps = activity.getByRole("listitem");
    await expect(steps).toHaveCount(4);
    await expect(steps.nth(1)).toContainText("Searching products · Done");
    await expect(steps.nth(2)).toContainText(
      "Checking purchasing rules · Couldn't finish",
    );
    await expect(steps.nth(3)).toContainText("Searching products · Done");
    await expect(activity).not.toContainText("Interrupted");
    await page.screenshot({
      path: testInfo.outputPath(`parallel-${width}.png`),
    });
  });
}

for (const width of [1440, 320]) {
  test(`saved partial result pauses and drafts continuation at ${width}px`, async ({
    page,
  }) => {
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
    const snapshot: Conversation = {
      id: cid,
      title: "Italian lunch",
      created_at: timestamp,
      updated_at: timestamp,
      cart_editable: false,
      purchases: [],
      busy: false,
      messages: [
        {
          id: 1,
          role: "assistant",
          text: "Your reviewed recipe progress is saved.",
          created_at: timestamp,
          meal_plan: {
            title: "Lasagna estimate",
            portions: 40,
            notes: [],
            ingredients: [
              {
                name: "Lasagna sheets",
                amount: "4",
                unit: "KG",
                status: "proposed",
              },
            ],
          },
        },
      ],
      activity: {
        turn_id: tid,
        state: "complete",
        events: [
          ...initialEvents,
          { sequence: 3, kind: "error", label: "Response interrupted" },
          { sequence: 4, kind: "complete", label: "Finishing the response" },
        ],
      },
    };
    let running = width === 1440;
    let publish: () => void = () => {};
    const streamReady = new Promise<void>((resolve) => {
      publish = resolve;
    });
    await page.route(`**/api/conversations/${cid}`, (route) =>
      route.fulfill({
        json: running
          ? {
              ...snapshot,
              busy: true,
              activity: {
                turn_id: tid,
                state: "running",
                events: initialEvents,
              },
            }
          : snapshot,
      }),
    );
    await page.route(`**/api/conversations/${cid}/events`, async (route) => {
      await streamReady;
      await route.fulfill({
        contentType: "text/event-stream",
        body: `event: conversation\ndata: ${JSON.stringify(snapshot)}\n\n`,
      });
    });
    if (!running) publish();
    let posts = 0;
    await page.route(`**/api/conversations/${cid}/messages`, async (route) => {
      posts++;
      const request = route.request();
      expect(request.headers()["x-csrf-token"]).toBe("test-csrf");
      expect(request.postDataJSON().text).toBe(
        "Continue matching the remaining ingredients in my saved recipe plan.",
      );
      expect(request.postDataJSON().idempotency_key).toBeTruthy();
      await route.fulfill({
        json: {
          ...snapshot,
          busy: true,
          activity: { turn_id: "new-turn", state: "queued", events: [] },
        },
      });
    });
    await page.goto(`/conversations/${cid}`);
    if (running) {
      await page.locator("#purchase-message").fill("Queued follow-up");
      await page.locator("#purchase-message").press("Enter");
      await expect(
        page.getByRole("list", { name: "Queued messages" }),
      ).toContainText("Queued follow-up");
      running = false;
      publish();
      await expect(
        page.getByRole("button", {
          name: "Send queued message: Queued follow-up",
          exact: true,
        }),
      ).toBeVisible();
      expect(posts).toBe(0);
    }
    const activity = page.getByRole("region", { name: "Aimo activity" });
    await expect(activity.getByRole("status")).toHaveText(
      "Paused — progress saved",
    );
    await expect(activity).toContainText(
      "Recipe saved; product matching is unfinished.",
    );
    await page.reload();
    await expect(activity.getByRole("status")).toHaveText(
      "Paused — progress saved",
    );
    const composer = page.locator("#purchase-message");
    await composer.fill("Keep my unsent draft");
    await expect(
      activity.getByRole("button", { name: "Continue matching" }),
    ).toHaveCount(0);
    await expect(composer).toHaveValue("Keep my unsent draft");
    await composer.fill("");
    await activity.getByRole("button", { name: "Continue matching" }).click();
    await expect(composer).toBeFocused();
    await expect(composer).toHaveValue(
      "Continue matching the remaining ingredients in my saved recipe plan.",
    );
    expect(posts).toBe(0); // Drafting is not sending or confirming a purchase.
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page
      .getByRole("button", { name: "Send Order Request", exact: true })
      .click();
    await expect.poll(() => posts).toBe(1);
  });
}
