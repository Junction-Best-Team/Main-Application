import { expect, test, type Page } from "@playwright/test";
import type { components } from "../src/shared/api/schema";
import type { Conversation, Proposal } from "../src/shared/api/types";

const session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf",
};
const conversationId = "fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";
const proposalId = "b7b7dc8d-8e75-4f79-ac23-649ed1e5fd96";
const approvalId = "9d42774c-5c59-4eb2-881d-c5e487f6a52d";
const timestamp = "2026-11-14T12:00:00Z";
const blankConversation: Conversation = {
  id: conversationId,
  title: "Carbonara for 200",
  created_at: timestamp,
  updated_at: timestamp,
  messages: [],
  purchases: [],
  busy: false,
};
const proposal: Proposal = {
  recipe_basis: "free_form",
  proposal_id: proposalId,
  revision: 1,
  fingerprint: "a".repeat(64),
  current_revision: 1,
  committed_revision: null,
  current_proposal_url: `/purchases/${proposalId}`,
  policy_version: 1,
  policy_outcome: "approval_required",
  approval_status: "pending",
  order_status: "not_placed",
  reasons: [
    {
      code: "PRODUCT_SCOPE",
      message: "Products outside the standing scope need your approval.",
      severity: "exception",
    },
  ],
  expires_at: "2099-11-15T12:00:00Z",
  next_action: { type: "wait" },
  approval_id: approvalId,
  approval_url: `/approvals/${approvalId}`,
  order_id: null,
  buyer_id: "demo-hotel",
  agent_id: "internal-demo-hotel",
  request: {
    request_id: "Carbonara for 200",
    lines: [{ product_id: "pasta", amount: "20", unit: "KG" }],
    destination: "hotel-helsinki",
    delivery_date: "2026-11-16",
    requirements: { lactose_free: false, milk_free: false },
    allow_substitution: true,
    allow_overbuy: true,
  },
  snapshot: {
    lines: [
      {
        product_id: "pasta",
        name: "Spaghetti 5 kg",
        quantity: {
          requested_amount: "20",
          requested_unit: "KG",
          sales_unit: "BAG",
          sales_quantity: "4",
          proposed_amount: "20",
          excess: "0",
          status: "known",
          basis: ["catalog"],
          source_step: "1",
        },
        substitutes_for: null,
        net: "100.00",
        gross: "114.00",
        tax: "14.00",
        deposits_gross: "0",
        deposit_lines: [],
        product_evidence: {},
        commercial_evidence: {},
      },
    ],
    currency: "EUR",
    net_total: "100.00",
    gross_total: "114.00",
    tax_total: "14.00",
    deposits_gross: "0",
    charges_gross: "0",
    charges_basis: "demo",
    mode: "fixture",
    observed_at: timestamp,
    reasons: [],
  },
  history: [],
  can_decide: true,
};
async function mockSession(page: Page, signedIn = true) {
  const currentSession = session;
  let authenticated = signedIn;
  await page.route("**/api/session", (route) =>
    route.fulfill({
      status: authenticated ? 200 : 401,
      json: authenticated ? currentSession : { error: { message: "Sign in" } },
    }),
  );
  await page.route("**/api/login", async (route) => {
    authenticated = true;
    await route.fulfill({ json: currentSession });
  });
  await page.route("**/api/logout", async (route) => {
    authenticated = false;
    await route.fulfill({ status: 204 });
  });
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: proposal }),
  );
  await page.route("**/api/purchases?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: [blankConversation], next_offset: null } }),
  );
  await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": heartbeat\n\n",
    }),
  );
}

