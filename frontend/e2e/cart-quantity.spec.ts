import { expect, test, type Page } from "@playwright/test";
import {
  BACON,
  EGGS,
  newCart,
  openCart,
  PASTA,
  type CartWorld,
} from "./support/cartFixtures";

// SPEC (written before the UI; fails until built). The customer edits the number of packs of each
// line of the prepared basket on the card: a number input with minus and plus, debounced about
// 600 ms into PUT /api/conversations/{id}/cart; a line set to 0 stays as a greyed "ghost" for 15
// seconds and can be put back; then it fades away. Texts, test ids and routes: docs/cart-quantity.md.
// Mocked API with typed fixtures (a7's contract, commit a802d54); the page clock is paused, so every
// timer is driven with page.clock.runFor. Nothing here proves the live backend.

const overview = (page: Page) =>
  page.getByRole("complementary", { name: "Overview" });
const qty = (page: Page, name: string) =>
  overview(page).getByLabel(`Quantity of ${name}`);
const row = (page: Page, id: string) =>
  overview(page).locator(`[data-testid="cart-line"][data-product-id="${id}"]`);
const ghost = (page: Page, id: string) =>
  overview(page).locator(`[data-testid="ghost-line"][data-product-id="${id}"]`);
const updating = (page: Page) => overview(page).getByTestId("cart-updating");
const note = (page: Page) => overview(page).getByTestId("cart-live-note");
const tick = (page: Page, ms: number) => page.clock.runFor(ms);
const REQUEST_ID = /^.{8,120}$/;

async function open(page: Page, world: CartWorld = newCart()) {
  await openCart(page, world);
  await expect(overview(page)).toContainText("Total estimated");
  return world;
}

// --- the controls ---------------------------------------------------------------------------

test("each line of the prepared basket has a labelled number input with minus and plus", async ({
  page,
}) => {
  await open(page);
  for (const [product, packs] of [
    [PASTA, "4"],
    [BACON, "2"],
  ] as const) {
    const input = qty(page, product.name);
    await expect(input).toHaveValue(packs);
    await expect(input).toHaveAttribute("type", "number");
    await expect(input).toHaveAttribute("min", "0");
    await expect(input).toBeEnabled();
    await expect(
      overview(page).getByRole("button", {
        name: `Decrease quantity of ${product.name}`,
      }),
    ).toBeEnabled();
    await expect(
      overview(page).getByRole("button", {
        name: `Increase quantity of ${product.name}`,
      }),
    ).toBeEnabled();
    await expect(row(page, product.id)).toContainText(product.salesUnit);
  }
});

test("there are no number controls once the purchase is an order", async ({
  page,
}) => {
  await open(page, newCart({ orderPlaced: true, editable: false }));
  await expect(overview(page).getByLabel(/^Quantity of /)).toHaveCount(0);
  await expect(overview(page)).toContainText("Spaghetti 5 kg");
  await expect(overview(page)).toContainText("4 BAG");
});

test("the controls work from the keyboard: arrow keys, Enter sends at once, plus and minus are buttons", async ({
  page,
  browserName,
}) => {
  test.skip(browserName !== "chromium", "number-input arrow keys: Chromium");
  const world = await open(page);
  await qty(page, PASTA.name).focus();
  await page.keyboard.press("ArrowUp");
  await expect(qty(page, PASTA.name)).toHaveValue("5");
  expect(world.puts).toHaveLength(0); // still inside the debounce
  await page.keyboard.press("Enter"); // sends without waiting
  await expect.poll(() => world.puts.length).toBe(1);
  expect(world.puts[0].body.lines).toEqual([
    { product_id: "pasta", sales_quantity: 5 },
  ]);
  const plus = overview(page).getByRole("button", {
    name: `Increase quantity of ${BACON.name}`,
  });
  await plus.focus();
  await page.keyboard.press("Enter");
  await expect(qty(page, BACON.name)).toHaveValue("3");
});

// --- debounce and the request ---------------------------------------------------------------

