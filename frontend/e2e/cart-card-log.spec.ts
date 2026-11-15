import { expect, test, type Page } from "@playwright/test";
import { newCart, openCart, type CartWorld } from "./support/cartFixtures";

// SPEC (written before the code). State logging for diagnosing the cart card, ACTIVE ONLY IN DEBUG
// MODE (?debug=1, remembered in the browser): every decision about the card is logged to the console
// and kept in window.__aimoCardLog (last 200 entries); the card has a "Copy card log" action. Never
// customer message text, item names, tokens or cookies. Mocked API; the clipboard is stubbed.

type Entry = Record<string, unknown> & { kind: string; t: string };
const card = (page: Page) =>
  page.locator("aside#overview, aside[aria-label='Your order']").first();
const log = (page: Page) =>
  page.evaluate(
    () =>
      (window as unknown as { __aimoCardLog?: Entry[] }).__aimoCardLog ?? null,
  );
const copyLog = (page: Page) =>
  card(page).getByRole("button", { name: /^Cop(y|ied) card log$/ });

async function stubClipboard(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __copied: string[] };
    w.__copied = [];
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: (text: string) => {
          w.__copied.push(text);
          return Promise.resolve();
        },
      },
    });
  });
}
const copied = (page: Page) =>
  page.evaluate(() => (window as unknown as { __copied: string[] }).__copied);

async function open(page: Page, over: Partial<CartWorld> = {}, debug = true) {
  if (debug)
    await page.addInitScript(() => localStorage.setItem("aimo.debug", "1"));
  const world = newCart({ stream: true, ...over });
  await openCart(page, world);
  await expect(card(page)).toBeVisible();
  return world;
}

test("outside debug mode nothing is logged and there is no Copy card log action", async ({
  page,
}) => {
  const messages: string[] = [];
  page.on("console", (m) => messages.push(m.text()));
  await open(page, { view: "prepared" }, false);
  await expect(card(page).getByTestId("card-total-row")).toBeVisible();
  expect(await log(page)).toBeNull();
  await expect(copyLog(page)).toHaveCount(0);
  expect(messages.filter((m) => m.includes("[aimo-card]"))).toEqual([]);
});

test("in debug mode the card logs which component it chose and why, to the console and window.__aimoCardLog", async ({
  page,
}) => {
  const messages: string[] = [];
  page.on("console", (m) => messages.push(m.text()));
  await open(page, { view: "prepared" });
  await expect
    .poll(async () =>
      ((await log(page)) ?? []).some(
        (e) => e.kind === "card" && e.chosen === "prepared",
      ),
    )
    .toBe(true);
  const entries = (await log(page))!;
  const chose = entries.filter((e) => e.kind === "card");
  expect(chose.length).toBeGreaterThan(0);
  const last = chose.at(-1)!;
  expect(last).toMatchObject({
    chosen: "prepared",
    why: expect.stringMatching(/\w/),
    conversation: expect.stringMatching(/^[0-9a-f-]{36}$/),
    hasDraftCart: true,
    purchases: 1,
    busy: false,
    cartEditable: true,
    notIncluded: 0,
    basket: {
      id: expect.stringMatching(/^[0-9a-f-]{36}$/),
      revision: 1,
      status: expect.any(String),
    },
  });
  expect(last.t).toMatch(/^\d{4}-\d\d-\d\dT/);
  expect(messages.some((m) => m.includes("[aimo-card]"))).toBe(true);
});

test("each state change adds a decision: empty, draft, unmatched, prepared", async ({
  page,
}) => {
  const world = await open(page, { view: "empty" });
  const chosen = async () =>
    ((await log(page)) ?? [])
      .filter((e) => e.kind === "card")
      .map((e) => e.chosen);
  await expect.poll(chosen).toContain("empty");
  world.view = "draft";
  await expect.poll(chosen).toContain("draft");
  world.view = "unmatched";
  await expect
    .poll(async () =>
      ((await log(page)) ?? []).some(
        (e) => e.kind === "card" && e.chosen === "draft" && e.notIncluded === 1,
      ),
    )
    .toBe(true);
  world.view = "prepared";
  await expect.poll(chosen).toContain("prepared");
  // A decision is logged when it changes, not on every render.
  const count = ((await log(page)) ?? []).length;
  await page.waitForTimeout(800);
  expect(((await log(page)) ?? []).length).toBe(count);
});

test("it logs why the card is open or collapsed: default, stored preference, user toggle", async ({
  page,
}) => {
  await open(page, { view: "draft" });
  const opens = async () =>
    ((await log(page)) ?? []).filter((e) => e.kind === "open");
  await expect
    .poll(async () => (await opens()).map((e) => e.why))
    .toContain("default");
  expect((await opens())[0]).toMatchObject({ open: true });
  await card(page).getByRole("button", { name: "Collapse cart" }).click();
  await expect
    .poll(async () => (await opens()).map((e) => e.why))
    .toContain("user toggle");
  expect((await opens()).at(-1)).toMatchObject({
    open: false,
    why: "user toggle",
  });
  await page.reload();
  await expect
    .poll(async () => (await opens()).map((e) => e.why))
    .toContain("stored preference");
  expect((await opens()).at(-1)).toMatchObject({ open: false });
});

test("it logs what decides the purchase button in each state", async ({
  page,
}) => {
  const world = await open(page, { view: "draft", busy: true });
  const button = async () =>
    ((await log(page)) ?? []).filter((e) => e.kind === "button");
  await expect
    .poll(async () => (await button()).map((e) => e.reason))
    .toContain("assistant working");
  world.busy = false;
  await expect
    .poll(async () => (await button()).map((e) => e.enabled))
    .toContain(true);
  world.view = "prepared";
  world.orderPlaced = true;
  world.editable = false;
  await expect
    .poll(async () => (await button()).map((e) => e.reason))
    .toContain("order placed");
  expect((await button()).at(-1)).toMatchObject({ enabled: false });
});

test("Copy card log copies the last entries as text: ids and states, never message text, tokens or item names", async ({
  page,
}) => {
  await stubClipboard(page);
  await open(page, { view: "unmatched" });
  await expect(copyLog(page)).toBeVisible();
  await copyLog(page).click();
  const text = (await copied(page))[0];
  expect(text).toContain("fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae");
  expect(text).toMatch(/chosen/);
  expect(text).toMatch(/cartEditable/);
  expect(text).toMatch(/busy/);
  expect(text).not.toContain("Here is your basket."); // the assistant's message text
  expect(text).not.toContain("test-csrf");
  expect(text).not.toMatch(/Unobtainium|Spaghetti|Diced bacon/); // no item names
  expect(text).not.toMatch(/aimo_session|cookie/i);
  await expect(copyLog(page)).toHaveText("Copied card log");
});
