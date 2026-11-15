import { expect, test, type Page } from "@playwright/test";
import type { Conversation } from "../src/shared/api/types";
import { proposal } from "./support/proposalFixture";
import { ids, json, mockSignedIn, problem } from "./support/schedulerFixtures";

// SPEC (written before the UI; fails until built). The right-hand card is ALWAYS in a chat and has a
// "Confirm purchase" button: greyed with a reason while nothing can be ordered, green and enabled as
// soon as one item has a product and a quantity. It asks for a delivery date and shows the
// destination, lists the items it leaves out, and prepares the purchase from the cart.
// MOCK API: the prepare-from-cart route is a typed mock of the backend owner's PROPOSED contract until
// it is generated (route and body are in src/features/purchases/api/cartApi.ts). Browser time is pinned
// to 14 Nov 2026 10:00 Helsinki, so "tomorrow" is 2026-11-15.

const conversationId = ids.conversation;
const turnId = "turn-1";
const timestamp = "2026-11-14T10:00:00+02:00";
const PREPARE = `**/api/conversations/${conversationId}/prepare-from-cart`;

const pasta = {
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
};
const salt = { name: "Salt", amount: null, unit: "g", matched: false };
const needsQuantity = {
  name: "Basil",
  amount: null,
  unit: "bunch",
  product_id: "basil",
  product_name: "Basil bunch",
  matched: true,
};
const tomato = {
  name: "Tomato",
  amount: "5",
  unit: "KG",
  matched: false,
};

const withCart = (items: unknown[]): Conversation =>
  ({
    id: conversationId,
    title: "Pasta lunch",
    created_at: timestamp,
    updated_at: timestamp,
    cart_editable: false,
    busy: false,
    purchases: [],
    messages: [
      {
        id: 1,
        role: "assistant",
        text: "Here is a draft.",
        created_at: timestamp,
      },
    ],
    draft_cart: { turn_id: turnId, title: "Pasta lunch", items },
  }) as Conversation;

async function open(
  page: Page,
  conversation: Conversation | null,
  destinations = ["hotel-helsinki"],
) {
  await page.clock.setFixedTime(new Date("2026-11-14T08:00:00Z"));
  await mockSignedIn(page);
  await page.route("**/api/settings/policy", (route) =>
    json(route, {
      buyer_id: "demo-hotel",
      policy_version: 1,
      rules: { currency: "EUR", destinations },
      can_edit: true,
      approval_authority: { can_approve: true },
      history: [],
    }),
  );
  if (conversation) {
    await page.route(`**/api/conversations/${conversationId}`, (route) =>
      json(route, conversation),
    );
    await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: ": heartbeat\n\n",
      }),
    );
  }
  await page.goto(
    conversation ? `/conversations/${conversationId}` : "/request",
  );
}
const card = (page: Page) =>
  page.getByRole("complementary", { name: "Your order" });
const confirm = (page: Page) =>
  card(page).getByRole("button", { name: "Confirm purchase" });

test("a new chat already has the card: empty, with a greyed Confirm purchase and a reason", async ({
  page,
}) => {
  await open(page, null);
  await expect(card(page)).toBeVisible();
  await expect(card(page)).toContainText("Empty");
  await expect(confirm(page)).toBeDisabled();
  await expect(confirm(page)).toHaveAccessibleDescription("Add items first");
  await expect(card(page).getByLabel("Delivery date")).toHaveCount(0);
});

test("items that have no product or quantity yet leave the button greyed and are listed as not included", async ({
  page,
}) => {
  await open(page, withCart([tomato, salt]));
  await expect(confirm(page)).toBeDisabled();
  await expect(confirm(page)).toHaveAccessibleDescription(
    "None of the items has a product and a quantity yet.",
  );
  const left = card(page).getByRole("region", { name: "Not included" });
  await expect(left).toContainText("Tomato · no product yet");
  await expect(left).toContainText("Salt · no product or quantity yet");
  await expect(left).toContainText("These items will not be ordered.");
});

test("an item with a product but no quantity says only the quantity is missing", async ({
  page,
}) => {
  await open(page, withCart([needsQuantity]));
  await expect(
    card(page).getByRole("region", { name: "Not included" }),
  ).toContainText("Basil · quantity needed");
  await expect(confirm(page)).toBeDisabled();
});