test("typing sends one PUT about 600 ms after the last key, with a fresh request id and the CSRF token", async ({
  page,
}) => {
  const world = await open(page);
  const input = qty(page, PASTA.name);
  await input.fill("1");
  await tick(page, 300);
  await input.fill("12");
  await tick(page, 300);
  await input.fill("125");
  await tick(page, 500);
  expect(world.puts).toHaveLength(0); // each key restarted the wait
  await tick(page, 200);
  await expect.poll(() => world.puts.length).toBe(1);
  expect(world.puts[0].body).toEqual({
    request_id: expect.stringMatching(REQUEST_ID),
    lines: [{ product_id: "pasta", sales_quantity: 125 }],
  });
  expect(world.puts[0].csrf).toBe("test-csrf");
  // The line already had 4 and the other line is untouched: only the edited product is sent.
  expect(world.puts[0].body.lines).toHaveLength(1);
});

test("quick clicks on plus and minus are one edit", async ({ page }) => {
  const world = await open(page);
  const plus = overview(page).getByRole("button", {
    name: `Increase quantity of ${PASTA.name}`,
  });
  await plus.click();
  await plus.click();
  await plus.click();
  await expect(qty(page, PASTA.name)).toHaveValue("7");
  await tick(page, 650);
  await expect.poll(() => world.puts.length).toBe(1);
  expect(world.puts[0].body.lines).toEqual([
    { product_id: "pasta", sales_quantity: 7 },
  ]);
  const minus = overview(page).getByRole("button", {
    name: `Decrease quantity of ${PASTA.name}`,
  });
  await expect(qty(page, PASTA.name)).toHaveValue("7");
  await minus.click();
  await expect(qty(page, PASTA.name)).toHaveValue("6");
});

test("minus stops at 0 and plus at 100000; an invalid number is not sent", async ({
  page,
}) => {
  const world = await open(page);
  const input = qty(page, BACON.name);
  const minus = overview(page).getByRole("button", {
    name: `Decrease quantity of ${BACON.name}`,
  });
  await input.fill("0");
  await expect(minus).toBeDisabled();
  await input.fill("100000");
  await expect(
    overview(page).getByRole("button", {
      name: `Increase quantity of ${BACON.name}`,
    }),
  ).toBeDisabled();
  await input.fill("-3");
  await tick(page, 700);
  await input.fill("2.5");
  await tick(page, 700);
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(overview(page)).toContainText(
    "Enter a whole number from 0 to 100000.",
  );
  expect(world.puts.filter((p) => p.body.lines[0].sales_quantity < 0)).toEqual(
    [],
  );
  expect(
    world.puts.filter((p) => !Number.isInteger(p.body.lines[0].sales_quantity)),
  ).toEqual([]);
});

test("while the edit is on its way the card says Updating… and typing is never blocked", async ({
  page,
}) => {
  const world = newCart();
  let release!: () => void;
  world.gate = new Promise<void>((resolve) => (release = resolve));
  await open(page, world);
  const input = qty(page, PASTA.name);
  await expect(updating(page)).toHaveCount(0);
  await input.fill("6");
  await tick(page, 650);
  await expect.poll(() => world.puts.length).toBe(1);
  await expect(updating(page)).toHaveText("Updating…");
  await expect(input).toBeEnabled();
  await input.fill("8"); // typed while the first edit is still in flight
  await tick(page, 650);
  expect(world.puts).toHaveLength(1); // one at a time
  await expect(input).toHaveValue("8");
  release();
  // The first answer must not overwrite what was typed meanwhile; the newer value is sent next.
  await expect.poll(() => world.puts.length).toBe(2);
  expect(world.puts[1].body.lines).toEqual([
    { product_id: "pasta", sales_quantity: 8 },
  ]);
  expect(world.puts[1].body.request_id).not.toBe(world.puts[0].body.request_id);
  await expect(input).toHaveValue("8");
  await expect(updating(page)).toHaveCount(0);
});

test("after the answer the card shows the new revision and total, and Confirm purchase commits that revision", async ({
  page,
}) => {
  const world = await open(page);
  await qty(page, PASTA.name).fill("6");
  await tick(page, 650);
  await expect(overview(page)).toContainText("Revision 2");
  // 6 x 28.50 + 2 x 6.00 + 1 x 10.00 = 193.00
  await expect(overview(page)).toContainText(/193[.,]00/);
  await expect(qty(page, PASTA.name)).toHaveValue("6");
  await overview(page)
    .getByRole("button", { name: "Confirm purchase" })
    .click();
  await expect.poll(() => world.confirmations.length).toBe(1);
  expect(world.confirmations[0]).toMatchObject({ revision: 2 });
});

