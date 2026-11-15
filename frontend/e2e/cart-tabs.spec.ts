import { expect, test, type Page } from "@playwright/test";
import {
  BACON,
  newCart,
  openCart,
  PASTA,
  type CartWorld,
} from "./support/cartFixtures";
import { ids, json, problem } from "./support/schedulerFixtures";

// SPEC (written before the build; fails until layout D exists). The prepared card is three tabs
// (Items | Delivery | Checks) with the total and the green Confirm purchase pinned under them.
// Owner's layout D; build rules from the coordinator:
//  - tabs are role=tab buttons (aria-selected) in a tablist named "Order sections"; ALL panels stay
//    mounted (the inactive ones hidden): data-testid card-panel-items | card-panel-delivery | card-panel-checks;
//  - Items is the default tab; the tab goes back to Items on any edit, any error and a NEW basket
//    (new proposal id), never because a basket was updated, and a customer's click is kept;
//  - the pinned footer (data-testid card-footer) holds: the total, the status chip only when the order
//    is not ready (card-status-chip), the Confirm purchase button, one reason line (card-reason, the
//    button's aria-describedby), the status line (card-status), errors (role=alert, with Try again) and
//    Reject for approvers;
//  - a blocker is never only under Checks: it is in card-reason and the Checks tab has a badge
//    (card-checks-badge);
//  - delivery is one line (card-delivery-line) "Tue 17 Nov · hotel-helsinki" with an "Edit delivery"
//    button that opens the Delivery tab; "Left out: ..." is one muted line (card-left-out);
//  - short product names (weights removed) are shown; the number input keeps its full accessible name
//    "Quantity of <full product name>". No item count in the header, "Empty" for an empty card.
// The style of the number controls is NOT specified here (separate spec). Mocked API, typed fixtures,
// paused page clock. Assumption to confirm: the empty and the unprepared (draft) card have no tabs.

const card = (page: Page) =>
  page.locator("aside#overview, aside[aria-label='Your order']").first();
const tab = (page: Page, name: "Items" | "Delivery" | "Checks") =>
  card(page).getByRole("tab", { name: new RegExp(`^${name}`) });
const panel = (page: Page, name: "items" | "delivery" | "checks") =>
  card(page).locator(`[data-testid="card-panel-${name}"]`);
const footer = (page: Page) => card(page).getByTestId("card-footer");
const confirmButton = (page: Page) =>
  footer(page).getByRole("button", { name: "Confirm purchase" });
const reason = (page: Page) => footer(page).getByTestId("card-reason");
const qty = (page: Page, name: string) =>
  card(page).getByRole("spinbutton", {
    name: `Quantity of ${name}`,
    exact: true,
  });
const tick = (page: Page, ms: number) => page.clock.runFor(ms);

async function open(page: Page, over: Partial<CartWorld> = {}) {
  const world = newCart({ stream: true, ...over });
  await openCart(page, world);
  await expect(card(page)).toBeVisible();
  return world;
}
const selected = (page: Page, name: "Items" | "Delivery" | "Checks") =>
  expect(tab(page, name)).toHaveAttribute("aria-selected", "true");

// --- the tabs -------------------------------------------------------------------------------

test("the prepared card has the tabs Items, Delivery and Checks; Items is selected and its panel shown", async ({
  page,
}) => {
  await open(page);
  await expect(
    card(page).getByRole("tablist", { name: "Order sections" }),
  ).toBeVisible();
  for (const name of ["Items", "Delivery", "Checks"] as const)
    await expect(tab(page, name)).toBeVisible();
  await selected(page, "Items");
  await expect(tab(page, "Delivery")).toHaveAttribute("aria-selected", "false");
  await expect(panel(page, "items")).toBeVisible();
  await expect(panel(page, "delivery")).toBeHidden();
  await expect(panel(page, "checks")).toBeHidden();
  // All panels stay mounted: the hidden ones are in the page, not removed.
  for (const name of ["items", "delivery", "checks"] as const)
    await expect(panel(page, name)).toHaveCount(1);
  await expect(card(page).getByLabel("Delivery date")).toHaveCount(1);
});