test("one item with a product and a quantity makes the button enabled; the others are warned about", async ({
  page,
}) => {
  await open(page, withCart([pasta, salt]));
  await expect(confirm(page)).toBeEnabled();
  await expect(confirm(page)).toHaveAccessibleDescription("");
  const left = card(page).getByRole("region", { name: "Not included" });
  await expect(left).toContainText("Salt · no product or quantity yet");
  await expect(left).not.toContainText("Pasta");
  const date = card(page).getByLabel("Delivery date");
  await expect(date).toHaveValue("2026-11-15"); // tomorrow in Helsinki
  await expect(date).toHaveAttribute("min", "2026-11-15");
  await expect(card(page).getByText("hotel-helsinki")).toBeVisible();
});

test("a date before tomorrow greys the button with its reason; a later one is fine", async ({
  page,
}) => {
  await open(page, withCart([pasta]));
  const date = card(page).getByLabel("Delivery date");
  await date.fill("2026-11-14");
  await expect(confirm(page)).toBeDisabled();
  await expect(confirm(page)).toHaveAccessibleDescription(
    "Choose a delivery date on or after 15 Nov 2026.",
  );
  await date.fill("2026-11-18");
  await expect(confirm(page)).toBeEnabled();
  await date.fill("");
  await expect(confirm(page)).toBeDisabled();
});

test("Confirm purchase prepares the purchase from the cart and then shows the exact basket to commit", async ({
  page,
}) => {
  const requests: { body: Record<string, unknown>; csrf?: string }[] = [];
  let prepared = false;
  const conversation = withCart([pasta, salt]);
  await open(page, conversation);
  await page.unroute(`**/api/conversations/${conversationId}`);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    json(
      route,
      prepared
        ? {
            ...conversation,
            purchases: [{ ...proposal, can_decide: true }],
            draft_cart: {
              ...conversation.draft_cart!,
              proposal_id: proposal.proposal_id,
            },
          }
        : conversation,
    ),
  );
  await page.route(`**/api/purchases/${proposal.proposal_id}`, (route) =>
    json(route, { ...proposal, can_decide: true }),
  );
  await page.route(PREPARE, (route) => {
    requests.push({
      body: route.request().postDataJSON(),
      csrf: route.request().headers()["x-csrf-token"],
    });
    prepared = true;
    return json(route, {
      proposal: { ...proposal, can_decide: true },
      not_included: [
        { name: "Salt", amount: null, unit: "g", reason: "no_product" },
      ],
    });
  });
  await card(page).getByLabel("Delivery date").fill("2026-11-17");
  await confirm(page).click();
  const overview = page.getByRole("complementary", { name: "Overview" });
  await expect(overview).toBeVisible();
  await expect(overview.getByTestId("card-total-row")).toBeVisible();
  await expect(
    overview.getByRole("button", {
      name: /Confirm purchase/,
    }),
  ).toBeEnabled();
  await expect(card(page)).toHaveCount(0);
  expect(requests).toHaveLength(1);
  expect(requests[0].csrf).toBe("test-csrf");
  expect(requests[0].body).toEqual({
    delivery_date: "2026-11-17",
    destination: "hotel-helsinki",
    request_id: expect.stringMatching(/^.{8,120}$/),
  });
});

test("a refused preparation shows the server's message in the card and the button works again", async ({
  page,
}) => {
  await open(page, withCart([pasta]));
  await page.route(PREPARE, (route) =>
    problem(
      route,
      409,
      "CART_NOT_VERIFIED",
      "The cart changed. Review it and try again.",
    ),
  );
  await confirm(page).click();
  await expect(card(page).getByRole("alert")).toHaveText(
    "The cart changed. Review it and try again.",
  );
  await expect(card(page)).toBeVisible();
  await expect(confirm(page)).toBeEnabled();
});

test("while the assistant is working the button is greyed with that reason", async ({
  page,
}) => {
  await open(page, { ...withCart([pasta]), busy: true });
  await expect(confirm(page)).toBeDisabled();
  await expect(confirm(page)).toHaveAccessibleDescription(
    "The assistant is still working on your request.",
  );
});