test("an edit that changes nothing sends nothing", async ({ page }) => {
  const world = await open(page);
  await qty(page, PASTA.name).fill("5");
  await qty(page, PASTA.name).fill("4"); // back to the server value
  await tick(page, 700);
  expect(world.puts).toHaveLength(0);
  await expect(updating(page)).toHaveCount(0);
});

// --- errors: the typed value is kept, the reason is said, the same request id is reused ----------

const failures = [
  {
    code: "ITEM_NOT_IN_CART",
    status: 422,
    server: "That product is not in the cart.",
    shown: "That product is not in the cart.",
  },
  {
    code: "EMPTY_CART",
    status: 422,
    server: "The basket cannot be empty.",
    shown: "The basket cannot be empty.",
  },
  {
    code: "RECIPE_BASKET_LOCKED",
    status: 422,
    server:
      "This basket comes from a saved recipe; change the portions instead.",
    shown:
      "This basket comes from a saved recipe; change the portions instead.",
  },
  {
    code: "CART_QUANTITY_UNKNOWN",
    status: 422,
    server: "This quantity cannot be set exactly in packs for this product.",
    shown: "This quantity cannot be set exactly in packs for this product.",
  },
  {
    code: "CONVERSATION_BUSY",
    status: 409,
    server: "A response is in progress.",
    shown: "A response is in progress.",
  },
  {
    code: "IDEMPOTENCY_CONFLICT",
    status: 409,
    server: "This key already identifies another request.",
    shown:
      "That change was already sent with other settings. Change the number again.",
  },
  {
    code: "INTERNAL",
    status: 500,
    server: "psycopg exploded at line 42",
    shown: "The quantity could not be saved. Try again.",
  },
];

for (const f of failures) {
  test(`${f.code}: the typed value stays, the reason is shown, Try again reuses the request id`, async ({
    page,
  }) => {
    const world = newCart();
    world.failNext = { status: f.status, code: f.code, message: f.server };
    await open(page, world);
    const input = qty(page, PASTA.name);
    await input.fill("9");
    await tick(page, 650);
    await expect.poll(() => world.puts.length).toBe(1);
    const alert = overview(page).getByRole("alert");
    await expect(alert).toContainText(f.shown);
    await expect(alert).not.toContainText("psycopg");
    await expect(input).toHaveValue("9"); // kept
    await expect(input).toHaveAttribute("aria-invalid", "true");
    await expect(updating(page)).toHaveCount(0);
    await overview(page).getByRole("button", { name: "Try again" }).click();
    await expect.poll(() => world.puts.length).toBe(2);
    expect(world.puts[1].body).toEqual(world.puts[0].body); // same request id, same edit
    await expect(alert).toHaveCount(0);
    await expect(input).not.toHaveAttribute("aria-invalid", "true");
    await expect(input).toHaveValue("9");
    await expect(overview(page)).toContainText("Revision 2");
  });
}

test("a new number after an error is a new edit with a new request id", async ({
  page,
}) => {
  const world = newCart();
  world.failNext = { status: 500, code: "INTERNAL", message: "boom" };
  await open(page, world);
  await qty(page, PASTA.name).fill("9");
  await tick(page, 650);
  await expect(overview(page).getByRole("alert")).toBeVisible();
  await qty(page, PASTA.name).fill("10");
  await tick(page, 650);
  await expect.poll(() => world.puts.length).toBe(2);
  expect(world.puts[1].body.request_id).not.toBe(world.puts[0].body.request_id);
  await expect(overview(page).getByRole("alert")).toHaveCount(0);
});

test("emptying the basket is refused: the last line keeps its 0 as typed and is not turned into a ghost", async ({
  page,
}) => {
  const world = newCart({ qty: { pasta: 4, bacon: 0, eggs: 0 } });
  await open(page, world);
  await expect(row(page, "bacon")).toHaveCount(0);
  await qty(page, PASTA.name).fill("0");
  await tick(page, 650);
  await expect(overview(page).getByRole("alert")).toContainText(
    "The basket cannot be empty.",
  );
  await expect(qty(page, PASTA.name)).toHaveValue("0");
  await expect(ghost(page, "pasta")).toHaveCount(0); // the server still has the line
  await expect(row(page, "pasta")).toHaveCount(1);
});

