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
//    link that opens the Delivery tab and focuses the date; the Delivery tab edits in place (no Edit,
//    Save or Cancel buttons): Enter or leaving the field saves; "Left out: ..." is one muted line (card-left-out);
//  - short product names (weights removed) are shown; the number input keeps its full accessible name
//    "Quantity of <full product name>". No item count in the header, "Empty" for an empty card.
// The style of the number controls is NOT specified here (separate spec). Mocked API, typed fixtures,
// paused page clock. Assumption to confirm: the empty and the unprepared (draft) card have no tabs.

const card = (page: Page) =>
  page.locator("aside#overview, aside[aria-label='Your order']").first();
const tab = (page: Page, name: "Items" | "Delivery" | "Checks" | "Details") =>
  card(page).getByRole("tab", { name: new RegExp(`^${name}`) });
const panel = (page: Page, name: "items" | "delivery" | "checks" | "details") =>
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
// Types into the number input of a panel that is not shown (a script, as no customer can): the card must still react.
const typeHidden = (page: Page, name: string, value: string) =>
  card(page)
    .locator(`input[aria-label="Quantity of ${name}"]`)
    .evaluate((el: HTMLInputElement, v: string) => {
      const set = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      set.call(el, v);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }, value);

async function open(page: Page, over: Partial<CartWorld> = {}) {
  const world = newCart({ stream: true, ...over });
  await openCart(page, world);
  await expect(card(page)).toBeVisible();
  return world;
}
const selected = (
  page: Page,
  name: "Items" | "Delivery" | "Checks" | "Details",
) => expect(tab(page, name)).toHaveAttribute("aria-selected", "true");

// --- the tabs -------------------------------------------------------------------------------

test("the prepared card has the tabs Items, Delivery, Details and Checks in that order; Items is selected and its panel shown", async ({
  page,
}) => {
  await open(page);
  await expect(
    card(page).getByRole("tablist", { name: "Order sections" }),
  ).toBeVisible();
  for (const name of ["Items", "Delivery", "Details", "Checks"] as const)
    await expect(tab(page, name)).toBeVisible();
  expect(await card(page).getByRole("tab").allInnerTexts()).toEqual([
    "Items",
    "Delivery",
    "Details",
    "Checks",
  ]);
  await selected(page, "Items");
  await expect(tab(page, "Delivery")).toHaveAttribute("aria-selected", "false");
  await expect(panel(page, "items")).toBeVisible();
  await expect(panel(page, "delivery")).toBeHidden();
  await expect(panel(page, "checks")).toBeHidden();
  await expect(panel(page, "details")).toBeHidden();
  // All panels stay mounted: the hidden ones are in the page, not removed.
  for (const name of ["items", "delivery", "checks", "details"] as const)
    await expect(panel(page, name)).toHaveCount(1);
  await expect(panel(page, "delivery")).toContainText("hotel-helsinki");
});

test("clicking a tab shows its panel and hides the others; the tab and its panel are linked", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Delivery").click();
  await selected(page, "Delivery");
  await expect(panel(page, "delivery")).toBeVisible();
  await expect(panel(page, "items")).toBeHidden();
  await expect(panel(page, "delivery")).toContainText("hotel-helsinki");
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
  await page.keyboard.press("ArrowRight");
  await selected(page, "Details");
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
    "Diced bacon: No pack size",
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

test("Checks has only the purchasing checks and the approval status", async ({
  page,
}) => {
  await open(page, { outcome: "approval_required" });
  await tab(page, "Checks").click();
  await expect(
    panel(page, "checks").getByRole("heading", { name: "Purchasing checks" }),
  ).toBeVisible();
  await expect(card(page).getByTestId("card-approval")).toHaveText(
    "Approval: pending",
  );
  await expect(panel(page, "checks").getByRole("button")).toHaveCount(0);
  await expect(panel(page, "checks")).not.toContainText(
    /Fixture prices|Revision/,
  );
});

// --- the Details tab: only what the proposal carries -------------------------------------------------

test("Details shows the reference, revision, how long the prices hold, the policy and the substitutions switch", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Details").click();
  const details = panel(page, "details");
  await expect(details).toContainText("Order reference");
  await expect(details).toContainText(ids.proposal.slice(0, 8).toUpperCase());
  await expect(details).toContainText("Revision");
  await expect(details).toContainText(/1 · created/);
  await expect(details).toContainText("Prices valid until");
  await expect(details).toContainText("Policy");
  await expect(details).toContainText("v1 · approval not required");
  const sub = details.getByRole("switch", { name: "Allow substitutions" });
  await expect(sub).toBeDisabled(); // read-only: shows the request, changes nothing
  await expect(sub).toHaveAttribute("aria-checked", "true");
  // The sample notice is here, not on the Checks tab.
  await expect(details).toContainText("Catalog prices and stock");
});