test("clicking a tab shows its panel and hides the others; the tab and its panel are linked", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Delivery").click();
  await selected(page, "Delivery");
  await expect(panel(page, "delivery")).toBeVisible();
  await expect(panel(page, "items")).toBeHidden();
  await expect(card(page).getByLabel("Delivery date")).toBeVisible();
  await tab(page, "Checks").click();
  await selected(page, "Checks");
  await expect(panel(page, "checks")).toBeVisible();
  await expect(panel(page, "delivery")).toBeHidden();
  const controls = await tab(page, "Checks").getAttribute("aria-controls");
  expect(controls).toBeTruthy();
  await expect(card(page).locator(`[id="${controls}"]`)).toHaveAttribute(
    "role",
    "tabpanel",
  );
});

test("the tabs work from the keyboard: arrows, Home and End", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Items").focus();
  await page.keyboard.press("ArrowRight");
  await selected(page, "Delivery");
  await expect(tab(page, "Delivery")).toBeFocused();
  await page.keyboard.press("End");
  await selected(page, "Checks");
  await page.keyboard.press("ArrowRight");
  await selected(page, "Items"); // wraps around
  await page.keyboard.press("ArrowLeft");
  await selected(page, "Checks");
  await page.keyboard.press("Home");
  await selected(page, "Items");
});

test("the empty and the unprepared cards have no tabs: Empty, or the items with the button", async ({
  page,
}) => {
  await open(page, { view: "empty" });
  await expect(card(page).getByRole("tablist")).toHaveCount(0);
  await expect(card(page).getByText("Empty", { exact: true })).toBeVisible();
  await expect(confirmButton(page)).toBeDisabled();
  await expect(reason(page)).toHaveText("Add items first");
});

// --- the header and the words -----------------------------------------------------------------

test("no item count in the header, and no status chip while the order is ready", async ({
  page,
}) => {
  await open(page, { outcome: "ready_to_commit" });
  await expect(card(page)).not.toContainText(/items staged/);
  await expect(card(page).getByTestId("card-status-chip")).toHaveCount(0);
});

test("a status chip shows when the order is not ready: needs a decision", async ({
  page,
}) => {
  await open(page, { outcome: "approval_required" });
  await expect(card(page).getByTestId("card-status-chip")).toContainText(
    "Pending",
  );
  await expect(footer(page).getByTestId("card-status-chip")).toBeVisible();
});

test("short product names without weights; the number input keeps the full name for assistive technology", async ({
  page,
}) => {
  await open(page);
  const items = panel(page, "items");
  await expect(items).toContainText("Spaghetti");
  await expect(items).toContainText("Diced bacon");
  await expect(items).toContainText("Eggs");
  await expect(items).not.toContainText(/5 kg|1 kg|30 pcs/);
  await expect(qty(page, PASTA.name)).toHaveValue("4");
  await expect(qty(page, BACON.name)).toHaveValue("2");
});

// --- the pinned footer --------------------------------------------------------------------------

test("the footer is under the tabs and shows the total and the button on every tab", async ({
  page,
}) => {
  await open(page);
  const tabs = await card(page).getByRole("tablist").boundingBox();
  const pinned = await footer(page).boundingBox();
  expect(tabs!.y + tabs!.height).toBeLessThanOrEqual(pinned!.y + 1);
  for (const name of ["Items", "Delivery", "Checks"] as const) {
    await tab(page, name).click();
    await expect(footer(page)).toBeVisible();
    await expect(footer(page)).toContainText("Total");
    await expect(footer(page)).toContainText(/136[.,]00/);
    await expect(confirmButton(page)).toBeEnabled();
  }
});

test("the footer says why the button is grey, in one line that the button points to", async ({
  page,
}) => {
  await open(page, { busy: true });
  await expect(confirmButton(page)).toBeDisabled();
  await expect(reason(page)).toHaveText(
    "The assistant is still working on your request.",
  );
  await expect(confirmButton(page)).toHaveAccessibleDescription(
    "The assistant is still working on your request.",
  );
});