// --- disabled controls ----------------------------------------------------------------------

test("when the conversation says the cart is not editable the controls are disabled with the reason", async ({
  page,
}) => {
  const reason =
    "This basket comes from a saved recipe; change the portions instead.";
  const world = await open(page, newCart({ editable: false, reason }));
  for (const product of [PASTA, BACON]) {
    await expect(qty(page, product.name)).toBeDisabled();
    await expect(
      overview(page).getByRole("button", {
        name: `Increase quantity of ${product.name}`,
      }),
    ).toBeDisabled();
    await expect(
      overview(page).getByRole("button", {
        name: `Decrease quantity of ${product.name}`,
      }),
    ).toBeDisabled();
  }
  await expect(overview(page).getByTestId("cart-edit-reason")).toHaveText(
    reason,
  );
  await expect(qty(page, PASTA.name)).toHaveAccessibleDescription(reason);
  await tick(page, 700);
  expect(world.puts).toHaveLength(0);
});

test("while the assistant is working the controls are disabled with a reason", async ({
  page,
}) => {
  await open(page, newCart({ busy: true }));
  await expect(qty(page, PASTA.name)).toBeDisabled();
  await expect(overview(page).getByTestId("cart-edit-reason")).toHaveText(
    "The assistant is still working on your request.",
  );
});

test("a conversation that does not say anything about editing shows plain quantities, no controls", async ({
  page,
}) => {
  // Older conversations and the specs of the purchase button carry no cart_editable field.
  await open(page, newCart({ legacy: true }));
  await expect(overview(page).getByLabel(/^Quantity of /)).toHaveCount(0);
  await expect(overview(page)).toContainText("4 BAG");
});

// --- the zero ghost line --------------------------------------------------------------------

async function zeroPasta(page: Page, world: CartWorld) {
  await qty(page, PASTA.name).fill("0");
  await tick(page, 650);
  await expect.poll(() => world.puts.length).toBeGreaterThan(0);
  await expect(ghost(page, "pasta")).toBeVisible();
}

test("a line set to 0 stays as a greyed ghost that says what it was; the server basket excludes it", async ({
  page,
}) => {
  const world = await open(page);
  await zeroPasta(page, world);
  expect(world.puts[0].body.lines).toEqual([
    { product_id: "pasta", sales_quantity: 0 },
  ]);
  const g = ghost(page, "pasta");
  await expect(g).toHaveAttribute("data-state", "ghost");
  await expect(g).toContainText("Spaghetti 5 kg");
  await expect(g).toContainText("was 4 BAG");
  await expect(g).toHaveCSS("opacity", "0.5"); // greyed
  await expect(row(page, "pasta")).toHaveCount(0); // a ghost is not a normal line
  await expect(
    g.getByRole("button", { name: "Put Spaghetti 5 kg back" }),
  ).toBeEnabled();
  // The basket is the server's: two lines left, and the total is only bacon and eggs (22.00).
  await expect(overview(page)).toContainText("2 items staged");
  await expect(overview(page)).toContainText(/22[.,]00/);
  await expect(overview(page)).not.toContainText(/114[.,]00/);
  // The other line is a normal line and keeps its controls.
  await expect(qty(page, BACON.name)).toHaveValue("2");
});

test("the ghost stays for 15 seconds", async ({ page }) => {
  const world = await open(page);
  await zeroPasta(page, world);
  await tick(page, 14_000);
  await expect(ghost(page, "pasta")).toHaveAttribute("data-state", "ghost");
  await expect(note(page)).toHaveText("");
});