for (const width of [1440, 320]) {
  test(`chat renders Markdown without page overflow at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockSession(page);
    const markdown = [
      "## Kitchen plan",
      "",
      "Use **tomatoes**, *basil* and ~~cream~~ with `pasta`.",
      "Keep this second line.",
      "",
      "- Ingredients",
      "  - Tomatoes",
      "  - Basil",
      "",
      "1. Boil water",
      "2. Cook pasta",
      "",
      "> Check the quantities before purchasing.",
      "",
      "[Recipe guide](https://example.com/recipe)",
      "",
      "```text",
      `SKU: ${"1234567890".repeat(30)}`,
      "```",
      "",
      "| Ingredient | Quantity | Unit | Preparation | Storage | Notes |",
      "| --- | --- | --- | --- | --- | --- |",
      "| Tomatoes | 20 | KG | Chopped | Chilled | Review quantity |",
      "",
      "- [x] Plan drafted",
      "- [ ] Buyer review",
    ].join("\n");
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({
        json: {
          ...blankConversation,
          messages: [
            {
              id: 1,
              role: "user",
              text: "Use **tomatoes**.\nNo cream.",
              created_at: timestamp,
            },
            { id: 2, role: "assistant", text: markdown, created_at: timestamp },
          ],
        },
      }),
    );
    await page.goto(`/conversations/${conversationId}`);
    const messages = page.getByRole("log", { name: "Conversation messages" });
    const customer = messages.locator("article").nth(0);
    const assistant = messages.locator("article").nth(1);
    await expect(customer.locator("strong")).toHaveText("tomatoes");
    await expect(customer.locator("p")).toHaveCSS("white-space", "pre-wrap");
    await expect(
      assistant.getByRole("heading", { name: "Kitchen plan" }),
    ).toBeVisible();
    await expect(assistant.locator("strong")).toHaveText("tomatoes");
    await expect(assistant.locator("em")).toHaveText("basil");
    await expect(assistant.locator("del")).toHaveText("cream");
    await expect(assistant.locator("li li")).toHaveText(["Tomatoes", "Basil"]);
    await expect(assistant.locator("ol > li")).toHaveText([
      "Boil water",
      "Cook pasta",
    ]);
    await expect(assistant.locator("blockquote")).toContainText(
      "Check the quantities",
    );
    await expect(assistant.locator("pre code")).toContainText("SKU:");
    await expect(assistant.getByRole("columnheader")).toHaveCount(6);
    await expect(
      assistant.getByRole("cell", { name: "Tomatoes", exact: true }),
    ).toBeVisible();
    await expect(assistant.getByRole("checkbox").first()).toBeChecked();
    await expect(assistant.getByRole("checkbox").last()).toBeDisabled();
    const link = assistant.getByRole("link", { name: "Recipe guide" });
    await expect(link).toHaveAttribute("href", "https://example.com/recipe");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(link).toHaveAttribute("target", "_blank");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(
      await assistant
        .locator("pre")
        .evaluate((node) => node.scrollWidth > node.clientWidth),
    ).toBe(true);
    await page.reload();
    await expect(
      assistant.getByRole("heading", { name: "Kitchen plan" }),
    ).toBeVisible();
    await assistant
      .getByRole("heading", { name: "Kitchen plan" })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath("chat-markdown.png"),
      fullPage: true,
    });
  });
}

for (const role of ["user", "assistant"] as const) {
  test(`Markdown in ${role} messages keeps HTML and unsafe URLs inert`, async ({
    page,
  }) => {
    await mockSession(page);
    const imageRequests: string[] = [];
    await page.route("https://example.com/tracking.png", (route) => {
      imageRequests.push(route.request().url());
      return route.abort();
    });
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({
        json: {
          ...blankConversation,
          messages: [
            {
              id: 1,
              role,
              created_at: timestamp,
              text: [
                '<img src="https://example.com/tracking.png" onerror="window.__markdownXss=1">',
                "",
                "<script>window.__markdownXss=1</script>",
                "",
                "[Unsafe script](javascript:alert%281%29)",
                "",
                "[Unsafe data](data:text/html,test)",
                "",
                "![Image description](https://example.com/tracking.png)",
                "",
                "```html",
                '<button onclick="window.__markdownXss=1">Confirm purchase</button>',
                "```",
              ].join("\n"),
            },
          ],
        },
      }),
    );
    await page.goto(`/conversations/${conversationId}`);
    const messages = page.getByRole("log", { name: "Conversation messages" });
    await expect(
      messages.getByText("Unsafe script", { exact: true }),
    ).toBeVisible();
    await expect(
      messages.getByText("Unsafe data", { exact: true }),
    ).toBeVisible();
    await expect(messages.getByRole("link")).toHaveCount(0);
    await expect(messages.locator("img, script, button")).toHaveCount(0);
    await expect(
      messages.getByText("Image description", { exact: true }),
    ).toBeVisible();
    await expect(messages.locator("pre code")).toContainText(
      "<button onclick=",
    );
    expect(await page.evaluate(() => "__markdownXss" in window)).toBe(false);
    expect(imageRequests).toEqual([]);
  });
}

