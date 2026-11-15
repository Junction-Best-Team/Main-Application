import { expect, test, type Page } from "@playwright/test";
import type { components } from "../src/shared/api/schema";
import type {
  Conversation,
  OrderListItem,
  Proposal,
  Session,
} from "../src/shared/api/types";
import { ordersPage, schedule } from "./support/schedulerFixtures";

const session: Session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf",
  role: "approver",
  scheduler_demo_mode: false,
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
  cart_editable: false,
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
const placedOrder: OrderListItem = {
  status: "placed",
  title: "Carbonara for 200",
  proposal_id: proposalId,
  order_id: "accepted-order",
  paused: false,
  line_count: 1,
  gross_total: "114.00",
  currency: "EUR",
  updated_at: timestamp,
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
  // The cart card reads the buyer's destinations; an unmocked request would fall through to a dead proxy.
  await page.route("**/api/settings/policy", (route) =>
    route.fulfill({
      json: {
        buyer_id: "demo-hotel",
        policy_version: 1,
        rules: { currency: "EUR", destinations: ["hotel-helsinki"] },
        can_edit: true,
        approval_authority: { can_approve: true },
        history: [],
      },
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
  await page.route("**/api/orders?*", (route) =>
    route.fulfill({ json: ordersPage([]) }),
  );
  await page.route("**/api/schedules?*", (route) =>
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
  test(`recipe draft appears in Overview before a basket at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await mockSession(page);
    const plan = {
      title: "Vegan lasagna estimate",
      portions: 500,
      base_servings: 4,
      ingredients: [
        {
          name: "Dry lasagna sheets",
          amount: "50",
          unit: "KG",
          status: "proposed" as const,
        },
        {
          name: "Plant mince",
          amount: "75",
          unit: "KG",
          status: "proposed" as const,
        },
        {
          name: "Tomato sauce",
          amount: "125",
          unit: "L",
          status: "proposed" as const,
        },
      ],
      notes: [
        "Assistant-drafted recipe estimate; ingredient quantities need review.",
      ],
    };
    let prepared = false;
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({
        json: {
          ...blankConversation,
          // A newer draft must replace an earlier purchase in Overview, without deleting history.
          purchases: [proposal],
          messages: [
            {
              id: 1,
              role: "assistant",
              text: "Earlier basket",
              proposal_id: proposalId,
              created_at: timestamp,
            },
            {
              id: 2,
              role: "user",
              text: "Now plan vegan lasagna for 500 people.",
              created_at: timestamp,
            },
            {
              id: 3,
              role: "assistant",
              text: "Here is the recipe estimate for 500 portions.",
              meal_plan: plan,
              proposal_id: prepared ? proposalId : null,
              created_at: timestamp,
            },
          ],
        },
      }),
    );
    await page.goto(`/conversations/${conversationId}`);
    const overview = page.getByRole("complementary", { name: "Overview" });
    await expect(overview).toContainText("3 draft ingredients");
    await expect(overview).toContainText("500 portions");
    await expect(overview).toContainText("50 KG");
    await expect(overview).toContainText("125 L");
    await expect(overview).not.toContainText("Nothing staged");
    await expect(
      overview.getByRole("button", { name: "Confirm purchase" }),
    ).toBeDisabled();
    await expect(overview).not.toContainText("Total estimated");
    await expect(page.locator("body")).toHaveJSProperty("scrollWidth", width);
    await page.screenshot({
      path: testInfo.outputPath(`recipe-draft-${width}.png`),
      fullPage: true,
    });
    await page.reload();
    await expect(overview).toContainText("3 draft ingredients");
    // A real proposal takes over; only then are price and confirmation controls displayed.
    prepared = true;
    await page.reload();
    await expect(overview).toContainText("1 items staged");
    await expect(overview).toContainText("Total estimated");
    await expect(
      overview.getByRole("button", { name: "Confirm purchase" }),
    ).toBeVisible();
    await expect(overview).not.toContainText("3 draft ingredients");
  });
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
      activity: {
        turn_id: "scroll-test-turn",
        state: "complete",
        events: [
          { sequence: 1, kind: "started", label: "Checking your request" },
          { sequence: 2, kind: "thinking", label: "Thinking" },
          { sequence: 3, kind: "complete", label: "Finished" },
        ],
      },
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
    const expectBesideComposer = async (name: string) => {
      const button = page.getByRole("button", { name, exact: true });
      const bounds = await button.boundingBox();
      expect(bounds!.y + bounds!.height / 2).toBeCloseTo(
        composerBounds!.y + composerBounds!.height / 2,
        0,
      );
      expect(bounds!.x).toBeGreaterThanOrEqual(
        composerBounds!.x + composerBounds!.width,
      );
    };
    // Voice and send take turns in a single action slot.
    await expect(
      page.getByRole("button", { name: "Scan barcode" }),
    ).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Attach file" })).toHaveCount(
      0,
    );
    const voice = page.getByRole("button", { name: "Start voice mode" });
    const send = page.getByRole("button", { name: "Send Order Request" });
    await expectBesideComposer("Start voice mode");
    await expect(send).toHaveCount(0);
    await expect(voice).toBeEnabled();
    expect(await voice.boundingBox()).toMatchObject({ width: 44, height: 44 });
    await expect(voice).toHaveCSS("border-radius", "9999px");
    await expect(voice.locator('svg[aria-hidden="true"]')).toHaveCount(1);
    await page.screenshot({ path: testInfo.outputPath("voice-composer.png") });
    await expect(
      page.getByText("Send Order Request", { exact: true }),
    ).toHaveCount(0);
    // Screen-reader-only activity labels must stay inside the history's scroll
    // boundary, including while its completed steps are expanded.
    await page.getByRole("button", { name: /Show 2 steps/ }).click();
    await expect(
      page.getByRole("list", { name: "Activity steps" }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollHeight),
    ).toBeLessThanOrEqual(height);
    await page.getByRole("button", { name: /Hide 2 steps/ }).click();
    await history.hover();
    await page.mouse.wheel(0, -100000);
    await expect.poll(() => history.evaluate((node) => node.scrollTop)).toBe(0);
    expect(await composer.boundingBox()).toEqual(composerBounds);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    await composer.fill("   ");
    await expect(voice).toBeVisible();
    await expect(send).toHaveCount(0);
    await composer.fill("Please continue");
    await expect(voice).toHaveCount(0);
    await expectBesideComposer("Send Order Request");
    await expect(send).toHaveCSS("border-radius", "9999px");
    await send.click();
    await expect(
      page.getByText("Latest reply", { exact: true }),
    ).toBeInViewport();
    await expect(send).toHaveCount(0);
    await expect(voice).toBeInViewport();
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
    page.getByRole("complementary", { name: "Overview" }),
  ).toHaveCount(0);
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
  const recipe = page.getByRole("region", { name: "Proposed meal plan" });
  await expect(recipe.getByText("20 KG", { exact: true })).not.toBeVisible();
  await recipe
    .getByText("Recipe quantities and assumptions", { exact: true })
    .click();
  await expect(recipe.getByText("20 KG", { exact: true })).toBeVisible();
  await recipe
    .getByText("Recipe quantities and assumptions", { exact: true })
    .click();
  await expect(
    page.getByRole("complementary", { name: "Overview" }),
  ).toBeVisible();
  await expect(
    page.getByText("Messages never authorize a purchase.", { exact: false }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Continue the conversation")).toHaveValue("");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Carbonara", exact: true }),
  ).toBeVisible();
  expect(keys).toHaveLength(1);
  await page.getByRole("log", { name: "Conversation messages" }).screenshot({
    path: "test-results/recipe-and-basket-desktop.png",
  });
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

for (const priced of [false, true]) {
  test(`SKU cards preserve ${priced ? "verified zero prices" : "unknown prices"}`, async ({
    page,
  }) => {
    await mockSession(page);
    const current = structuredClone(proposal);
    const value = priced ? "0.00" : null;
    Object.assign(current.snapshot.lines[0], {
      net: value,
      gross: value,
      tax: value,
    });
    Object.assign(current.snapshot, {
      net_total: value,
      gross_total: value,
      tax_total: value,
    });
    if (!priced) {
      current.policy_outcome = "needs_resolution";
      current.can_decide = false;
    }
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({
        json: {
          ...blankConversation,
          messages: [
            {
              id: 2,
              role: "assistant",
              text: "Review your basket.",
              created_at: timestamp,
              proposal_id: proposalId,
            },
          ],
          purchases: [current],
        },
      }),
    );
    await page.goto(`/conversations/${conversationId}`);
    const items = page.getByRole("list", { name: "Proposed items" });
    if (priced) {
      await expect(items.getByText("€0.00", { exact: true })).toHaveCount(2);
    } else {
      await expect(items.getByText("Unresolved", { exact: true })).toHaveCount(
        2,
      );
      await expect(items).not.toContainText("€0.00");
    }
  });
}

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

test("Enter submits the composer when a draft is ready", async ({ page }) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  let posted = false;
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      posted = true;
      await route.fulfill({
        json: {
          ...blankConversation,
          messages: [
            {
              id: 1,
              role: "assistant",
              text: "Got it — what delivery date?",
              created_at: timestamp,
            },
          ],
        },
      });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  const composer = page.getByLabel("Continue the conversation");
  await composer.fill("Carbonara for 200");
  await composer.press("Enter");
  await expect(page.getByText("Got it — what delivery date?")).toBeVisible();
  expect(posted).toBe(true);
});

test("composer clears as soon as send starts", async ({ page }) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      await gate;
      await route.fulfill({
        json: {
          ...blankConversation,
          messages: [
            {
              id: 1,
              role: "user",
              text: "Carbonara for 200",
              created_at: timestamp,
            },
            {
              id: 2,
              role: "assistant",
              text: "Got it — what delivery date?",
              created_at: timestamp,
            },
          ],
        },
      });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  const composer = page.getByLabel("Continue the conversation");
  await composer.fill("Carbonara for 200");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(composer).toHaveValue("");
  release();
  await expect(page.getByText("Got it — what delivery date?")).toBeVisible();
  await expect(composer).toHaveValue("");
});

test("Home does not restore the accepted first message while Aimo is working", async ({
  page,
}) => {
  await mockSession(page);
  const text = "i would like to cook 200 carbonara";
  await page.route("**/api/conversations", (route) =>
    route.fulfill({ json: blankConversation }),
  );
  let accepted = blankConversation;
  let acknowledge!: () => void;
  const acceptedReady = new Promise<void>((resolve) => {
    acknowledge = resolve;
  });
  await page.route(`**/api/conversations/${conversationId}`, async (route) => {
    await acceptedReady;
    await route.fulfill({ json: accepted });
  });
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const posted: string[] = [];
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      const body = route.request().postDataJSON();
      posted.push(body.text);
      // The real API exposes retry metadata for unfinished text-only turns,
      // including a queued/running turn. It does not mean the send failed.
      accepted = {
        ...blankConversation,
        busy: true,
        retry_message: {
          text: body.text,
          idempotency_key: body.idempotency_key,
        },
        messages: [{ id: 1, role: "user", text, created_at: timestamp }],
      };
      acknowledge();
      await gate;
      await route.fulfill({ json: accepted });
    },
  );
  await page.goto("/");
  await page.getByLabel("Your meal or purchasing request").fill(text);
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(page).toHaveURL(new RegExp(`/conversations/${conversationId}$`));
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  const composer = page.getByLabel("Continue the conversation");
  await expect(composer).toHaveValue("");
  release();
  await expect
    .poll(() =>
      page.evaluate(
        (key) => sessionStorage.getItem(key),
        `aimo-pending-${session.buyer_id}-${conversationId}`,
      ),
    )
    .toBeNull();
  await expect(composer).toHaveValue("");
  await page.reload();
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  await expect(composer).toHaveValue("");
  expect(posted).toEqual([text]);
});

test("messages typed while Aimo works queue above the composer and send in order", async ({
  page,
}) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const posted: string[] = [];
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      const text = route.request().postDataJSON().text as string;
      posted.push(text);
      if (posted.length === 1) await gate;
      await route.fulfill({
        json: {
          ...blankConversation,
          messages: posted.map((message, index) => ({
            id: index + 1,
            role: "user",
            text: message,
            created_at: timestamp,
          })),
        },
      });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  const composer = page.getByLabel("Continue the conversation");
  await expect(composer).toBeFocused();
  await composer.fill("Carbonara for 200");
  await composer.press("Enter");
  await expect(composer).toHaveValue("");
  await expect(composer).toBeFocused();

  await composer.fill("Add a vegetarian option");
  await composer.press("Enter");
  await composer.fill("Never mind this one");
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  await composer.press("Enter");
  await expect(composer).toBeFocused();
  const queued = page.getByRole("list", { name: "Queued messages" });
  await expect(queued.getByRole("listitem")).toContainText([
    "Add a vegetarian option",
    "Never mind this one",
  ]);

  await page
    .getByRole("button", {
      name: "Remove queued message: Never mind this one",
    })
    .click();
  await expect(composer).toBeFocused();
  await expect(queued.getByRole("listitem")).toHaveCount(1);
  expect(posted).toEqual(["Carbonara for 200"]);

  release();
  await expect(queued).toHaveCount(0);
  await expect
    .poll(() => posted)
    .toEqual(["Carbonara for 200", "Add a vegetarian option"]);
  await expect(composer).toBeFocused();
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
    page.getByRole("button", { name: "Confirm purchase" }),
  ).toBeVisible();
  expect(confirmations).toEqual([]);
  await page.getByRole("button", { name: "Confirm purchase" }).click();
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
    page.getByRole("button", { name: "Confirm purchase" }),
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
  await page.getByRole("button", { name: "Confirm purchase" }).click();
  await expect(page.getByRole("status")).toContainText("Terms changed");
  await expect(
    page.locator(".purchase-sheet").getByText("Revision 2 / v1"),
  ).toBeVisible();
  expect(revisions).toEqual([1]);
  await page.getByRole("button", { name: "Confirm purchase" }).click();
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
    page.getByRole("button", { name: "Confirm purchase" }),
  ).toBeDisabled();
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
      page.getByRole("button", { name: "Confirm purchase" }),
    ).toBeDisabled();
  }
});

test("history retains completed purchases and reports an actionable refresh error", async ({
  page,
}) => {
  await mockSession(page);
  let fail = false;
  await page.route("**/api/orders?*", (route) =>
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
        : { json: ordersPage([placedOrder]) },
    ),
  );
  await page.goto("/approvals");
  await expect(page).toHaveURL(/\/purchases$/);
  await expect(
    page.getByRole("heading", { name: "Past Orders" }),
  ).toBeVisible();
  await expect(page.locator(".purchase-row")).toContainText("Placed");
  fail = true;
  // The list refreshes when the tab becomes visible again (useRefresh).
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await expect(page.getByRole("alert")).toContainText("Refresh to retry");
  await expect(page.locator(".purchase-row")).toContainText("Placed");
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
  await page.getByRole("button", { name: "Retry" }).click();
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
  await page.getByRole("button", { name: "Retry" }).click();
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
      page.getByRole("button", { name: "Confirm purchase" }),
    ).toBeVisible();
  });
}

for (const width of [1440, 390]) {
  test(`expanded requests stay under their parent at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 720 });
    await mockSession(page);
    const items = Array.from({ length: 31 }, (_, index) => ({
      ...blankConversation,
      id: `fa0d5e73-f5a5-4594-a1c5-${String(index).padStart(12, "0")}`,
      title: `Catering request ${index + 1}`,
    }));
    await page.route("**/api/conversations?*", (route) => {
      const older = new URL(route.request().url()).searchParams.get("offset");
      return route.fulfill({
        json: {
          items: older === "30" ? items.slice(30) : items.slice(0, 30),
          next_offset: older === "30" ? null : 30,
        },
      });
    });
    const last = items[30];
    await page.route(`**/api/conversations/${last.id}`, (route) =>
      route.fulfill({ json: last }),
    );
    await page.route(`**/api/conversations/${last.id}/events`, (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: ": heartbeat\n\n",
      }),
    );
    await page.goto("/");
    if (width < 768)
      await page.getByRole("button", { name: "Open menu" }).click();
    const nav =
      width < 768
        ? page.getByRole("dialog", { name: "Menu", exact: true })
        : page.getByRole("complementary", { name: "Sidebar" });
    const list = nav.getByRole("list", { name: "Conversations" });
    await expect(list.getByRole("link")).toHaveCount(30);
    const requests = nav.getByRole("link", { name: "Requests", exact: true });
    const schedule = nav.getByRole("link", { name: "Schedule", exact: true });
    const orders = nav.getByRole("link", { name: "Orders", exact: true });
    const requestsBox = (await requests.boundingBox())!;
    const listBox = (await list.boundingBox())!;
    const scheduleBox = (await schedule.boundingBox())!;
    expect(listBox.y).toBeGreaterThanOrEqual(
      requestsBox.y + requestsBox.height,
    );
    expect(listBox.x).toBeGreaterThan(requestsBox.x);
    const group = nav.locator("#nav-conversations");
    const groupBox = (await group.boundingBox())!;
    expect(scheduleBox.y).toBeGreaterThanOrEqual(groupBox.y + groupBox.height);
    await expect(schedule).toBeInViewport();
    await expect(orders).toBeInViewport();
    expect(
      await group.evaluate((el) => el.scrollHeight > el.clientHeight),
    ).toBe(true);
    await nav.getByRole("button", { name: "Hide conversations" }).click();
    await expect(list).toHaveCount(0);
    await nav.getByRole("button", { name: "Show conversations" }).click();
    await group.evaluate((el) => (el.scrollTop = el.scrollHeight));
    await nav.getByRole("button", { name: "Load older conversations" }).click();
    await expect(list.getByRole("link")).toHaveCount(31);
    const lastLink = list.getByRole("link", { name: last.title, exact: true });
    await lastLink.scrollIntoViewIfNeeded();
    await expect(lastLink).toBeInViewport();
    await expect(schedule).toBeInViewport();
    await expect(orders).toBeInViewport();
    await page.screenshot({
      path: testInfo.outputPath(`nested-requests-${width}.png`),
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await lastLink.click();
    await expect(page).toHaveURL(`/conversations/${last.id}`);
    if (width < 768) await expect(nav).toHaveCount(0);
  });
}

for (const width of [1440, 390]) {
  test(`minimal Home and navigation work at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockSession(page);
    await page.route("**/api/schedules?*", (route) =>
      route.fulfill({ json: { items: [schedule], next_offset: null } }),
    );
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "What are we cooking?" }),
    ).toBeVisible();
    // The strip under the chat box lists the customer's real standing orders.
    const strip = page.getByRole("region", { name: "Scheduled deliveries" });
    await expect(strip).toContainText("Breakfast dairy");
    await expect(strip).not.toContainText("Placeholder");
    await expect(strip.getByRole("link", { name: "View all" })).toHaveAttribute(
      "href",
      "/schedules",
    );
    if (width < 768) {
      await page.getByRole("button", { name: "Open menu" }).click();
      const menu = page.getByRole("dialog", { name: "Menu", exact: true });
      await expect(menu).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(
        page.getByRole("button", { name: "Open menu" }),
      ).toBeFocused();
      await page.getByRole("button", { name: "Open menu" }).click();
      await menu.getByRole("link", { name: "Requests", exact: true }).click();
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
      await nav.getByRole("link", { name: "Requests", exact: true }).click();
    }
    await expect(page).toHaveURL(/\/request$/);
    await expect(
      page.getByRole("heading", { name: "Aimo Kitchen Assistant" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Attach file" })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", { name: "Start voice mode" }),
    ).toBeEnabled();
    await expect(
      page.getByRole("complementary", { name: "Overview" }),
    ).toHaveCount(0);
    await expect(
      page.getByText("Mikael Virtanen", { exact: true }),
    ).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath(`empty-chat-${width}.png`),
    });
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
      panel.getByRole("button", { name: "Call account manager" }),
    ).toHaveCount(0);
    await expect(
      panel.getByText("Mikael Virtanen", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("list", { name: "Proposed items" }),
    ).toContainText("4 BAG");
    // The card is open by default now, so the confirm button is visible at every width.
    await expect(
      panel.getByRole("button", { name: "Confirm purchase" }),
    ).toBeVisible();
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
    await panel.getByRole("button", { name: "Confirm purchase" }).click();
    await expect(panel.getByRole("status")).toContainText("Terms changed");
    expect(revisions).toEqual([1]);
    await panel.getByRole("button", { name: "Confirm purchase" }).click();
    await expect(panel.locator(".order-reference")).toContainText(
      "overview-order",
    );
    await expect(panel).toContainText("Accepted by demo order service");
    await expect(
      panel.getByRole("button", { name: "Confirm purchase" }),
    ).toBeDisabled();
    expect(revisions).toEqual([1, 2]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  });
}

test("Past Orders pages the order list, expands placed rows and resolves an older deep link", async ({
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
  await page.route("**/api/orders?*", (route) => {
    const offset = Number(
      new URL(route.request().url()).searchParams.get("offset"),
    );
    offsets.push(offset);
    return route.fulfill({
      json:
        offset === 0
          ? ordersPage(
              [{ ...placedOrder, status: "pending", order_id: null }],
              20,
            )
          : ordersPage([placedOrder], null),
    });
  });
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: accepted }),
  );
  await page.goto("/purchases");
  // Fewer than five rows are visible, so the page keeps reading pages by next_offset itself.
  await expect(page.locator(".purchase-row")).toHaveCount(2);
  // React StrictMode may repeat the first request in development.
  expect([...new Set(offsets)]).toEqual([0, 20]);
  const row = page.locator(".purchase-row").nth(1);
  await expect(row).toContainText("Placed");
  await row
    .getByRole("button", { name: "Order details: Carbonara for 200" })
    .click();
  await expect(row.getByText("Ordered items", { exact: true })).toBeVisible();
  await expect(row.locator(".purchase-sheet")).toContainText("Spaghetti 5 kg");
  await expect(
    page.getByRole("button", { name: "Confirm purchase" }),
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
      panel.getByRole("button", { name: "Call account manager" }),
    ).toHaveCount(0);
    await expect(
      panel.getByText("Mikael Virtanen", { exact: true }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", { name: "Confirm purchase" }),
    ).toBeDisabled();
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
    panel.getByRole("button", { name: "Confirm purchase" }),
  ).toBeDisabled();
  expect(confirmations).toBe(0);
});

for (const width of [1440, 390, 320]) {
  test(`draft cart streams matches and checked prices before basket review at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await mockSession(page);
    const turnId = "aa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";
    let snapshot: Conversation = {
      ...blankConversation,
      busy: true,
      activity: { turn_id: turnId, state: "running", events: [] },
    };
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({ json: snapshot }),
    );
    let publish: () => void = () => {};
    const ready = new Promise<void>((resolve) => {
      publish = resolve;
    });
    await page.route(
      `**/api/conversations/${conversationId}/events`,
      async (route) => {
        await ready;
        await route.fulfill({
          contentType: "text/event-stream",
          body: `event: conversation\ndata: ${JSON.stringify(snapshot)}\n\n`,
        });
      },
    );
    await page.goto(`/conversations/${conversationId}`);
    await expect(
      page.getByRole("complementary", { name: "Overview" }),
    ).toHaveCount(0);
    // The card is always in a chat: empty, with its purchase button greyed out.
    await expect(
      page.getByRole("complementary", { name: "Your order" }),
    ).toContainText("Your cart is empty");
    snapshot = {
      ...snapshot,
      messages: [
        {
          id: 1,
          role: "assistant",
          text: "Recipe estimate for 200 portions.",
          created_at: timestamp,
          meal_plan: {
            title: "Pasta lunch",
            portions: 200,
            ingredients: [
              { name: "Pasta", amount: "20", unit: "KG", status: "proposed" },
              { name: "Salt", amount: null, unit: "g", status: "unresolved" },
            ],
            notes: ["Assistant-drafted recipe estimate."],
          },
        },
      ],
      draft_cart: {
        turn_id: turnId,
        title: "Pasta lunch",
        items: [
          { name: "Pasta", amount: "20", unit: "KG", matched: false },
          { name: "Salt", amount: null, unit: "g", matched: false },
        ],
      },
    };
    publish();
    const draft = page.getByRole("complementary", { name: "Your order" });
    await expect(draft.getByRole("status")).toHaveText("Preparing your order…");
    await expect(
      page.getByRole("complementary", { name: "Overview" }),
    ).toHaveCount(0); // The live cart takes precedence over the saved recipe draft.
    await expect(
      draft.getByText("Product to match", { exact: true }),
    ).toHaveCount(2);
    await expect(
      draft.getByText("Price not checked", { exact: true }),
    ).toHaveCount(2);
    // Nothing has a product yet, so the card's purchase button is greyed out.
    await expect(
      draft.getByRole("button", { name: "Confirm purchase" }),
    ).toBeDisabled();
    snapshot = {
      ...snapshot,
      draft_cart: {
        ...snapshot.draft_cart!,
        items: [
          {
            name: "Pasta",
            amount: "20",
            unit: "KG",
            product_id: "pasta",
            product_name: "Spaghetti 5 kg",
            matched: true,
            price: {
              gross: "28.50",
              currency: "EUR",
              sales_unit: "BAG",
              mode: "fixture",
              delivery_date: "2026-11-16",
              observed_at: timestamp,
              expires_at: "2099-11-15T12:00:00Z",
            },
          },
          snapshot.draft_cart!.items[1],
        ],
      },
    };
    await expect(draft.getByRole("status")).toHaveText("Preparing your order…");
    await expect(draft.getByText(/28\.50.*BAG incl. VAT/)).toBeVisible();
    await expect(
      draft.getByText(/Fixture price · invented demo data/),
    ).toBeVisible();
    await expect(
      draft.getByText("Price not checked", { exact: true }),
    ).toHaveCount(1);
    await expect(
      draft.getByText("Quantity needed", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`draft-cart-${width}.png`),
    });
    await page.reload();
    await expect(draft.getByText(/28\.50.*BAG incl. VAT/)).toBeVisible();
    snapshot = {
      ...snapshot,
      busy: false,
      purchases: [proposal],
      messages: [
        ...snapshot.messages,
        {
          id: 2,
          role: "assistant",
          text: "Review the prepared basket.",
          created_at: timestamp,
          proposal_id: proposalId,
        },
      ],
      draft_cart: { ...snapshot.draft_cart!, proposal_id: proposalId },
      activity: { turn_id: turnId, state: "complete", events: [] },
    };
    const overview = page.getByRole("complementary", { name: "Overview" });
    await expect(overview).toBeVisible({ timeout: 10_000 });
    await expect(draft).toHaveCount(0);
    await expect(
      overview.getByRole("button", { name: "Confirm purchase" }),
    ).toBeEnabled();
    await expect(overview.getByText("Total estimated")).toBeVisible();
  });
}