test("clicking the ghost puts the line back with 1 pack and prepares again", async ({
  page,
}) => {
  const world = await open(page);
  await zeroPasta(page, world);
  await tick(page, 5_000);
  await ghost(page, "pasta")
    .getByRole("button", { name: "Put Spaghetti 5 kg back" })
    .click();
  await expect.poll(() => world.puts.length).toBe(2); // at once, no debounce
  expect(world.puts[1].body.lines).toEqual([
    { product_id: "pasta", sales_quantity: 1 },
  ]);
  expect(world.puts[1].body.request_id).not.toBe(world.puts[0].body.request_id);
  await expect(row(page, "pasta")).toHaveCount(1);
  await expect(qty(page, PASTA.name)).toHaveValue("1");
  await expect(ghost(page, "pasta")).toHaveCount(0);
  await expect(overview(page)).toContainText("3 items staged");
  // The old timer is gone: nothing fades or is announced later.
  await tick(page, 30_000);
  await expect(row(page, "pasta")).toHaveCount(1);
  await expect(note(page)).toHaveText("");
});

test("typing a number above 0 into the ghost puts the line back with that number", async ({
  page,
}) => {
  const world = await open(page);
  await zeroPasta(page, world);
  await qty(page, PASTA.name).fill("3");
  await expect(ghost(page, "pasta")).toHaveCount(0); // it is a line again as soon as it has a number
  await tick(page, 650);
  await expect.poll(() => world.puts.length).toBe(2);
  expect(world.puts[1].body.lines).toEqual([
    { product_id: "pasta", sales_quantity: 3 },
  ]);
  await expect(row(page, "pasta")).toHaveCount(1);
  await tick(page, 30_000);
  await expect(row(page, "pasta")).toHaveCount(1);
});

test("after 15 seconds the ghost fades away and a polite note says it was removed", async ({
  page,
}) => {
  const world = await open(page);
  await zeroPasta(page, world);
  await tick(page, 15_100);
  await expect(ghost(page, "pasta")).toHaveAttribute("data-state", "fading");
  await tick(page, 600);
  await expect(ghost(page, "pasta")).toHaveCount(0);
  await expect(note(page)).toHaveText("Removed Spaghetti 5 kg");
  await expect(note(page)).toHaveAttribute("aria-live", "polite");
  await expect(row(page, "pasta")).toHaveCount(0);
  await expect(overview(page)).toContainText("2 items staged");
});

test("with reduced motion the ghost is removed at 15 seconds without a fade", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const world = await open(page);
  await zeroPasta(page, world);
  await tick(page, 15_100);
  await expect(ghost(page, "pasta")).toHaveCount(0);
  await expect(note(page)).toHaveText("Removed Spaghetti 5 kg");
});

test("two ghosts keep their own timers", async ({ page }) => {
  const world = await open(page);
  await zeroPasta(page, world);
  await tick(page, 8_000);
  await qty(page, BACON.name).fill("0");
  await tick(page, 650);
  await expect(ghost(page, "bacon")).toBeVisible();
  await expect(ghost(page, "pasta")).toHaveAttribute("data-state", "ghost");
  // pasta is 8.65 s old, bacon 0 s: 6.5 s later pasta fades, bacon does not.
  await tick(page, 6_500);
  await expect(ghost(page, "pasta")).toHaveAttribute("data-state", "fading");
  await expect(ghost(page, "bacon")).toHaveAttribute("data-state", "ghost");
  await tick(page, 600);
  await expect(ghost(page, "pasta")).toHaveCount(0);
  await expect(ghost(page, "bacon")).toBeVisible();
  await expect(note(page)).toHaveText("Removed Spaghetti 5 kg");
  await tick(page, 8_000);
  await expect(ghost(page, "bacon")).toHaveAttribute("data-state", "fading");
  await tick(page, 600);
  await expect(note(page)).toHaveText("Removed Diced bacon 1 kg");
});

test("a ghost survives the card reloading the basket after another edit", async ({
  page,
}) => {
  const world = await open(page);
  await zeroPasta(page, world);
  const reads = world.conversationReads;
  await qty(page, EGGS.name).fill("2");
  await tick(page, 650);
  await expect.poll(() => world.puts.length).toBe(2);
  await expect.poll(() => world.conversationReads).toBeGreaterThan(reads);
  await expect(overview(page)).toContainText("Revision 3");
  await expect(ghost(page, "pasta")).toHaveAttribute("data-state", "ghost");
  await expect(qty(page, EGGS.name)).toHaveValue("2");
});

test("on a phone the controls fit the card and nothing scrolls sideways", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page);
  await expect(qty(page, PASTA.name)).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