for (const width of [1440, 1024, 390, 320]) {
  test(`recipe illustration persists beside text at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockSession(page);
    const imageUrl =
      "https://res.cloudinary.com/test-cloud/image/upload/v123/recipe.png";
    const saved: Conversation = {
      ...blankConversation,
      messages: [
        {
          id: 2,
          role: "assistant",
          text: "Here is an illustration of the tomato pasta.",
          created_at: timestamp,
          image: { url: imageUrl, width: 1024, height: 768 },
        },
      ],
    };
    await page.route(imageUrl, (route) =>
      route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="768"><rect width="1024" height="768" fill="#c7e8f6"/><text x="64" y="384" font-size="48">Recipe image fixture</text></svg>',
      }),
    );
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({ json: saved }),
    );
    await page.goto(`/conversations/${conversationId}`);
    const image = page.getByRole("img", {
      name: "AI-generated recipe illustration",
    });
    await expect(image).toBeVisible();
    await expect
      .poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth))
      .toBeGreaterThan(0);
    await expect(
      page.getByText("Here is an illustration of the tomato pasta."),
    ).toBeVisible();
    await expect(
      page.getByText(
        "AI-generated illustration · Actual presentation may vary.",
      ),
    ).toBeVisible();
    await expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    const bounds = await image.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.width / bounds!.height).toBeCloseTo(4 / 3, 2);
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.reload();
    await expect(image).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("recipe-image.png"),
      fullPage: true,
    });
  });
}

for (const [width, height] of [
  [1440, 900],
  [1024, 768],
  [390, 844],
  [320, 740],
  [390, 568],
]) {
  test(`chat scrolls messages while keeping the composer visible at ${width}x${height}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height });
    await mockSession(page);
    let saved: Conversation = {
      ...blankConversation,
      messages: Array.from({ length: 30 }, (_, index) => ({
        id: index + 1,
        role: index % 2 ? "assistant" : "user",
        text: `Message ${index + 1}: ${"Meal planning details. ".repeat(10)}`,
        created_at: timestamp,
      })),
    };
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({ json: saved }),
    );
    await page.route(
      `**/api/conversations/${conversationId}/messages`,
      async (route) => {
        saved = {
          ...saved,
          messages: [
            ...saved.messages,
            {
              id: 31,
              role: "assistant",
              text: "Latest reply",
              created_at: timestamp,
            },
          ],
        };
        await route.fulfill({ json: saved });
      },
    );
    await page.goto(`/conversations/${conversationId}`);
    const history = page.getByRole("region", { name: "Conversation history" });
    const composer = page.getByLabel("Continue the conversation");
    await expect(history).toBeVisible();
    await expect(composer).toBeInViewport();
    await expect
      .poll(() => history.evaluate((node) => node.scrollTop))
      .toBeGreaterThan(0);
    const composerBounds = await composer.boundingBox();
    expect(composerBounds!.height).toBeLessThanOrEqual(48);
    for (const name of [
      "Attach file",
      "Start voice mode",
      "Scan barcode",
      "Send Order Request",
    ]) {
      const button = page.getByRole("button", { name, exact: true });
      const bounds = await button.boundingBox();
      expect(bounds!.y + bounds!.height / 2).toBeCloseTo(
        composerBounds!.y + composerBounds!.height / 2,
        0,
      );
      expect(bounds!.x).toBeGreaterThanOrEqual(
        composerBounds!.x + composerBounds!.width,
      );
    }
    const voice = page.getByRole("button", { name: "Start voice mode" });
    await expect(voice).toBeEnabled();
    expect(await voice.boundingBox()).toMatchObject({ width: 44, height: 44 });
    await expect(voice).toHaveCSS("border-radius", "9999px");
    await expect(voice.locator('svg[aria-hidden="true"]')).toHaveCount(1);
    await page.screenshot({ path: testInfo.outputPath("voice-composer.png") });
    await expect(
      page.getByText("Send Order Request", { exact: true }),
    ).toHaveCount(0);
    await history.hover();
    await page.mouse.wheel(0, -100000);
    await expect.poll(() => history.evaluate((node) => node.scrollTop)).toBe(0);
    expect(await composer.boundingBox()).toEqual(composerBounds);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    await composer.fill("Please continue");
    await expect(voice).toBeDisabled();
    await page.getByRole("button", { name: "Send Order Request" }).click();
    await expect(
      page.getByText("Latest reply", { exact: true }),
    ).toBeInViewport();
    await expect(
      page.getByRole("button", { name: "Send Order Request" }),
    ).toBeInViewport();
    expect(
      await page.evaluate(() => document.documentElement.scrollHeight),
    ).toBeLessThanOrEqual(height);
    await page.screenshot({ path: testInfo.outputPath("chat-scroll.png") });
  });
}