type DroppedFile = { name: string; mimeType: string; buffer: Buffer };
async function dropFiles(page: Page, files: DroppedFile | DroppedFile[]) {
  const payload = (Array.isArray(files) ? files : [files]).map((file) => ({
    name: file.name,
    mimeType: file.mimeType,
    base64: file.buffer.toString("base64"),
  }));
  await page
    .getByRole("form", { name: "Chat message" })
    .evaluate((form, files) => {
      const data = new DataTransfer();
      for (const file of files) {
        data.items.add(
          new File(
            [
              Uint8Array.from(atob(file.base64), (character) =>
                character.charCodeAt(0),
              ),
            ],
            file.name,
            { type: file.mimeType },
          ),
        );
      }
      form.dispatchEvent(
        new DragEvent("drop", {
          bubbles: true,
          cancelable: true,
          dataTransfer: data,
        }),
      );
    }, payload);
}

const attachmentPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7VYAAAAASUVORK5CYII=",
  "base64",
);
for (const width of [1440, 320]) {
  test(`attachments preview, remove and send a file-only request at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockSession(page);
    let current = { ...blankConversation };
    let posted: components["schemas"]["MessageRequest"] | undefined;
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({ json: current }),
    );
    await page.route(
      `**/api/conversations/${conversationId}/messages`,
      async (route) => {
        posted = route.request().postDataJSON();
        current = {
          ...blankConversation,
          messages: [
            {
              id: 1,
              role: "user",
              text: posted?.text ?? "",
              created_at: timestamp,
              attachments: [
                {
                  name: "menu.csv",
                  media_type: "text/csv",
                  size: 20,
                  url: `/api/conversations/${conversationId}/attachments/1/0`,
                },
              ],
            },
          ],
        };
        await route.fulfill({ json: current });
      },
    );
    await page.goto(`/conversations/${conversationId}`);
    await dropFiles(page, [
      { name: "photo.png", mimeType: "image/png", buffer: attachmentPng },
      {
        name: "menu.csv",
        mimeType: "text/csv",
        buffer: Buffer.from("Ingredient,KG\nTomato,5"),
      },
    ]);
    const files = page.getByRole("list", {
      name: "Attached files",
      exact: true,
    });
    await expect(files.getByText("photo.png")).toBeVisible();
    await expect(
      files.getByRole("img", { name: "Preview of photo.png" }),
    ).toBeVisible();
    // An attachment counts as a draft: the send arrow replaces voice mode.
    await expect(
      page.getByRole("button", { name: "Start voice mode" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Send Order Request" }),
    ).toBeEnabled();
    await page.screenshot({
      path: testInfo.outputPath(`attachment-preview-${width}.png`),
    });
    await page.getByRole("button", { name: "Remove photo.png" }).click();
    await expect(files.getByText("photo.png")).toHaveCount(0);
    await page.getByRole("button", { name: "Send Order Request" }).click();
    await expect.poll(() => posted?.attachments?.length).toBe(1);
    expect(posted?.text).toBe("");
    expect(posted?.attachments?.[0].data).toBe(
      Buffer.from("Ingredient,KG\nTomato,5").toString("base64"),
    );
    await expect(
      page
        .getByRole("list", { name: "Message attachments", exact: true })
        .getByRole("link", { name: "menu.csv" }),
    ).toBeVisible();
    await expect(files).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.reload();
    await expect(
      page.getByRole("link", { name: "menu.csv", exact: true }),
    ).toBeVisible();
  });
}

test("drop and clipboard files produce removable composer previews", async ({
  page,
}) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  await page.goto(`/conversations/${conversationId}`);
  await page.getByRole("form", { name: "Chat message" }).evaluate((form) => {
    const data = new DataTransfer();
    data.items.add(
      new File(["Tomato soup"], "dropped.txt", { type: "text/plain" }),
    );
    form.dispatchEvent(
      new DragEvent("drop", {
        bubbles: true,
        cancelable: true,
        dataTransfer: data,
      }),
    );
  });
  await expect(page.getByText("dropped.txt", { exact: true })).toBeVisible();
  await page.getByLabel("Continue the conversation").evaluate((input) => {
    const data = new DataTransfer();
    data.items.add(
      new File(["Ingredient,KG\nTomato,5"], "pasted.csv", { type: "text/csv" }),
    );
    input.dispatchEvent(
      new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: data,
      }),
    );
  });
  await expect(page.getByText("pasted.csv", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Remove dropped.txt" }).click();
  await expect(page.getByText("dropped.txt", { exact: true })).toHaveCount(0);
  await expect(page.getByText("pasted.csv", { exact: true })).toBeVisible();
});

test("unsupported, empty, oversized and excessive files are rejected without losing the draft", async ({
  page,
}) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  await page.goto(`/conversations/${conversationId}`);
  await page.getByLabel("Continue the conversation").fill("Soup menu");
  await dropFiles(page, {
    name: "script.exe",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("abc"),
  });
  await expect(page.getByRole("alert")).toContainText("Use PDF");
  await dropFiles(page, {
    name: "large.txt",
    mimeType: "text/plain",
    buffer: Buffer.alloc(2 * 1024 * 1024 + 1),
  });
  await expect(page.getByRole("alert")).toContainText("at most 2 MB");
  await dropFiles(page, {
    name: "empty.txt",
    mimeType: "text/plain",
    buffer: Buffer.alloc(0),
  });
  await expect(page.getByRole("alert")).toContainText("nonempty");
  await dropFiles(
    page,
    ["a", "b", "c", "d"].map((name) => ({
      name: `${name}.txt`,
      mimeType: "text/plain",
      buffer: Buffer.from(name),
    })),
  );
  await expect(page.getByRole("alert")).toContainText("up to 3 files");
  await dropFiles(
    page,
    ["a", "b", "c"].map((name) => ({
      name: `${name}.txt`,
      mimeType: "text/plain",
      buffer: Buffer.alloc(1500000, "x"),
    })),
  );
  await expect(page.getByRole("alert")).toContainText("at most 4 MB");
  await expect(page.getByLabel("Continue the conversation")).toHaveValue(
    "Soup menu",
  );
  await expect(
    page.getByRole("list", { name: "Attached files", exact: true }),
  ).toHaveCount(0);
});

test("failed worker retry restores attachments after refresh and retains the exact key", async ({
  page,
}) => {
  await mockSession(page);
  const retry = {
    text: "Read this menu",
    idempotency_key: "saved-file-turn-key",
    constraints: { budget_gross: "150", lactose_free: true, milk_free: null },
    attachments: [
      {
        name: "menu.txt",
        media_type: "text/plain",
        data: Buffer.from("Tomato soup").toString("base64"),
      },
    ],
  };
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: { ...blankConversation, retry_message: retry } }),
  );
  let posted: unknown;
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      posted = route.request().postDataJSON();
      await route.fulfill({ json: { ...blankConversation, busy: true } });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  await expect(page.getByText("menu.txt", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("menu.txt", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).click();
  await expect.poll(() => posted).toEqual(retry);
});

for (const width of [1440, 320]) {
  test(`home submits a multiline request and attachment into saved chat at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 1000 });
    await mockSession(page);
    let saved = structuredClone(blankConversation);
    const messages: string[] = [];
    const requestText = "Milk and eggs for Monday.\nFor 40 guests.";
    await page.route("**/api/conversations", async (route) => {
      expect(route.request().headers()["x-csrf-token"]).toBe(
        session.csrf_token,
      );
      expect(route.request().postDataJSON().idempotency_key).toBeTruthy();
      await route.fulfill({ json: saved });
    });
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      route.fulfill({ json: saved }),
    );
    await page.route(
      `**/api/conversations/${conversationId}/messages`,
      async (route) => {
        const body = route.request().postDataJSON();
        messages.push(body.text);
        expect(body.attachments).toEqual([
          {
            name: "restock.txt",
            media_type: "text/plain",
            data: Buffer.from("Milk and eggs").toString("base64"),
          },
        ]);
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
              text: "What quantities do you need?",
              created_at: timestamp,
            },
          ],
        };
        await route.fulfill({ json: saved });
      },
    );
    await page.goto("/");
    const input = page.getByLabel("Your meal or purchasing request");
    await expect(page.getByRole("button", { name: "Attach file" })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", { name: "Send Order Request" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Start voice mode" }),
    ).toBeEnabled();
    await input.fill("Milk");
    await expect(
      page.getByRole("button", { name: "Send Order Request" }),
    ).toBeEnabled();
    await expect(
      page.getByRole("button", { name: "Start voice mode" }),
    ).toHaveCount(0);
    await input.fill(" ");
    await expect(
      page.getByRole("button", { name: "Start voice mode" }),
    ).toBeEnabled();
    await input.fill("");
    const schedule = page.getByRole("region", { name: "Scheduled deliveries" });
    // This test mocks no standing orders, so the strip shows its empty state.
    await expect(schedule).toContainText("No standing orders yet.");
    await expect(
      page.getByText("Demo schedule · No supplier orders are placed."),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({
      path: testInfo.outputPath(`home-${width}.png`),
      fullPage: true,
    });
    await input.evaluate((field) => {
      const data = new DataTransfer();
      data.items.add(
        new File(["Milk and eggs"], "restock.txt", { type: "text/plain" }),
      );
      field.dispatchEvent(
        new ClipboardEvent("paste", {
          bubbles: true,
          cancelable: true,
          clipboardData: data,
        }),
      );
    });
    await expect(page.getByText("restock.txt", { exact: true })).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath(`home-attachment-${width}.png`),
      fullPage: true,
    });
    await expect(
      page.getByRole("button", { name: "Send Order Request" }),
    ).toBeEnabled();
    await expect(
      page.getByRole("button", { name: "Start voice mode" }),
    ).toHaveCount(0);
    await input.fill("Milk and eggs for Monday.");
    await input.press("Shift+Enter");
    await expect(input).toHaveValue("Milk and eggs for Monday.\n");
    await input.fill(requestText);
    await expect(page).toHaveURL(/\/$/);
    await page.getByRole("button", { name: "Send Order Request" }).click();
    await expect(page).toHaveURL(
      new RegExp(`/conversations/${conversationId}$`),
    );
    await expect(page.getByText("What quantities do you need?")).toBeVisible();
    // The sent request must not linger as a draft in the chat composer.
    await expect(page.getByLabel("Continue the conversation")).toHaveValue("");
    await expect(page.getByText("restock.txt", { exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.getByText("What quantities do you need?")).toBeVisible();
    await expect(page.getByLabel("Continue the conversation")).toHaveValue("");
    expect(messages).toEqual([requestText]);
  });
}

