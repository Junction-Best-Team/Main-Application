import { expect, test, type Page } from "@playwright/test";
import { newCart, openCart, type CartWorld } from "./support/cartFixtures";

// SPEC (written before the fix; fails until built). Three owner findings on the cart card:
// (1) the customer never sees "Draft cart" or "Quantities are for review. ..."; a basket is "Your
// order", the moment before it exists says "Preparing your order…", and only a true note is kept
// (items that are not matched); (2) the card is open by default, stays open when items are added or
// the basket changes, and closes only when the customer closes it (remembered in this browser);
// (3) the purchase button is always on the card: green with items, grey with a reason otherwise.
// Mocked API with typed fixtures; the conversation changes through the SSE stream like a real turn.

const card = (page: Page) =>
  page.locator("aside#overview, aside[aria-label='Your order']").first();
const confirmButton = (page: Page) =>
  card(page).getByRole("button", { name: "Confirm purchase" });
const toggle = (page: Page) =>
  card(page).getByRole("button", { name: /^(Collapse|Expand) cart$/ });

async function open(page: Page, over: Partial<CartWorld> = {}) {
  const world = newCart({ stream: true, ...over });
  await openCart(page, world);
  await expect(card(page)).toBeVisible();
  return world;
}
const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "phone", width: 390, height: 800 },
];

// --- (1) what the customer reads ------------------------------------------------------------

const STATES: { name: string; over: Partial<CartWorld> }[] = [
  { name: "an empty cart", over: { view: "empty" } },
  { name: "a draft cart", over: { view: "draft" } },
  { name: "a draft with an unmatched item", over: { view: "unmatched" } },
  { name: "the assistant still working", over: { view: "draft", busy: true } },
  { name: "a prepared basket", over: { view: "prepared" } },
];
for (const state of STATES) {
  test(`${state.name}: the card says "Your order", never "Draft cart" and never the review disclaimer`, async ({
    page,
  }) => {
    await open(page, state.over);
    await expect(
      card(page).getByRole("heading", { name: "Your order" }),
    ).toBeVisible();
    await expect(page.getByText("Draft cart")).toHaveCount(0);
    await expect(page.getByText(/Quantities are for review/)).toHaveCount(0);
    await expect(
      page.getByText(/verified when the basket is prepared/),
    ).toHaveCount(0);
    await expect(page.getByText(/items matched/)).toHaveCount(0);
  });
}

test("before the server has prepared the order the card says Preparing your order…", async ({
  page,
}) => {
  await open(page, { view: "draft", busy: true });
  await expect(card(page).getByText("Preparing your order…")).toBeVisible();
  await expect(confirmButton(page)).toBeDisabled();
  await expect(confirmButton(page)).toHaveAccessibleDescription(
    "The assistant is still working on your request.",
  );
});

test("a prepared basket is the finished order: no preparing text, the exact total", async ({
  page,
}) => {
  await open(page, { view: "prepared" });
  await expect(card(page).getByText("Preparing your order…")).toHaveCount(0);
  await expect(card(page)).toContainText("Total estimated");
  await expect(card(page)).toContainText(/136[.,]00/);
});

test("the only note on a draft is the true one: items that are not matched will not be ordered", async ({
  page,
}) => {
  await open(page, { view: "unmatched" });
  const note = card(page).getByRole("region", { name: "Not included" });
  await expect(note).toContainText("Unobtainium");
  await expect(note).toContainText("These items will not be ordered.");
});

test("a fully matched draft has no note at all", async ({ page }) => {
  await open(page, { view: "draft" });
  await expect(
    card(page).getByRole("region", { name: "Not included" }),
  ).toHaveCount(0);
  await expect(card(page).getByText(/will not be ordered/)).toHaveCount(0);
});

// --- (3) the purchase button is always there --------------------------------------------------