test("an expired hosted image leaves the recipe text readable", async ({
  page,
}) => {
  await mockSession(page);
  const saved: Conversation = {
    ...blankConversation,
    messages: [
      {
        id: 2,
        role: "assistant",
        text: "Cook the pasta and add tomato sauce.",
        created_at: timestamp,
        image: {
          url: "https://res.cloudinary.com/test-cloud/image/upload/v123/expired.png",
          width: 1024,
          height: 768,
        },
      },
    ],
  };
  await page.route("https://res.cloudinary.com/**", (route) =>
    route.fulfill({ status: 404 }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: saved }),
  );
  await page.goto(`/conversations/${conversationId}`);
  await expect(
    page.getByText("This illustration is currently unavailable."),
  ).toBeVisible();
  await expect(
    page.getByText("Cook the pasta and add tomato sauce."),
  ).toBeVisible();
});

test("request starts a meal conversation and keeps messages through refresh", async ({
  page,
}) => {
  await mockSession(page);
  let saved: Conversation = structuredClone(blankConversation);
  const keys: string[] = [];
  await page.route("**/api/conversations", (route) =>
    route.fulfill({ json: saved }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: saved }),
  );
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      const body = route.request().postDataJSON();
      keys.push(body.idempotency_key);
      expect(route.request().headers()["x-csrf-token"]).toBe(
        session.csrf_token,
      );
      saved = {
        ...saved,
        messages: [
          { id: 1, role: "user", text: body.text, created_at: timestamp },
          {
            id: 2,
            role: "assistant",
            text: "Here is a proposed recipe. Review the verified basket before confirming.",
            created_at: timestamp,
            proposal_id: proposalId,
            meal_plan: {
              title: "Carbonara",
              portions: 200,
              ingredients: [
                {
                  name: "Spaghetti",
                  amount: "20",
                  unit: "KG",
                  product_id: "pasta",
                  status: "proposed",
                },
              ],
              notes: ["Recipe quantities are estimates."],
            },
          },
        ],
        purchases: [proposal],
      };
      await route.fulfill({ json: saved });
    },
  );
  await page.goto("/request");
  await expect(
    page.getByRole("heading", { name: "Aimo Kitchen Assistant" }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "I need ingredients for 200 portions of carbonara.",
    })
    .click();
  await page.getByLabel("Your meal or purchasing request").press("Enter");
  await expect(page).toHaveURL(new RegExp(`/conversations/${conversationId}$`));
  await expect(
    page.getByRole("heading", { name: "Carbonara", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Proposed items" }),
  ).toContainText("SKU pasta");
  await expect(
    page.getByRole("complementary", { name: "Overview" }),
  ).toBeVisible();
  await expect(
    page.getByText("Messages never authorize a purchase.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByLabel("Continue the conversation")).toHaveValue("");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Carbonara", exact: true }),
  ).toBeVisible();
  expect(keys).toHaveLength(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/chat-mobile.png",
    fullPage: true,
  });
});

test("a lost message response reuses its idempotency key after refresh", async ({
  page,
}) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  let attempts = 0;
  const keys: string[] = [];
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      keys.push(route.request().postDataJSON().idempotency_key);
      attempts++;
      if (attempts === 1)
        await route.fulfill({
          status: 503,
          json: {
            error: {
              code: "PROVIDER_TIMEOUT",
              message: "Provider timed out. Retry this request.",
            },
          },
        });
      else
        await route.fulfill({
          json: {
            ...blankConversation,
            messages: [
              {
                id: 1,
                role: "assistant",
                text: "What delivery date do you need?",
                created_at: timestamp,
              },
            ],
          },
        });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  await page.getByLabel("Continue the conversation").fill("Carbonara for 200");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(page.getByRole("alert")).toContainText("Retry this request");
  await page.reload();
  await expect(page.getByLabel("Continue the conversation")).toHaveValue(
    "Carbonara for 200",
  );
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(page.getByText("What delivery date do you need?")).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
});

test("purchase deep links survive sign-in and confirmation requires an explicit click", async ({
  page,
}) => {
  await mockSession(page, false);
  let current = structuredClone(proposal);
  const confirmations: components["schemas"]["CommitRequest"][] = [];
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    confirmations.push(route.request().postDataJSON());
    expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf_token);
    current = {
      ...current,
      order_status: "accepted_mock",
      approval_status: "approved",
      order_id: "order-123",
      can_decide: false,
    };
    await route.fulfill({
      json: { status: "accepted_mock", order_id: "order-123" },
    });
  });
  await page.goto(`/purchases/${proposalId}`);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password", { exact: true }).fill("password-for-test");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/purchases/${proposalId}$`));
  await expect(
    page.getByRole("button", { name: "Approve & Push to Dispatch" }),
  ).toBeVisible();
  expect(confirmations).toEqual([]);
  await page
    .getByRole("button", { name: "Approve & Push to Dispatch" })
    .click();
  await expect(page.locator(".order-reference")).toContainText("order-123");
  expect(confirmations).toEqual([
    {
      proposal_id: proposalId,
      revision: 1,
      idempotency_key: expect.stringMatching(
        new RegExp(`^customer-confirm-${proposalId}-1-[a-f0-9]{24}$`),
      ),
    },
  ]);
  await expect(
    page.getByRole("button", { name: "Approve & Push to Dispatch" }),
  ).toHaveCount(0);
});

