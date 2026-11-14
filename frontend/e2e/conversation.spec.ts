import { expect, test, type Page } from "@playwright/test";

// Conversation thread path (#68): list/create/open on Home + Request IA,
// CSRF+idempotency message send, SSE full-snapshot replace, busy affordance,
// stream/API error chrome. Mocked at the browser<->API edge.
// chat.spec.ts already covers request starters, lost-response retry keys, and
// Overview confirm; this file keeps the conversation/SSE chrome gaps.

const session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "conversation-csrf-token",
};
const conversationId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
const otherId = "b2c3d4e5-f6a7-8901-bcde-f12345678901";
const timestamp = "2026-11-14T15:00:00Z";

const summary = (id: string, title: string) => ({
  id,
  title,
  created_at: timestamp,
  updated_at: timestamp,
});

const blankConversation = {
  ...summary(conversationId, "Carbonara for 200"),
  messages: [] as Array<Record<string, unknown>>,
  purchases: [] as unknown[],
  busy: false,
  retry_message: null as null | { text: string; idempotency_key: string },
};

function sseConversation(payload: Record<string, unknown>) {
  return `event: conversation\ndata: ${JSON.stringify(payload)}\n\n`;
}

async function mockBuyerSession(page: Page) {
  await page.route("**/api/session", (route) =>
    route.fulfill({ status: 200, json: session }),
  );
  await page.route("**/api/login", (route) => route.fulfill({ json: session }));
  await page.route("**/api/logout", (route) => route.fulfill({ status: 204 }));
  await page.route("**/api/purchases?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
}

test("buyer can list, create, and open conversations from Home and Request", async ({
  page,
}) => {
  await mockBuyerSession(page);
  const created = structuredClone(blankConversation);
  const other = {
    ...summary(otherId, "Lunch for Monday"),
    messages: [
      {
        id: 10,
        role: "assistant",
        text: "What are you cooking on Monday?",
        created_at: timestamp,
      },
    ],
    purchases: [],
    busy: false,
    retry_message: null,
  };
  let listItems = [summary(otherId, "Lunch for Monday")];

  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: listItems, next_offset: null } }),
  );
  await page.route(`**/api/conversations/${otherId}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": keep-alive\n\n",
    }),
  );
  await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": keep-alive\n\n",
    }),
  );
  await page.route(`**/api/conversations/${otherId}`, (route) =>
    route.fulfill({ json: other }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: created }),
  );

  const createBodies: Array<Record<string, unknown>> = [];
  await page.route("**/api/conversations", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    const body = route.request().postDataJSON();
    createBodies.push(body);
    expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf_token);
    created.title = String(body.title);
    listItems = [
      summary(conversationId, created.title),
      ...listItems.filter((item) => item.id !== conversationId),
    ];
    await route.fulfill({ json: created });
  });

  const messageBodies: Array<Record<string, unknown>> = [];
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      const body = route.request().postDataJSON();
      messageBodies.push(body);
      expect(route.request().headers()["x-csrf-token"]).toBe(
        session.csrf_token,
      );
      created.messages = [
        {
          id: 1,
          role: "user",
          text: body.text,
          created_at: timestamp,
        },
      ];
      listItems = [
        summary(conversationId, created.title),
        ...listItems.filter((item) => item.id !== conversationId),
      ];
      await route.fulfill({ json: created });
    },
  );

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What are we cooking?" }),
  ).toBeVisible();
  const nav = page.getByRole("complementary", { name: "Sidebar" });
  await expect(nav.getByRole("list", { name: "Conversations" })).toBeVisible();
  await expect(
    nav.getByRole("link", { name: "Lunch for Monday" }),
  ).toBeVisible();

  await nav.getByRole("link", { name: "Lunch for Monday" }).click();
  await expect(page).toHaveURL(new RegExp(`/conversations/${otherId}$`));
  await expect(page.getByText("What are you cooking on Monday?")).toBeVisible();

  await page.goto("/request");
  await expect(page).toHaveURL(/\/request$/);
  await expect(
    page.getByRole("heading", { name: "Aimo Kitchen Assistant" }),
  ).toBeVisible();
  await page
    .getByLabel("Your meal or purchasing request")
    .fill("Carbonara for 200 portions");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(page).toHaveURL(new RegExp(`/conversations/${conversationId}$`));
  await expect(
    page
      .getByLabel("Conversation messages")
      .getByText("Carbonara for 200 portions"),
  ).toBeVisible();
  expect(createBodies).toHaveLength(1);
  expect(createBodies[0].idempotency_key).toEqual(expect.any(String));
  expect(String(createBodies[0].idempotency_key).length).toBeGreaterThanOrEqual(
    8,
  );
  expect(messageBodies).toHaveLength(1);
  expect(messageBodies[0]).toEqual({
    text: "Carbonara for 200 portions",
    idempotency_key: expect.any(String),
  });
  expect(
    String(messageBodies[0].idempotency_key).length,
  ).toBeGreaterThanOrEqual(8);
  await expect(
    nav.getByRole("link", { name: "Carbonara for 200 portions" }),
  ).toBeVisible();
});

test("message send includes CSRF and an idempotency key", async ({ page }) => {
  await mockBuyerSession(page);
  const saved = structuredClone(blankConversation);
  const headersSeen: string[] = [];
  const keys: string[] = [];

  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({
      json: {
        items: [summary(conversationId, saved.title)],
        next_offset: null,
      },
    }),
  );
  await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": keep-alive\n\n",
    }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: saved }),
  );
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      headersSeen.push(route.request().headers()["x-csrf-token"] ?? "");
      const body = route.request().postDataJSON();
      keys.push(body.idempotency_key);
      expect(body.text).toBe("Need eggs and pancetta");
      saved.messages = [
        {
          id: 1,
          role: "user",
          text: body.text,
          created_at: timestamp,
        },
        {
          id: 2,
          role: "assistant",
          text: "Noted. Any dietary constraints?",
          created_at: timestamp,
        },
      ];
      await route.fulfill({ json: saved });
    },
  );

  await page.goto(`/conversations/${conversationId}`);
  await page
    .getByLabel("Continue the conversation")
    .fill("Need eggs and pancetta");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(page.getByText("Noted. Any dietary constraints?")).toBeVisible();
  expect(headersSeen).toEqual([session.csrf_token]);
  expect(keys).toHaveLength(1);
  expect(keys[0].length).toBeGreaterThanOrEqual(8);
});

test("SSE conversation snapshots replace the thread view", async ({ page }) => {
  await mockBuyerSession(page);
  const initial = {
    ...structuredClone(blankConversation),
    messages: [
      {
        id: 1,
        role: "assistant",
        text: "Stale poll snapshot that must disappear.",
        created_at: timestamp,
      },
    ],
  };
  const fromStream = {
    ...structuredClone(blankConversation),
    messages: [
      {
        id: 2,
        role: "user",
        text: "Carbonara for 200",
        created_at: timestamp,
      },
      {
        id: 3,
        role: "assistant",
        text: "SSE replaced this thread with a full snapshot.",
        created_at: timestamp,
      },
    ],
    busy: false,
  };

  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({
      json: {
        items: [summary(conversationId, initial.title)],
        next_offset: null,
      },
    }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: initial }),
  );
  await page.route(
    `**/api/conversations/${conversationId}/events`,
    async (route) => {
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
        },
        body: sseConversation(fromStream),
      });
    },
  );

  await page.goto(`/conversations/${conversationId}`);
  await expect(
    page
      .getByLabel("Conversation messages")
      .getByText("SSE replaced this thread with a full snapshot."),
  ).toBeVisible();
  await expect(
    page.getByLabel("Conversation messages").getByText("Carbonara for 200"),
  ).toBeVisible();
  await expect(
    page.getByText("Stale poll snapshot that must disappear."),
  ).toHaveCount(0);
});

test("busy affordance shows while a turn is in flight", async ({ page }) => {
  await mockBuyerSession(page);
  const busyConversation = {
    ...blankConversation,
    busy: true,
    messages: [
      {
        id: 1,
        role: "user",
        text: "Plan carbonara",
        created_at: timestamp,
      },
    ],
  };

  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({
      json: {
        items: [summary(conversationId, busyConversation.title)],
        next_offset: null,
      },
    }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: busyConversation }),
  );
  await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: sseConversation(busyConversation),
    }),
  );

  await page.goto(`/conversations/${conversationId}`);
  // develop's chat activity strip replaced "Aimo is checking your request".
  await expect(
    page
      .getByRole("region", { name: "Aimo activity" })
      .getByRole("status")
      .filter({ hasText: "Sending your request" }),
  ).toBeVisible();
  await expect(page.getByLabel("Continue the conversation")).toBeDisabled();
  // The composer's buttons are disabled while a turn runs (the send button only shows with text).
  await expect(
    page.getByRole("button", { name: "Attach file" }),
  ).toBeDisabled();
});

test("API failure shows error chrome", async ({ page }) => {
  await mockBuyerSession(page);

  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({
      json: {
        items: [summary(conversationId, blankConversation.title)],
        next_offset: null,
      },
    }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({
      status: 503,
      json: {
        error: {
          message: "Conversation is temporarily unavailable. Try again.",
        },
      },
    }),
  );
  await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": keep-alive\n\n",
    }),
  );

  await page.goto(`/conversations/${conversationId}`);
  await expect(page.getByRole("alert")).toContainText(
    "Conversation is temporarily unavailable",
  );
});

test("SSE disconnect shows reconnect chrome", async ({ page }) => {
  await mockBuyerSession(page);
  const saved = structuredClone(blankConversation);

  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({
      json: {
        items: [summary(conversationId, saved.title)],
        next_offset: null,
      },
    }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: saved }),
  );
  await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
    route.abort("connectionfailed"),
  );

  await page.goto(`/conversations/${conversationId}`);
  await expect(
    page.getByText("Reconnecting to updates", { exact: false }),
  ).toBeVisible();
});