test("without a readable policy the destination defaults to hotel-helsinki; several destinations are a choice", async ({
  page,
}) => {
  await open(page, withCart([pasta]), ["hotel-helsinki", "hotel-espoo"]);
  const choice = card(page).getByLabel("Destination");
  await expect(choice).toHaveValue("hotel-helsinki");
  await choice.selectOption("hotel-espoo");
  let body: Record<string, unknown> = {};
  await page.route(PREPARE, (route) => {
    body = route.request().postDataJSON();
    return problem(route, 422, "EMPTY_CART", "The cart is empty.");
  });
  await confirm(page).click();
  await expect(card(page).getByRole("alert")).toHaveText("The cart is empty.");
  expect(body.destination).toBe("hotel-espoo");
});

test("a retry of the same press reuses the request id; a changed date gets a new one", async ({
  page,
}) => {
  await open(page, withCart([pasta]));
  const ids: string[] = [];
  await page.route(PREPARE, (route) => {
    ids.push(route.request().postDataJSON().request_id);
    return problem(route, 409, "CONVERSATION_BUSY", "Try again in a moment.");
  });
  await confirm(page).click();
  await expect(card(page).getByRole("alert")).toBeVisible();
  await confirm(page).click();
  await expect.poll(() => ids.length).toBe(2);
  expect(ids[1]).toBe(ids[0]);
  await card(page).getByLabel("Delivery date").fill("2026-11-20");
  await confirm(page).click();
  await expect.poll(() => ids.length).toBe(3);
  expect(ids[2]).not.toBe(ids[0]);
});

test("on a phone the button is reachable without opening the card, and nothing scrolls sideways", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page, withCart([pasta, salt]));
  await expect(confirm(page)).toBeVisible();
  await expect(confirm(page)).toBeEnabled();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

// --- the card shows the exact proposal as soon as there is one (owner's "always finalised" design) --

const decidable = { ...proposal, can_decide: true };
const withProposal = (
  items: unknown[],
  over: Partial<Conversation> = {},
  p = decidable,
): Conversation => ({
  ...withCart(items),
  purchases: [p],
  draft_cart: {
    turn_id: turnId,
    title: "Pasta lunch",
    items: items as NonNullable<Conversation["draft_cart"]>["items"],
    proposal_id: p.proposal_id,
  },
  ...over,
});
const overview = (page: Page) =>
  page.getByRole("complementary", { name: "Overview" });
const finalButton = (page: Page) =>
  overview(page).getByRole("button", { name: "Confirm purchase" });

async function openProposal(
  page: Page,
  conversation: Conversation,
  p = decidable,
) {
  await page.route(`**/api/purchases/${p.proposal_id}`, (route) =>
    json(route, p),
  );
  await open(page, conversation);
}

test("with a prepared purchase the card shows its exact lines and total and one green Confirm purchase", async ({
  page,
}) => {
  await openProposal(page, withProposal([pasta, salt]));
  await expect(overview(page).getByText("Spaghetti").first()).toBeVisible();
  await expect(overview(page).getByTestId("card-total-row")).toBeVisible();
  await expect(finalButton(page)).toBeEnabled();
  await expect(card(page)).toHaveCount(0);
});

test("one press of Confirm purchase commits that exact revision", async ({
  page,
}) => {
  const confirmations: Record<string, unknown>[] = [];
  await openProposal(page, withProposal([pasta]));
  await page.route(
    `**/api/purchases/${decidable.proposal_id}/confirm`,
    (route) => {
      confirmations.push(route.request().postDataJSON());
      return json(route, { ...decidable, status: "revised" });
    },
  );
  await finalButton(page).click();
  expect(confirmations).toHaveLength(1);
  expect(confirmations[0].revision).toBe(1);
  expect(confirmations[0].proposal_id).toBe(decidable.proposal_id);
});

test("the card keeps the delivery date and destination and lists what is not included", async ({
  page,
}) => {
  await openProposal(page, withProposal([pasta, salt]));
  const left = overview(page).getByRole("region", { name: "Not included" });
  await expect(left).toContainText("Salt · no product or quantity yet");
  await expect(left).not.toContainText("Pasta");
  await overview(page).getByRole("tab", { name: "Delivery" }).click();
  await expect(overview(page).getByLabel("Delivery date")).toHaveValue(
    "2026-11-16", // this purchase's delivery date
  );
  await expect(overview(page).getByTestId("card-panel-delivery")).toContainText(
    "hotel-helsinki",
  );
  const date = overview(page).getByLabel("Delivery date");
  await expect(date).toHaveValue("2026-11-16");
  await expect(date).toHaveAttribute("min", "2026-11-15");
  // Nothing changed yet, so there is nothing to save and nothing to warn about.
  await expect(overview(page).getByTestId("delivery-hint")).toHaveCount(0);
});