test("changed terms require a second explicit confirmation of the new revision", async ({
  page,
}) => {
  await mockSession(page);
  let current = structuredClone(proposal);
  const revisions: number[] = [];
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    revisions.push(route.request().postDataJSON().revision);
    current = { ...current, revision: 2, current_revision: 2 };
    await route.fulfill({ json: { ...current, status: "revised" } });
  });
  await page.goto(`/purchases/${proposalId}`);
  await page
    .getByRole("button", { name: "Approve & Push to Dispatch" })
    .click();
  await expect(page.getByRole("status")).toContainText("Terms changed");
  await expect(
    page.locator(".purchase-sheet").getByText("Revision 2 / v1"),
  ).toBeVisible();
  expect(revisions).toEqual([1]);
  await page
    .getByRole("button", { name: "Approve & Push to Dispatch" })
    .click();
  expect(revisions).toEqual([1, 2]);
});

test("legacy approval links keep the original revision and closed states have no confirmation", async ({
  page,
}) => {
  await mockSession(page, false);
  const historical = {
    ...proposal,
    current_revision: 2,
    committed_revision: 2,
    approval_status: "superseded",
    can_decide: false,
  };
  await page.route(`**/api/approvals/${approvalId}`, (route) =>
    route.fulfill({ json: historical }),
  );
  await page.goto(`/approvals/${approvalId}`);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password", { exact: true }).fill("password-for-test");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/approvals/${approvalId}$`));
  await expect(
    page.locator(".purchase-sheet").getByText("Revision 1 / v1"),
  ).toBeVisible();
  await expect(page.locator(".status-note")).toContainText("Superseded");
  await expect(
    page.getByRole("link", { name: "View current revision 2" }),
  ).toHaveAttribute("href", `/purchases/${proposalId}`);
  await expect(
    page.getByRole("button", { name: "Approve & Push to Dispatch" }),
  ).toHaveCount(0);
  for (const state of ["rejected", "expired"]) {
    await page.route(`**/api/purchases/${proposalId}`, (route) =>
      route.fulfill({
        json: {
          ...proposal,
          approval_status: state === "rejected" ? "rejected" : "pending",
          can_decide: false,
          expires_at:
            state === "expired" ? "2020-01-01T00:00:00Z" : proposal.expires_at,
        },
      }),
    );
    await page.goto(`/purchases/${proposalId}`);
    await expect(page.locator(".status-note")).toContainText(
      state === "expired" ? "Expired" : "Rejected",
    );
    await expect(
      page.getByRole("button", { name: "Approve & Push to Dispatch" }),
    ).toHaveCount(0);
  }
});

test("history retains completed purchases and reports an actionable refresh error", async ({
  page,
}) => {
  await mockSession(page);
  let fail = false;
  await page.route("**/api/purchases?*", (route) =>
    route.fulfill(
      fail
        ? {
            status: 503,
            json: {
              error: {
                code: "HISTORY_UNAVAILABLE",
                message:
                  "History is temporarily unavailable. Refresh to retry.",
              },
            },
          }
        : {
            json: {
              items: [
                {
                  ...proposal,
                  approval_status: "approved",
                  order_status: "accepted_mock",
                  order_id: "saved-order",
                },
              ],
              next_offset: null,
            },
          },
    ),
  );
  await page.goto("/approvals");
  await expect(page).toHaveURL(/\/purchases$/);
  await expect(
    page.getByRole("heading", { name: "Past Orders" }),
  ).toBeVisible();
  await expect(page.locator(".purchase-row")).toContainText("Accepted (demo)");
  fail = true;
  await page.getByRole("button", { name: "Refresh purchases" }).click();
  await expect(page.getByRole("alert")).toContainText("Refresh to retry");
});