test("the Cut-off row appears only when the lines carry a supplier cut-off", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Details").click();
  await expect(panel(page, "details")).not.toContainText("Cut-off");
});

test("with a supplier cut-off in the evidence the Details tab shows it", async ({
  page,
}) => {
  await open(page, { cutoff: "2026-11-16T14:00:00+02:00" });
  await tab(page, "Details").click();
  await expect(panel(page, "details")).toContainText("Cut-off");
  await expect(panel(page, "details")).toContainText(/16 Nov 2026/);
});

test("an order that was placed shows its order id as the reference", async ({
  page,
}) => {
  await open(page, { orderPlaced: true, editable: false });
  await tab(page, "Details").click();
  await expect(panel(page, "details")).toContainText(ids.sourceOrder);
});

test("Details has no Export manifest and no History link; More opens the full sheet", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Details").click();
  const details = panel(page, "details");
  await expect(
    details.getByRole("button", { name: /Export manifest/ }),
  ).toHaveCount(0);
  await expect(details.getByRole("button", { name: "History" })).toHaveCount(0);
  await expect(details.locator(".purchase-sheet")).toBeHidden();
  await details.getByRole("button", { name: "More" }).click();
  await expect(details.locator(".purchase-sheet")).toBeVisible();
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
  await expect(card(page).getByLabel("Delivery date")).toBeFocused();
});

const PREPARE = `**/api/conversations/${ids.conversation}/prepare-from-cart`;