const BUTTONS: {
  name: string;
  over: Partial<CartWorld>;
  enabled: boolean;
  reason?: string;
}[] = [
  {
    name: "empty cart",
    over: { view: "empty" },
    enabled: false,
    reason: "Add items first",
  },
  { name: "draft cart", over: { view: "draft" }, enabled: true },
  {
    name: "assistant working",
    over: { view: "draft", busy: true },
    enabled: false,
    reason: "The assistant is still working on your request.",
  },
  { name: "prepared basket", over: { view: "prepared" }, enabled: true },
  {
    name: "order placed",
    over: { view: "prepared", orderPlaced: true, editable: false },
    enabled: false,
    reason: "This order was already placed.",
  },
  {
    name: "blocked by the purchasing checks",
    over: { view: "prepared", outcome: "denied" },
    enabled: false,
    reason:
      "This order cannot be confirmed yet. Resolve the purchasing checks.",
  },
  {
    name: "needs resolution",
    over: { view: "prepared", outcome: "needs_resolution" },
    enabled: false,
    reason:
      "This order cannot be confirmed yet. Resolve the purchasing checks.",
  },
  {
    name: "expired basket",
    over: { view: "prepared", expired: true },
    enabled: false,
    reason: "This order expired. Change it to prepare a new one.",
  },
];
for (const b of BUTTONS) {
  test(`the Confirm purchase button is on the card: ${b.name} (${b.enabled ? "green" : "grey with a reason"})`, async ({
    page,
  }) => {
    await open(page, b.over);
    await expect(confirmButton(page)).toHaveCount(1);
    await expect(confirmButton(page)).toBeVisible();
    if (b.enabled) await expect(confirmButton(page)).toBeEnabled();
    else {
      await expect(confirmButton(page)).toBeDisabled();
      await expect(confirmButton(page)).toHaveAccessibleDescription(b.reason!);
      await expect(card(page).getByText(b.reason!)).toBeVisible();
    }
  });
}

test("the button is reachable on a phone without opening anything", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page, { view: "draft" });
  await expect(confirmButton(page)).toBeVisible();
  await expect(confirmButton(page)).toBeEnabled();
});

// --- (2) open by default, closed only by the customer ------------------------------------------

const content = (page: Page, view: CartWorld["view"]) =>
  view === "prepared"
    ? card(page).getByText("Total estimated")
    : view === "empty"
      ? card(page).getByText(/Your cart is empty/)
      : card(page).getByRole("list").first();

for (const vp of VIEWPORTS) {
  for (const view of ["empty", "draft", "prepared"] as const) {
    test(`${vp.name}: the card is open by default (${view})`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await open(page, { view });
      await expect(toggle(page)).toHaveAccessibleName("Collapse cart");
      await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
      await expect(content(page, view)).toBeVisible();
    });
  }

  test(`${vp.name}: it stays open while items are added and the basket changes`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    const world = await open(page, { view: "empty" });
    await expect(toggle(page)).toHaveAccessibleName("Collapse cart");
    world.view = "draft"; // items are added
    await expect(card(page).getByRole("list").first()).toBeVisible();
    await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
    world.view = "unmatched"; // an item that has no product yet arrives
    await expect(
      card(page).getByText("Unobtainium", { exact: true }),
    ).toBeVisible();
    await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
    world.view = "prepared"; // the basket is prepared
    await expect(card(page).getByText("Total estimated")).toBeVisible();
    await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
    world.qty = { ...world.qty, pasta: 6 }; // and changes
    world.revision += 1;
    await expect(card(page)).toContainText("Revision 2");
    await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
    await expect(card(page).getByText("Total estimated")).toBeVisible();
    expect(
      await page.evaluate(() => localStorage.getItem("aimo.cart.open")),
    ).not.toBe("0"); // nothing stored a closed card behind the customer's back
  });
}

test("the card closes only when the customer closes it, and the choice is remembered", async ({
  page,
}) => {
  const world = await open(page, { view: "draft" });
  await toggle(page).click();
  await expect(toggle(page)).toHaveAccessibleName("Expand cart");
  await expect(card(page).getByRole("list")).toHaveCount(0);
  world.view = "prepared"; // the basket arrives: still closed, the customer closed it
  await expect(confirmButton(page)).toBeVisible();
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "false");
  await expect(card(page).getByText("Total estimated")).toBeHidden();
  await page.reload();
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "false");
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
  await page.reload();
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
  await expect(card(page).getByText("Total estimated")).toBeVisible();
});

test("a closed card with blocked site storage still opens and works", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new Error("blocked");
      },
    });
  });
  await open(page, { view: "draft" });
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "false");
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
});