test("changing the delivery date prepares the purchase again and the card shows the new revision", async ({
  page,
}) => {
  const bodies: Record<string, unknown>[] = [];
  const next = {
    ...decidable,
    revision: 2,
    current_revision: 2,
    request: { ...decidable.request, delivery_date: "2026-11-18" },
  };
  let prepared = false;
  const conversation = withProposal([pasta]);
  await page.route(`**/api/purchases/${decidable.proposal_id}`, (route) =>
    json(route, prepared ? next : decidable),
  );
  await open(page, conversation);
  await page.unroute(`**/api/conversations/${conversationId}`);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    json(route, prepared ? withProposal([pasta], {}, next) : conversation),
  );
  await page.route(PREPARE, (route) => {
    bodies.push(route.request().postDataJSON());
    prepared = true;
    return json(route, { proposal: next, not_included: [] });
  });
  await overview(page).getByRole("button", { name: "Edit delivery" }).click();
  await overview(page).getByLabel("Delivery date").fill("2026-11-18");
  await overview(page).getByLabel("Delivery date").press("Enter");
  // Saved: back to the list, which shows the new date, and the card shows the new revision.
  await expect(overview(page).getByLabel("Delivery date")).toHaveValue(
    "2026-11-18",
  );
  await overview(page).getByRole("tab", { name: "Details" }).click();
  await expect(overview(page)).toContainText("2 · created");
  expect(bodies).toEqual([
    {
      delivery_date: "2026-11-18",
      destination: "hotel-helsinki",
      request_id: expect.stringMatching(/^.{8,120}$/),
    },
  ]);
});

test("a date before tomorrow cannot be applied", async ({ page }) => {
  await openProposal(page, withProposal([pasta]));
  await overview(page).getByRole("button", { name: "Edit delivery" }).click();
  await overview(page).getByLabel("Delivery date").fill("2026-11-14");
  await expect(overview(page).getByTestId("delivery-hint")).toBeVisible();
});

test("while the assistant works the card is dimmed and Confirm purchase is greyed out", async ({
  page,
}) => {
  await openProposal(page, withProposal([pasta], { busy: true }));
  await expect(overview(page)).toHaveAttribute("aria-busy", "true");
  await expect(finalButton(page)).toBeDisabled();
});

test("a stale press is answered in plain words and the card shows the new revision", async ({
  page,
}) => {
  const next = { ...decidable, revision: 2, current_revision: 2 };
  let revised = false;
  await page.route(`**/api/purchases/${decidable.proposal_id}`, (route) =>
    json(route, revised ? next : decidable),
  );
  await open(page, withProposal([pasta]));
  await page.route(
    `**/api/purchases/${decidable.proposal_id}/confirm`,
    (route) => {
      revised = true;
      return json(route, { ...next, status: "revised" });
    },
  );
  await finalButton(page).click();
  await expect(
    overview(page).getByText(
      "Terms changed during verification. Review the new revision and confirm again.",
    ),
  ).toBeVisible();
  await overview(page).getByRole("tab", { name: "Details" }).click();
  await expect(overview(page)).toContainText("2 · created");
  await expect(finalButton(page)).toBeEnabled();
});

// --- default open, collapsible, remembered, never moved by updates -------------------------------

const toggle = (page: Page, name: "Collapse cart" | "Expand cart") =>
  page.getByRole("complementary").getByRole("button", { name });

for (const [label, width] of [
  ["desktop", 1440],
  ["phone", 390],
] as const) {
  test(`the card is open by default on a ${label} and its toggle says so`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, withCart([pasta, salt]));
    await expect(toggle(page, "Collapse cart")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await expect(card(page).getByText("Spaghetti 5 kg")).toBeVisible();
    await expect(card(page).getByLabel("Delivery date")).toBeVisible();
  });
}