test("unfinished server turns restore the request and retry key on another browser", async ({
  page,
}) => {
  await mockSession(page);
  const retry = {
    text: "The same persisted meal request",
    idempotency_key: "persisted-retry-key",
  };
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: { ...blankConversation, retry_message: retry } }),
  );
  let payload: unknown;
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      payload = route.request().postDataJSON();
      await route.fulfill({
        json: {
          ...blankConversation,
          messages: [
            {
              id: 1,
              role: "assistant",
              text: "Your saved request resumed.",
              created_at: timestamp,
            },
          ],
        },
      });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  await expect(page.getByLabel("Continue the conversation")).toHaveValue(
    retry.text,
  );
  await expect(page.getByRole("alert")).toHaveText(
    "The response was interrupted. Retry this request to continue.",
  );
  await page.getByRole("button", { name: "Retry request" }).click();
  await expect(page.getByText("Your saved request resumed.")).toBeVisible();
  expect(payload).toEqual(retry);
});

test("an interrupted turn arriving through SSE restores the persisted retry action", async ({
  page,
}) => {
  await mockSession(page);
  const retry = {
    text: "Recover this interrupted request",
    idempotency_key: "sse-retry-key",
  };
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  let publish: () => void = () => {};
  const streamReady = new Promise<void>((resolve) => {
    publish = resolve;
  });
  await page.route(
    `**/api/conversations/${conversationId}/events`,
    async (route) => {
      await streamReady;
      await route.fulfill({
        contentType: "text/event-stream",
        body: `event: conversation\ndata: ${JSON.stringify({ ...blankConversation, retry_message: retry })}\n\n`,
      });
    },
  );
  let payload: unknown;
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      payload = route.request().postDataJSON();
      await route.fulfill({
        json: {
          ...blankConversation,
          messages: [
            {
              id: 1,
              role: "assistant",
              text: "The interrupted turn resumed.",
              created_at: timestamp,
            },
          ],
        },
      });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  await expect(
    page.getByRole("heading", { name: "Aimo Kitchen Assistant", exact: true }),
  ).toBeVisible();
  publish();
  await expect(page.getByLabel("Continue the conversation")).toHaveValue(
    retry.text,
  );
  await expect(page.getByRole("alert")).toHaveText(
    "The response was interrupted. Retry this request to continue.",
  );
  await page.getByRole("button", { name: "Retry request" }).click();
  await expect(page.getByText("The interrupted turn resumed.")).toBeVisible();
  expect(payload).toEqual(retry);
});

test(`recipe plan keeps unresolved ingredients visible beside matched packs`, async ({
  page,
}) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({
      json: {
        ...blankConversation,
        messages: [
          {
            id: 1,
            role: "assistant",
            text: "The recipe needs more product evidence.",
            created_at: timestamp,
            meal_plan: {
              title: "Carbonara",
              portions: 200,
              attribution: "UniTools — theunitools.com / CC BY-SA 4.0",
              ingredients: [
                {
                  name: "Dry spaghetti",
                  amount: "20",
                  unit: "KG",
                  status: "matched",
                  product_id: "465236",
                  conversion: {
                    sales_quantity: "7",
                    sales_unit: "ST",
                    excess: "1",
                  },
                },
                {
                  name: "Whole eggs",
                  amount: "120",
                  unit: "piece",
                  status: "matched",
                  product_id: "egg-tray",
                  conversion: {
                    sales_quantity: "4",
                    sales_unit: "ST",
                    excess: "0",
                  },
                },
                {
                  name: "Salt",
                  amount: null,
                  unit: "tsp",
                  status: "unresolved",
                  reason:
                    "Recipe quantity is unspecified; provide a reviewed numeric quantity.",
                },
              ],
              notes: ["Recipe quantities are estimates for customer review."],
            },
          },
        ],
      },
    }),
  );
  await page.goto(`/conversations/${conversationId}`);
  const plan = page.getByRole("region", { name: "Proposed meal plan" });
  await expect(
    plan.getByText("Free-form plan — recipe completeness not checked.", {
      exact: true,
    }),
  ).toHaveCount(1);
  await expect(plan.getByText("Salt", { exact: true })).toBeVisible();
  await expect(
    plan.getByText("Quantity unresolved", { exact: true }),
  ).toBeVisible();
  await expect(
    plan.getByText("Quantity unresolved tsp", { exact: true }),
  ).toHaveCount(0);
  await expect(
    plan.getByText("Recipe quantity is unspecified", { exact: false }),
  ).toBeVisible();
  await expect(plan.getByText("Buy 7 ST", { exact: false })).toBeVisible();
  await expect(plan.getByText("Excess: 1 KG", { exact: false })).toBeVisible();
  await expect(plan.getByText("Buy 4 ST", { exact: true })).toBeVisible();
  await expect(plan.getByText("Excess: 0", { exact: false })).toHaveCount(0);
  await expect(plan.getByText("UniTools", { exact: false })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Review basket and purchasing checks" }),
  ).toHaveCount(0);
});
for (const basis of ["free_form", "saved_recipe"] as const) {
  test(`purchase review identifies ${basis} basket before confirmation`, async ({
    page,
  }) => {
    await mockSession(page);
    await page.route(`**/api/purchases/${proposalId}`, (route) =>
      route.fulfill({ json: { ...proposal, recipe_basis: basis } }),
    );
    await page.goto(`/purchases/${proposalId}`);
    await expect(
      page.getByText(
        basis === "saved_recipe"
          ? "Recipe-backed basket — includes every ingredient from the saved recipe plan."
          : "Free-form basket — recipe completeness and ingredient conversions are not checked against a saved recipe.",
        { exact: true },
      ),
    ).toHaveCount(1);
    await expect(
      page.getByRole("button", { name: "Approve & Push to Dispatch" }),
    ).toBeVisible();
  });
}