test("an ordered purchase: a grey button with the reason, no Reject, no Edit", async ({
  page,
}) => {
  await open(page, { orderPlaced: true, editable: false });
  await expect(confirmButton(page)).toBeDisabled();
  await expect(reason(page)).toHaveText("This order was already placed.");
  await expect(
    footer(page).getByRole("button", { name: "Reject" }),
  ).toHaveCount(0);
  await expect(
    card(page).getByRole("button", { name: "Edit delivery" }),
  ).toHaveCount(0);
});

test("Reject is in the footer for an approver of a pending order, and only then", async ({
  page,
}) => {
  await open(page, { outcome: "approval_required" });
  await expect(
    footer(page).getByRole("button", { name: "Reject" }),
  ).toBeVisible();
});

test("no Reject when the order is ready", async ({ page }) => {
  await open(page, { outcome: "ready_to_commit" });
  await expect(
    footer(page).getByRole("button", { name: "Reject" }),
  ).toHaveCount(0);
});

test("changed terms: the status line in the footer says so and the next press confirms the new revision", async ({
  page,
}) => {
  const world = await open(page, { renew: false });
  await page.route(`**/api/purchases/*/confirm`, (route) => {
    world.revision += 1; // the basket changed under the customer
    return json(route, {
      status: "revised",
      proposal_id: ids.proposal,
      revision: world.revision,
    });
  });
  await confirmButton(page).click();
  await expect(footer(page).getByTestId("card-status")).toContainText(
    "Terms changed during verification",
  );
  await expect(confirmButton(page)).toBeEnabled();
});

test("an edit that fails: the error is in the footer with Try again, whatever tab is open, and the tab goes back to Items", async ({
  page,
}) => {
  const world = await open(page);
  world.failNext = { status: 500, code: "INTERNAL", message: "boom" };
  await qty(page, PASTA.name).fill("9");
  await tick(page, 650);
  await expect(footer(page).getByRole("alert")).toContainText(
    "The quantity could not be saved.",
  );
  await expect(
    footer(page).getByRole("button", { name: "Try again" }),
  ).toBeVisible();
  await selected(page, "Items");
});

// --- blockers are never only under Checks -----------------------------------------------------

test("a product without a pack size: the footer says which one and why, the Checks tab has a badge", async ({
  page,
}) => {
  await open(page, { unresolved: "bacon" });
  await expect(confirmButton(page)).toBeDisabled();
  await expect(reason(page)).toHaveText("Diced bacon: no pack size");
  await expect(confirmButton(page)).toHaveAccessibleDescription(
    "Diced bacon: no pack size",
  );
  await expect(
    tab(page, "Checks").getByTestId("card-checks-badge"),
  ).toBeVisible();
  // The blocked line itself shows it has no number.
  await expect(panel(page, "items")).toContainText("Unresolved");
  // The full sentence and its code are under Checks.
  await tab(page, "Checks").click();
  await expect(panel(page, "checks")).toContainText(
    "This product has no pack size in its data",
  );
  await expect(panel(page, "checks")).toContainText("QUANTITY_UNRESOLVED");
});

for (const blocked of [
  {
    name: "denied by the purchasing checks",
    over: { outcome: "denied" as const },
    sentence:
      "This order cannot be confirmed yet. Resolve the purchasing checks.",
  },
  {
    name: "needs resolution",
    over: { outcome: "needs_resolution" as const },
    sentence:
      "This order cannot be confirmed yet. Resolve the purchasing checks.",
  },
  {
    name: "expired",
    over: { expired: true },
    sentence: "This order expired. Change it to prepare a new one.",
  },
]) {
  test(`${blocked.name}: the footer line and a badge on Checks, without opening Checks`, async ({
    page,
  }) => {
    await open(page, blocked.over);
    await expect(confirmButton(page)).toBeDisabled();
    await expect(reason(page)).toHaveText(blocked.sentence);
    await expect(
      tab(page, "Checks").getByTestId("card-checks-badge"),
    ).toBeVisible();
    await selected(page, "Items");
  });
}