test("home hands a failed first message back to the chat composer", async ({
  page,
}) => {
  await mockSession(page);
  await page.route("**/api/conversations", (route) =>
    route.fulfill({ json: blankConversation }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  // A real network takes a moment to fail. The chat page's mount effect runs twice in development
  // (StrictMode) and the second run clears the error, so an instant failure that lands before the
  // chat page has mounted would be lost; this keeps the test about the hand-over, not about that race.
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 400));
      await route.fulfill({
        status: 503,
        json: {
          error: { code: "UNAVAILABLE", message: "Try again shortly." },
        },
      });
    },
  );
  await page.goto("/");
  await page
    .getByLabel("Your meal or purchasing request")
    .fill("Restock milk for Monday");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(page).toHaveURL(new RegExp(`/conversations/${conversationId}$`));
  await expect(page.getByRole("alert").first()).toContainText(
    "Try again shortly.",
  );
  await expect(page.getByLabel("Continue the conversation")).toHaveValue(
    "Restock milk for Monday",
  );
});

test("home composer sends on Enter and keeps Shift+Enter as a new line", async ({
  page,
}) => {
  await mockSession(page);
  const posted: string[] = [];
  await page.route("**/api/conversations", async (route) => {
    posted.push(route.request().method());
    await route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "Try again shortly." } },
    });
  });
  await page.goto("/");
  const input = page.getByLabel("Your meal or purchasing request");
  await input.fill("Restock milk");
  await input.press("Shift+Enter");
  await input.pressSequentially("for Monday");
  await expect(input).toHaveValue("Restock milk\nfor Monday");
  expect(posted).toHaveLength(0);
  await input.press("Enter");
  await expect(page.getByRole("alert")).toContainText("Try again shortly.");
  await expect(input).toHaveValue("Restock milk\nfor Monday");
  expect(posted).toHaveLength(1);
});