test("the Delivery tab is a labelled list whose values are edited in place: no Edit, Save or Cancel buttons", async ({
  page,
}) => {
  await open(page);
  await tab(page, "Delivery").click();
  const delivery = panel(page, "delivery");
  await expect(delivery.getByText("Date", { exact: true })).toBeVisible();
  await expect(
    delivery.getByText("Destination", { exact: true }),
  ).toBeVisible();
  await expect(card(page).getByLabel("Delivery date")).toHaveValue(
    "2026-11-17",
  );
  await expect(delivery.getByText("hotel-helsinki")).toBeVisible();
  await expect(delivery.getByRole("button")).toHaveCount(0);
  // No address, contact or note: the backend has none, so no such rows and nothing invented.
  await expect(delivery).not.toContainText(/Address|Contact|Phone|Note/);
  // Plain text until it is hovered or focused: no dashed underline.
  const date = card(page).getByLabel("Delivery date");
  expect(
    await date.evaluate((e) => getComputedStyle(e).borderBottomStyle),
  ).not.toBe("dashed");
  expect(await date.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe(
    "rgba(0, 0, 0, 0)",
  );
  await date.hover();
  expect(
    await date.evaluate((e) => getComputedStyle(e).backgroundColor),
  ).not.toBe("rgba(0, 0, 0, 0)");
});

test("Enter in the date saves it: one prepare-from-cart request with one request id", async ({
  page,
}) => {
  const requests: Record<string, unknown>[] = [];
  const world = await open(page);
  await page.route(PREPARE, (route) => {
    requests.push(route.request().postDataJSON());
    return problem(route, 409, "CART_NOT_VERIFIED", "The cart changed.");
  });
  await tab(page, "Delivery").click();
  const date = card(page).getByLabel("Delivery date");
  await date.fill("2026-11-20");
  expect(requests).toHaveLength(0); // typing alone saves nothing
  await date.press("Enter");
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({
    delivery_date: "2026-11-20",
    destination: "hotel-helsinki",
  });
  expect(requests[0].request_id).toEqual(expect.stringMatching(/^.{8,120}$/));
  expect(world.puts).toHaveLength(0);
});

test("leaving the date field saves it too; an unchanged date sends nothing", async ({
  page,
}) => {
  const requests: Record<string, unknown>[] = [];
  await open(page);
  await page.route(PREPARE, (route) => {
    requests.push(route.request().postDataJSON());
    return problem(route, 409, "CART_NOT_VERIFIED", "The cart changed.");
  });
  await tab(page, "Delivery").click();
  const date = card(page).getByLabel("Delivery date");
  await date.focus();
  await date.blur();
  await page.waitForTimeout(300);
  expect(requests).toHaveLength(0);
  await date.fill("2026-11-21");
  await date.blur();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({ delivery_date: "2026-11-21" });
});

test("a date before tomorrow is not sent: a hint says why, Escape puts the old date back", async ({
  page,
}) => {
  const requests: Record<string, unknown>[] = [];
  await open(page);
  await page.route(PREPARE, (route) => {
    requests.push(route.request().postDataJSON());
    return problem(route, 409, "X", "x");
  });
  await tab(page, "Delivery").click();
  const date = card(page).getByLabel("Delivery date");
  await date.fill("2026-11-14");
  await date.press("Enter");
  await expect(card(page).getByTestId("delivery-hint")).toContainText(
    "Choose a delivery date on or after",
  );
  expect(requests).toHaveLength(0);
  await date.press("Escape");
  await expect(date).toHaveValue("2026-11-17");
  await expect(card(page).getByTestId("delivery-hint")).toHaveCount(0);
});

test("with several destinations the destination is a list that saves when a different one is picked", async ({
  page,
}) => {
  const requests: Record<string, unknown>[] = [];
  await open(page);
  await page.route("**/api/settings/policy", (route) =>
    json(route, {
      buyer_id: "demo-hotel",
      policy_version: 1,
      rules: {
        currency: "EUR",
        destinations: ["hotel-helsinki", "hotel-espoo"],
      },
      can_edit: true,
      approval_authority: { can_approve: true },
      history: [],
    }),
  );
  await page.reload();
  await expect(card(page)).toBeVisible();
  await page.route(PREPARE, (route) => {
    requests.push(route.request().postDataJSON());
    return problem(route, 409, "X", "x");
  });
  await tab(page, "Delivery").click();
  await card(page).getByLabel("Destination").selectOption("hotel-espoo");
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({
    destination: "hotel-espoo",
    delivery_date: "2026-11-17",
  });
});

test("the Delivery values are plain text once the order is placed", async ({
  page,
}) => {
  await open(page, { orderPlaced: true, editable: false });
  await tab(page, "Delivery").click();
  await expect(panel(page, "delivery")).toContainText("Tue 17 Nov 2026");
  await expect(panel(page, "delivery")).toContainText("hotel-helsinki");
  await expect(card(page).getByLabel("Delivery date")).toHaveCount(0);
  await expect(
    panel(page, "delivery").locator("input, select, button"),
  ).toHaveCount(0);
});

test("a saved date that fails shows its error in the footer and brings the tab back to Items", async ({
  page,
}) => {
  await open(page);
  await page.route(PREPARE, (route) =>
    problem(route, 409, "CART_NOT_VERIFIED", "The cart changed."),
  );
  await tab(page, "Delivery").click();
  await card(page).getByLabel("Delivery date").fill("2026-11-20");
  await card(page).getByLabel("Delivery date").press("Enter");
  await expect(footer(page).getByRole("alert")).toContainText(
    "The cart changed.",
  );
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
  await typeHidden(page, PASTA.name, "5");
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
  for (const name of ["Items", "Delivery", "Details", "Checks"] as const)
    await expect(tab(page, name)).toBeInViewport(); // four labels fit in 390 px
  await expect(footer(page)).toBeInViewport();
  await expect(confirmButton(page)).toBeInViewport();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("on a phone collapsing puts the whole card behind the corner button, and expanding brings back the total and the button", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page);
  await card(page).getByRole("button", { name: "Collapse cart" }).click();
  // The page clock is paused in these specs, so the shell's slide animation needs ticks to finish.
  await page.waitForTimeout(250); // let React mount before ticking the paused clock
  await page.clock.runFor(1000);
  await expect(card(page).getByRole("tablist")).toBeHidden();
  await expect(confirmButton(page)).toHaveCount(0); // collapsed, the button is behind the corner button
  await card(page).getByRole("button", { name: "Expand cart" }).click();
  await page.waitForTimeout(250); // let React mount before ticking the paused clock
  await page.clock.runFor(1000);
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
  await typeHidden(page, PASTA.name, "5");
  await expect
    .poll(async () => (await tabLog(page)).map((e) => `${e.tab}:${e.why}`))
    .toContain("items:edit");
  const text = JSON.stringify(await tabLog(page));
  expect(text).not.toMatch(/Spaghetti|Diced bacon|Eggs/); // no item names in the log
});

// --- the VAT breakdown: the "i" on the right of the total row ---------------------------------------

const vatButton = (page: Page) =>
  footer(page).getByRole("button", { name: "VAT breakdown" });
const vat = (page: Page) => footer(page).getByTestId("card-vat");

test("VAT is closed by default behind a real button named VAT breakdown; the total itself is not a button", async ({
  page,
}) => {
  await open(page);
  await expect(vatButton(page)).toBeVisible();
  await expect(vatButton(page)).toHaveAttribute("aria-expanded", "false");
  await expect(vat(page)).toBeHidden();
  const controls = await vatButton(page).getAttribute("aria-controls");
  expect(controls).toBeTruthy();
  await expect(footer(page).locator(`[id="${controls}"]`)).toHaveCount(1);
  await expect(
    footer(page).getByRole("button", { name: /136[.,]00/ }),
  ).toHaveCount(0);
});

test("pressing the i shows Excl. VAT, VAT 14% and Total under the total, pressing again hides them", async ({
  page,
}) => {
  await open(page);
  await vatButton(page).click();
  await expect(vatButton(page)).toHaveAttribute("aria-expanded", "true");
  await expect(vat(page)).toBeVisible();
  await expect(vat(page)).toContainText("Excl. VAT");
  await expect(vat(page)).toContainText("VAT 14%");
  await expect(vat(page)).toContainText("Total");
  await vatButton(page).click();
  await expect(vatButton(page)).toHaveAttribute("aria-expanded", "false");
  await expect(vat(page)).toBeHidden();
});

test("the amounts are the proposal's, never recomputed in the browser", async ({
  page,
}) => {
  // Totals that do not follow from the lines: whatever the proposal says is what is shown.
  await open(page, {
    totals: { net: "111.11", tax: "24.89", gross: "136.00" },
  });
  await vatButton(page).click();
  await expect(vat(page)).toContainText(/111[.,]11/);
  await expect(vat(page)).toContainText(/24[.,]89/);
  await expect(vat(page)).toContainText(/136[.,]00/);
});

test("the i works from the keyboard: Enter and Space toggle it", async ({
  page,
}) => {
  await open(page);
  await vatButton(page).focus();
  await page.keyboard.press("Enter");
  await expect(vat(page)).toBeVisible();
  await page.keyboard.press("Space");
  await expect(vat(page)).toBeHidden();
});

test("the i is on the right, level with the amount; the breakdown is under the total and above the button", async ({
  page,
}) => {
  await open(page);
  await vatButton(page).click();
  const total = await footer(page).getByTestId("card-total-row").boundingBox();
  const amount = await footer(page)
    .getByText(/136[.,]00/)
    .first()
    .boundingBox();
  const i = await vatButton(page).boundingBox();
  const breakdown = await vat(page).boundingBox();
  const button = await confirmButton(page).boundingBox();
  // same line as the amount (vertical centres within a few pixels) and at the far right of the row
  expect(
    Math.abs(i!.y + i!.height / 2 - (amount!.y + amount!.height / 2)),
  ).toBeLessThan(10);
  expect(i!.x).toBeGreaterThan(amount!.x + amount!.width);
  expect(i!.x + i!.width).toBeGreaterThan(total!.x + total!.width - 12);
  // order in the page: total row, then the breakdown, then the Confirm purchase button
  expect(breakdown!.y).toBeGreaterThanOrEqual(total!.y + total!.height - 1);
  expect(breakdown!.y + breakdown!.height).toBeLessThanOrEqual(button!.y + 1);
});

test("when the order is not ready the chip is on the right of the row, before the i", async ({
  page,
}) => {
  await open(page, { outcome: "approval_required" });
  const chip = await footer(page).getByTestId("card-status-chip").boundingBox();
  const i = await vatButton(page).boundingBox();
  expect(chip!.x + chip!.width).toBeLessThanOrEqual(i!.x + 1);
  expect(
    Math.abs(chip!.y + chip!.height / 2 - (i!.y + i!.height / 2)),
  ).toBeLessThan(10);
});

test("the breakdown stays open across tab switches and a basket update; a new basket closes it", async ({
  page,
}) => {
  const world = await open(page, { renew: false });
  await vatButton(page).click();
  await tab(page, "Checks").click();
  await tab(page, "Delivery").click();
  await expect(vat(page)).toBeVisible();
  world.revision += 1; // the same proposal, updated
  await page.waitForTimeout(1200);
  await expect(vat(page)).toBeVisible();
  await expect(vatButton(page)).toHaveAttribute("aria-expanded", "true");
  world.renew = true;
  world.seq += 1; // a NEW proposal
  world.revision = 1;
  await expect(vat(page)).toBeHidden();
  await expect(vatButton(page)).toHaveAttribute("aria-expanded", "false");
});

test("an unresolved total has no i at all", async ({ page }) => {
  await open(page, { unresolved: "bacon" });
  await expect(vatButton(page)).toHaveCount(0);
});

test("nothing about VAT in Checks, in Details or in More", async ({ page }) => {
  await open(page);
  await tab(page, "Checks").click();
  await expect(panel(page, "checks")).not.toContainText(/\bVAT\b/i);
  await tab(page, "Details").click();
  await panel(page, "details").getByRole("button", { name: "More" }).click();
  await expect(panel(page, "details")).not.toContainText(/\bVAT\b/i);
});

// --- the number control: carets on hover ----------------------------------------------------------

const caretUp = (page: Page, name: string) =>
  card(page).getByRole("button", {
    name: `Increase quantity of ${name}`,
    exact: true,
  });
const caretDown = (page: Page, name: string) =>
  card(page).getByRole("button", {
    name: `Decrease quantity of ${name}`,
    exact: true,
  });

test("carets are invisible until the row is hovered, and shown by keyboard focus", async ({
  page,
}) => {
  await open(page);
  await expect(caretUp(page, PASTA.name)).toHaveCSS("opacity", "0");
  await expect(caretDown(page, PASTA.name)).toHaveCSS("opacity", "0");
  await qty(page, PASTA.name).hover();
  await expect(caretUp(page, PASTA.name)).toHaveCSS("opacity", "1");
  await expect(caretDown(page, PASTA.name)).toHaveCSS("opacity", "1");
  await page.mouse.move(5, 5);
  await expect(caretUp(page, PASTA.name)).toHaveCSS("opacity", "0");
  await qty(page, PASTA.name).focus();
  await expect(caretUp(page, PASTA.name)).toHaveCSS("opacity", "1");
});

test("the caret above is above the number and the caret below is below it", async ({
  page,
}) => {
  await open(page);
  const up = await caretUp(page, PASTA.name).boundingBox();
  const number = await qty(page, PASTA.name).boundingBox();
  const down = await caretDown(page, PASTA.name).boundingBox();
  expect(up!.y + up!.height).toBeLessThanOrEqual(number!.y + 1);
  expect(down!.y).toBeGreaterThanOrEqual(number!.y + number!.height - 1);
});

test("no plus or minus buttons and no dashed underline; the carets still change the number", async ({
  page,
}) => {
  const world = await open(page);
  for (const el of [caretUp(page, PASTA.name), caretDown(page, PASTA.name)])
    await expect(el).not.toHaveText(/^[+−-]|add|remove/);
  const input = qty(page, PASTA.name);
  expect(
    await input.evaluate((e) => getComputedStyle(e).borderBottomStyle),
  ).not.toBe("dashed");
  expect(
    await input.evaluate((e) => getComputedStyle(e).textDecorationStyle),
  ).not.toBe("dashed");
  await caretUp(page, PASTA.name).click();
  await expect(input).toHaveValue("5");
  await tick(page, 650);
  await expect.poll(() => world.puts.length).toBe(1);
  expect(world.puts[0].body.lines).toEqual([
    { product_id: "pasta", sales_quantity: 5 },
  ]);
});

test.describe("on a touch screen", () => {
  test.use({ hasTouch: true, isMobile: true });
  test("the carets are faint all the time", async ({ page }) => {
    await open(page);
    const opacity = await caretUp(page, PASTA.name).evaluate((e) =>
      Number(getComputedStyle(e).opacity),
    );
    expect(opacity).toBeGreaterThan(0.2);
    expect(opacity).toBeLessThan(0.8);
  });
});

// --- names that differ only by pack size ------------------------------------------------------------

test("two products that differ only by pack size keep their weights so they can be told apart; the full name is the row's title", async ({
  page,
}) => {
  await open(page, { names: { bacon: "Spaghetti 500 g" } }); // pasta stays "Spaghetti 5 kg"
  const rows = panel(page, "items").locator('[data-testid="cart-line"]');
  await expect(rows.nth(0)).toContainText("Spaghetti 5 kg");
  await expect(rows.nth(1)).toContainText("Spaghetti 500 g");
  await expect(rows.nth(0).getByTitle("Spaghetti 5 kg")).toHaveCount(1);
  await expect(rows.nth(1).getByTitle("Spaghetti 500 g")).toHaveCount(1);
  // The other rows still show the short name.
  await expect(rows.nth(2)).toContainText("Eggs");
  await expect(rows.nth(2)).not.toContainText("30 pcs");
});

test("a short name keeps the full name as its title and in the More sheet", async ({
  page,
}) => {
  await open(page);
  await expect(panel(page, "items").getByTitle("Spaghetti 5 kg")).toHaveCount(
    1,
  );
  await tab(page, "Details").click();
  await panel(page, "details").getByRole("button", { name: "More" }).click();
  await expect(panel(page, "details").locator(".purchase-sheet")).toContainText(
    "Spaghetti 5 kg",
  );
});