test("a ready order has no badge on Checks and no blocker line", async ({
  page,
}) => {
  await open(page);
  await expect(
    tab(page, "Checks").getByTestId("card-checks-badge"),
  ).toHaveCount(0);
  await expect(reason(page)).toHaveCount(0);
});

test("Checks has the purchasing checks and More opens the details", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Checks").click();
  await expect(
    panel(page, "checks").getByRole("heading", { name: "Purchasing checks" }),
  ).toBeVisible();
  const more = panel(page, "checks").getByRole("button", { name: "More" });
  await expect(panel(page, "checks").locator(".purchase-sheet")).toBeHidden();
  await more.click();
  await expect(panel(page, "checks").locator(".purchase-sheet")).toBeVisible();
});

// --- delivery in one line ---------------------------------------------------------------------

test("delivery is one line with the date and the destination, and Edit delivery opens the Delivery tab", async ({
  page,
}) => {
  await open(page);
  const line = card(page).getByTestId("card-delivery-line");
  await expect(line).toHaveText(/^Tue 17 Nov · hotel-helsinki/);
  await line.getByRole("button", { name: "Edit delivery" }).click();
  await selected(page, "Delivery");
  await expect(card(page).getByLabel("Delivery date")).toBeVisible();
});

test("Update delivery details sends one request id; its error shows in the footer and brings the tab back to Items", async ({
  page,
}) => {
  const requests: Record<string, unknown>[] = [];
  await open(page);
  await page.route(
    `**/api/conversations/${ids.conversation}/prepare-from-cart`,
    (route) => {
      requests.push(route.request().postDataJSON());
      return problem(route, 409, "CART_NOT_VERIFIED", "The cart changed.");
    },
  );
  await card(page)
    .getByTestId("card-delivery-line")
    .getByRole("button", { name: "Edit delivery" })
    .click();
  await card(page).getByLabel("Delivery date").fill("2026-11-20");
  await card(page)
    .getByRole("button", { name: "Update delivery details" })
    .click();
  await expect(footer(page).getByRole("alert")).toContainText(
    "The cart changed.",
  );
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({
    delivery_date: "2026-11-20",
    destination: "hotel-helsinki",
  });
  expect(requests[0].request_id).toEqual(expect.stringMatching(/^.{8,120}$/));
  await selected(page, "Items"); // an error brings the tab back to Items
});

test("a blocked order reads differently on the delivery line; an ordered one has no Edit", async ({
  page,
}) => {
  await open(page, { outcome: "needs_resolution" });
  await expect(card(page).getByTestId("card-delivery-line")).toHaveText(
    /^Blocked · /,
  );
});

test("an ordered purchase's delivery line says Order placed", async ({
  page,
}) => {
  await open(page, { orderPlaced: true, editable: false });
  await expect(card(page).getByTestId("card-delivery-line")).toHaveText(
    /^Order placed · /,
  );
});

// --- left out ---------------------------------------------------------------------------------

test("Left out is one muted line with the reason of each item", async ({
  page,
}) => {
  await open(page, {
    unmatched: [
      { name: "Unobtainium", amount: "3", unit: "kg", reason: "no_product" },
      { name: "Basil", amount: null, unit: "bunch", reason: "no_quantity" },
    ],
  });
  const line = card(page).getByTestId("card-left-out");
  await expect(line).toHaveText(
    "Left out: Unobtainium (no product yet), Basil (quantity needed)",
  );
  expect(
    await line.evaluate((e) => e.getBoundingClientRect().height),
  ).toBeLessThan(80);
});

test("a removed line is listed as Left out only after its ghost is gone, and after a reload", async ({
  page,
}) => {
  await open(page);
  await expect(card(page).getByTestId("card-left-out")).toHaveCount(0);
  await qty(page, PASTA.name).fill("0");
  await tick(page, 650);
  await expect(card(page).locator('[data-testid="ghost-line"]')).toBeVisible();
  await expect(card(page).getByTestId("card-left-out")).toHaveCount(0); // not twice
  await tick(page, 15_600);
  await expect(card(page).getByTestId("card-left-out")).toHaveText(
    "Left out: Spaghetti (removed by you)",
  );
  await page.reload();
  await expect(card(page).getByTestId("card-left-out")).toHaveText(
    "Left out: Spaghetti (removed by you)",
  );
});