test("open conversation composer sends on Enter and keeps Shift+Enter as a new line", async ({
  page,
}) => {
  await mockSession(page);
  const posted: string[] = [];
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      posted.push(route.request().postDataJSON().text);
      await route.fulfill({
        status: 503,
        json: { error: { code: "UNAVAILABLE", message: "Try again shortly." } },
      });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  const input = page.getByLabel("Continue the conversation");
  await expect(input).toHaveJSProperty("tagName", "TEXTAREA");
  await input.fill("Restock milk");
  await input.press("Shift+Enter");
  await input.pressSequentially("for Monday");
  await expect(input).toHaveValue("Restock milk\nfor Monday");
  expect(posted).toHaveLength(0);
  await input.press("Enter");
  await expect(page.getByRole("alert")).toContainText("Try again shortly.");
  await expect(input).toHaveValue("Restock milk\nfor Monday");
  expect(posted).toEqual(["Restock milk\nfor Monday"]);
});

test("proposal message offers Review basket handoff into Overview", async ({
  page,
}) => {
  await mockSession(page);
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
  await page.goto(`/conversations/${conversationId}`);
  const handoff = page.getByRole("button", {
    name: "Review basket to confirm",
  });
  await expect(handoff).toBeVisible();
  await expect(
    page.getByText("Sending chat never places an order."),
  ).toBeVisible();
  await handoff.click();
  const overview = page.getByRole("complementary", { name: "Overview" });
  await expect(overview).toContainText("1 items staged");
  await expect(
    overview.getByRole("button", { name: "Confirm purchase" }),
  ).toBeVisible();
});

test("home retains the draft and creation key after a failed start", async ({
  page,
}) => {
  await mockSession(page);
  const keys: string[] = [];
  await page.route("**/api/conversations", async (route) => {
    keys.push(route.request().postDataJSON().idempotency_key);
    await route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "Try again shortly." } },
    });
  });
  await page.goto("/");
  const input = page.getByLabel("Your meal or purchasing request");
  await input.fill("Restock milk for Monday");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(page.getByRole("alert")).toContainText("Try again shortly.");
  await expect(input).toHaveValue("Restock milk for Monday");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("alert")).toContainText("Try again shortly.");
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});