for (const width of [1440, 390]) {
  test(`designer Home and navigation work at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockSession(page);
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Welcome, demo-hotel" }),
    ).toBeVisible();
    await expect(
      page.getByText("Delivery schedule is not available yet."),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Recent Past Orders" }),
    ).toBeVisible();
    if (width < 768) {
      await page.getByRole("button", { name: "Open menu" }).click();
      const menu = page.getByRole("dialog", { name: "Menu", exact: true });
      await expect(menu).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(
        page.getByRole("button", { name: "Open menu" }),
      ).toBeFocused();
      await page.getByRole("button", { name: "Open menu" }).click();
      await menu.getByRole("link", { name: "Request", exact: true }).click();
      await expect(menu).toHaveCount(0);
    } else {
      const nav = page.getByRole("complementary", { name: "Sidebar" });
      await nav.getByRole("button", { name: "Hide conversations" }).click();
      await expect(
        nav.getByRole("list", { name: "Conversations" }),
      ).toHaveCount(0);
      await nav.getByRole("button", { name: "Show conversations" }).click();
      await expect(
        nav.getByRole("link", { name: blankConversation.title }),
      ).toBeVisible();
      await nav.getByRole("link", { name: "Request", exact: true }).click();
    }
    await expect(page).toHaveURL(/\/request$/);
    await expect(
      page.getByRole("heading", { name: "Aimo Kitchen Assistant" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Attach file" }),
    ).toBeDisabled();
    await expect(
      page.getByRole("complementary", { name: "Overview" }),
    ).toContainText("Nothing staged");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  });

  test(`Overview confirms exact revisions and retains receipts at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockSession(page);
    let current = structuredClone(proposal);
    const revisions: number[] = [];
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({
        json: {
          ...blankConversation,
          purchases: [proposal],
          messages: [
            {
              id: 1,
              role: "assistant",
              text: "Please review your basket.",
              created_at: timestamp,
              proposal_id: proposalId,
            },
          ],
        },
      }),
    );
    await page.route(`**/api/purchases/${proposalId}`, (route) =>
      route.fulfill({ json: current }),
    );
    await page.route(`**/api/purchases/${proposalId}/confirm`, (route) => {
      const body = route.request().postDataJSON();
      expect(route.request().headers()["x-csrf-token"]).toBe(
        session.csrf_token,
      );
      revisions.push(body.revision);
      if (revisions.length === 1) {
        current = { ...current, revision: 2, current_revision: 2 };
        return route.fulfill({ json: { ...current, status: "revised" } });
      }
      current = {
        ...current,
        approval_status: "approved",
        order_status: "accepted_mock",
        order_id: "overview-order",
        can_decide: false,
      };
      return route.fulfill({
        json: { status: "accepted_mock", order_id: "overview-order" },
      });
    });
    await page.goto(`/conversations/${conversationId}`);
    const panel = page.getByRole("complementary", { name: "Overview" });
    await expect(panel).toContainText("1 items staged");
    await expect(
      page.getByRole("list", { name: "Proposed items" }),
    ).toContainText("4 BAG");
    if (width < 768) {
      await expect(
        panel.getByRole("button", { name: "Approve & Push to Dispatch" }),
      ).not.toBeVisible();
      await panel.getByRole("button", { name: "Expand overview" }).click();
    }
    await expect(
      panel.getByRole("button", { name: "Save as Draft" }),
    ).toBeDisabled();
    await expect(
      panel.getByRole("button", { name: "Export Manifest" }),
    ).toBeDisabled();
    await expect(
      panel.getByRole("switch", { name: "Substitutions allowed" }),
    ).toBeDisabled();
    expect(revisions).toEqual([]);
    await panel
      .getByRole("button", { name: "Approve & Push to Dispatch" })
      .click();
    await expect(panel.getByRole("status")).toContainText("Terms changed");
    expect(revisions).toEqual([1]);
    await panel
      .getByRole("button", { name: "Approve & Push to Dispatch" })
      .click();
    await expect(panel.locator(".order-reference")).toContainText(
      "overview-order",
    );
    await expect(panel).toContainText("Accepted by demo order service");
    await expect(
      panel.getByRole("button", { name: "Approve & Push to Dispatch" }),
    ).toHaveCount(0);
    expect(revisions).toEqual([1, 2]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  });
}