test("collapsing hides the lines, the choice is remembered after a reload, and expanding brings them back", async ({
  page,
}) => {
  await open(page, withCart([pasta, salt]));
  await toggle(page, "Collapse cart").click();
  await expect(toggle(page, "Expand cart")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await expect(card(page).getByText("Spaghetti 5 kg")).toBeHidden();
  await expect(confirm(page)).toBeVisible(); // the button stays reachable
  await page.reload();
  await expect(toggle(page, "Expand cart")).toBeVisible();
  await expect(card(page).getByText("Spaghetti 5 kg")).toBeHidden();
  await toggle(page, "Expand cart").click();
  await expect(card(page).getByText("Spaghetti 5 kg")).toBeVisible();
  await page.reload();
  await expect(toggle(page, "Collapse cart")).toBeVisible();
});

test("an update never opens or closes the card: the choice survives the draft becoming a purchase", async ({
  page,
}) => {
  let prepared = false;
  const conversation = withCart([pasta]);
  await page.route(`**/api/purchases/${decidable.proposal_id}`, (route) =>
    json(route, decidable),
  );
  await open(page, conversation);
  await page.unroute(`**/api/conversations/${conversationId}`);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    json(route, prepared ? withProposal([pasta]) : conversation),
  );
  await page.route(PREPARE, (route) => {
    prepared = true;
    return json(route, { proposal: decidable, not_included: [] });
  });
  await toggle(page, "Collapse cart").click();
  await confirm(page).click();
  await expect(overview(page)).toBeVisible();
  await expect(toggle(page, "Expand cart")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await expect(overview(page).getByTestId("card-total-row")).toBeVisible();
  await expect(overview(page).getByText("Spaghetti 5 kg").first()).toBeHidden();
});

test("a new chat remembers the choice too, and an unreadable store means open", async ({
  page,
}) => {
  await open(page, null);
  await toggle(page, "Collapse cart").click();
  await page.reload();
  await expect(toggle(page, "Expand cart")).toBeVisible();
  // Storage that throws (private window, blocked site data) must not break the card.
  await page.addInitScript(() => {
    const { getItem, setItem } = Storage.prototype;
    Storage.prototype.getItem = function (key: string) {
      if (key === "aimo.cart.open") throw new Error("blocked");
      return getItem.call(this, key);
    };
    Storage.prototype.setItem = function (key: string, value: string) {
      if (key === "aimo.cart.open") throw new Error("blocked");
      return setItem.call(this, key, value);
    };
  });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.reload();
  await expect(toggle(page, "Collapse cart")).toBeVisible();
  await toggle(page, "Collapse cart").click();
  await expect(toggle(page, "Expand cart")).toBeVisible();
  expect(errors).toEqual([]);
});

// --- several baskets in one chat: the card is the current one; an order closes the card ------------

test("the card shows the newest basket that is not cancelled", async ({
  page,
}) => {
  const old = {
    ...decidable,
    proposal_id: "11111111-1111-4111-8111-111111111111",
    approval_status: "cancelled",
  } as typeof decidable;
  const current = { ...decidable, revision: 2, current_revision: 2 };
  await page.route(`**/api/purchases/${current.proposal_id}`, (route) =>
    json(route, current),
  );
  await page.route(`**/api/purchases/${old.proposal_id}`, (route) =>
    json(route, old),
  );
  await open(page, { ...withProposal([pasta]), purchases: [current, old] });
  await overview(page).getByRole("tab", { name: "Details" }).click();
  await expect(overview(page)).toContainText("2 · created");
  await expect(finalButton(page)).toBeEnabled();
});

test("after an order is placed the card offers no second purchase and no edits", async ({
  page,
}) => {
  const placed = {
    ...decidable,
    approval_status: "approved",
    order_status: "accepted_mock",
    order_id: "c1a2b3c4-d5e6-4f70-8a9b-0c1d2e3f4a5b",
  } as typeof decidable;
  await openProposal(page, withProposal([pasta], {}, placed), placed);
  await expect(overview(page)).toContainText("Accepted by demo order service");
  await expect(finalButton(page)).toBeDisabled();
  await expect(overview(page).getByLabel("Delivery date")).toHaveCount(0);
  await expect(
    overview(page).getByRole("button", { name: "Save" }),
  ).toHaveCount(0);
});