// --- the tab rules ----------------------------------------------------------------------------

test("a customer's click on a tab is kept while nothing else happens", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Checks").click();
  await page.waitForTimeout(1200); // the stream re-sends the same basket several times
  await selected(page, "Checks");
});

test("an edit brings the tab back to Items (here typed by a script into the hidden panel)", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Checks").click();
  await qty(page, PASTA.name).fill("5", { force: true }); // typed into the hidden panel by a script
  await selected(page, "Items");
});

test("a NEW basket (new proposal id) brings the tab back to Items", async ({
  page,
}) => {
  const world = await open(page);
  await tab(page, "Checks").click();
  world.seq += 1;
  world.revision = 1;
  await selected(page, "Items");
});

test("a basket that is only updated (same proposal, new revision) leaves the tab where it is", async ({
  page,
}) => {
  const world = await open(page, { renew: false });
  await tab(page, "Delivery").click();
  world.revision += 1;
  await page.waitForTimeout(1200);
  await selected(page, "Delivery");
});

// --- the edit state lives above the tabs ----------------------------------------------------------

test("a typed number and the ghost survive switching tabs; the ghost fades on its own timer", async ({
  page,
}) => {
  await open(page);
  await qty(page, PASTA.name).fill("0");
  await tick(page, 650);
  const ghost = card(page).locator('[data-testid="ghost-line"]');
  await expect(ghost).toBeVisible();
  await tab(page, "Delivery").click();
  await tick(page, 5_000);
  await tab(page, "Items").click();
  await expect(ghost).toHaveAttribute("data-state", "ghost");
  await tab(page, "Checks").click();
  await tick(page, 11_000); // 15 s since the answer, while Items is not shown
  await expect(card(page).getByTestId("cart-live-note")).toHaveText(
    "Removed Spaghetti 5 kg",
  );
  await tab(page, "Items").click();
  await expect(ghost).toHaveCount(0);
});

// --- the phone drawer ---------------------------------------------------------------------------

test("on a phone the tabs and the pinned footer fit the open drawer", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page);
  await expect(tab(page, "Items")).toBeInViewport();
  await expect(footer(page)).toBeInViewport();
  await expect(confirmButton(page)).toBeInViewport();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("on a phone the collapsed card still shows the total and the button", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page);
  await card(page).getByRole("button", { name: "Collapse cart" }).click();
  await expect(card(page).getByRole("tablist")).toBeHidden();
  await expect(footer(page)).toBeInViewport();
  await expect(footer(page)).toContainText(/136[.,]00/);
  await expect(confirmButton(page)).toBeInViewport();
  await expect(confirmButton(page)).toBeEnabled();
});

// --- the debug log ------------------------------------------------------------------------------

type Entry = Record<string, unknown> & { kind: string };
const tabLog = (page: Page) =>
  page.evaluate(
    () =>
      (
        (window as unknown as { __aimoCardLog?: Entry[] }).__aimoCardLog ?? []
      ).filter((e) => e.kind === "tab") as Entry[],
  );

test("in debug mode every tab decision is logged with the reason", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("aimo.debug", "1"));
  const world = newCart({ stream: true });
  await openCart(page, world);
  await expect(card(page)).toBeVisible();
  await expect
    .poll(async () => (await tabLog(page)).map((e) => `${e.tab}:${e.why}`))
    .toContain("items:default");
  await tab(page, "Checks").click();
  await expect
    .poll(async () => (await tabLog(page)).map((e) => `${e.tab}:${e.why}`))
    .toContain("checks:user click");
  await qty(page, PASTA.name).fill("5", { force: true });
  await expect
    .poll(async () => (await tabLog(page)).map((e) => `${e.tab}:${e.why}`))
    .toContain("items:edit");
  const text = JSON.stringify(await tabLog(page));
  expect(text).not.toMatch(/Spaghetti|Diced bacon|Eggs/); // no item names in the log
});