test("Past Orders fills sparse API pages, expands rows and resolves an older deep link", async ({
  page,
}) => {
  await mockSession(page);
  const accepted = {
    ...proposal,
    order_id: "accepted-order",
    order_status: "accepted_mock",
    can_decide: false,
  };
  const offsets: number[] = [];
  await page.route("**/api/purchases?*", (route) => {
    const offset = Number(
      new URL(route.request().url()).searchParams.get("offset"),
    );
    offsets.push(offset);
    return route.fulfill({
      json:
        offset === 0
          ? { items: [proposal], next_offset: 20 }
          : { items: [accepted], next_offset: null },
    });
  });
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: accepted }),
  );
  await page.goto("/purchases");
  await expect(page.locator(".purchase-row")).toHaveCount(1);
  expect(offsets).toContain(20);
  const row = page.locator(".purchase-row");
  await expect(row).toContainText("Accepted (demo)");
  await row
    .getByRole("button", { name: "Order details: Carbonara for 200" })
    .click();
  await expect(row.getByText("Ordered items", { exact: true })).toBeVisible();
  await expect(row.locator(".purchase-sheet")).toContainText("Spaghetti 5 kg");
  await expect(
    page.getByRole("button", { name: "Approve & Push to Dispatch" }),
  ).toHaveCount(0);
  await page.goto(`/purchases/${proposalId}`);
  await expect(
    page.getByRole("button", { name: "Order details: Carbonara for 200" }),
  ).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".purchase-sheet")).toBeVisible();
});

for (const state of ["denied", "expired", "rejected"] as const) {
  test(`Overview preserves ${state} purchasing controls`, async ({ page }) => {
    await mockSession(page);
    const current: Proposal = {
      ...proposal,
      policy_outcome: state === "denied" ? "denied" : proposal.policy_outcome,
      approval_status:
        state === "rejected" ? "rejected" : proposal.approval_status,
      expires_at:
        state === "expired" ? "2020-01-01T00:00:00Z" : proposal.expires_at,
      can_decide: false,
    };
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({ json: { ...blankConversation, purchases: [current] } }),
    );
    await page.route(`**/api/purchases/${proposalId}`, (route) =>
      route.fulfill({ json: current }),
    );
    await page.goto(`/conversations/${conversationId}`);
    const panel = page.getByRole("complementary", { name: "Overview" });
    await expect(panel).toContainText("1 items staged");
    await expect(
      panel.getByRole("button", { name: "Approve & Push to Dispatch" }),
    ).toHaveCount(0);
    if (state === "denied")
      await expect(panel.getByRole("alert")).toContainText(
        "cannot be approved",
      );
    else
      await expect(panel.locator(".status-note")).toContainText(
        state === "expired" ? "Expired" : "Rejected",
      );
  });
}

test("Overview rejection retains the server decision without placing an order", async ({
  page,
}) => {
  await mockSession(page);
  let current = structuredClone(proposal);
  let confirmations = 0;
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: { ...blankConversation, purchases: [proposal] } }),
  );
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, (route) => {
    confirmations++;
    return route.abort();
  });
  await page.route(`**/api/approvals/${approvalId}/decision`, (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf_token);
    expect(route.request().postDataJSON()).toEqual({
      decision: "reject",
      revision: 1,
    });
    current = { ...current, approval_status: "rejected", can_decide: false };
    return route.fulfill({ json: current });
  });
  await page.goto(`/conversations/${conversationId}`);
  const panel = page.getByRole("complementary", { name: "Overview" });
  await panel.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Rejection recorded");
  await expect(
    panel.getByRole("button", { name: "Approve & Push to Dispatch" }),
  ).toHaveCount(0);
  expect(confirmations).toBe(0);
});
