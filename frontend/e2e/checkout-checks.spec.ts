import { expect, test, type Page } from "@playwright/test";
import {
  newCart,
  openCart,
  proposalOf,
  type CartWorld,
} from "./support/cartFixtures";
import { ids, json, problem } from "./support/schedulerFixtures";
import type { Proposal } from "../src/shared/api/types";

// SPEC (written before the build). The Checks tab groups the purchasing checks by what the customer can do:
//  - "Cannot order yet" (blockers: QUANTITY_UNRESOLVED, TOTAL_UNRESOLVED, CUTOFF_PASSED),
//    first, with "What you can do: choose another product or ask the assistant.";
//  - "Needs your approval" (exceptions: SUBSTITUTION_REQUIRES_APPROVAL, OVERBUY_REQUIRES_APPROVAL, UNVERIFIED_STOCK),
//    with "What you can do: approve below.";
//  - "Good to know" (warnings: VARIABLE_WEIGHT_UNRESOLVED), with "What you can do: nothing; the amount is an estimate.";
//  - "Expired" (the approval ran out) with a Refresh button.
// Each code gets a short human text; the code stays as a small label. The class comes from the proposal's
// `reason_classes` when the server sends it, else from one table in the UI. Mocked API, typed fixtures.

const card = (page: Page) =>
  page.locator("aside#overview, aside[aria-label='Your order']").first();
const checks = (page: Page) =>
  card(page).locator('[data-testid="card-panel-checks"]');
const group = (page: Page, name: string) =>
  checks(page).getByRole("group", { name });

type Reason = Proposal["reasons"][number];
const reason = (
  code: string,
  severity: Reason["severity"],
  message = `server text for ${code}`,
  product_id: string | null = "pasta",
): Reason => ({ code, message, severity, product_id });

async function open(page: Page, over: Partial<CartWorld>) {
  const world = newCart({ stream: true, ...over });
  await openCart(page, world);
  await expect(card(page)).toBeVisible();
  await card(page)
    .getByRole("tab", { name: /^Checks/ })
    .click();
  return world;
}

const ALL: Reason[] = [
  reason("VARIABLE_WEIGHT_UNRESOLVED", "warning"),
  reason("SUBSTITUTION_REQUIRES_APPROVAL", "exception"),
  reason("UNVERIFIED_STOCK", "exception"),
  reason("QUANTITY_UNRESOLVED", "unresolved"),
  reason("OVERBUY_REQUIRES_APPROVAL", "exception", undefined, "bacon"),
  reason("TOTAL_UNRESOLVED", "unresolved", undefined, null),
];

test("blockers come first, then approvals, then warnings, each with a plain heading", async ({
  page,
}) => {
  await open(page, { reasons: ALL, outcome: "needs_resolution" });
  const headings = await checks(page)
    .getByRole("group")
    .evaluateAll((els) => els.map((el) => el.getAttribute("aria-label")));
  expect(headings).toEqual([
    "Cannot order yet",
    "Needs your approval",
    "Good to know",
  ]);
});

test("each group says what the customer can do", async ({ page }) => {
  await open(page, { reasons: ALL, outcome: "needs_resolution" });
  await expect(group(page, "Cannot order yet")).toContainText(
    "What you can do: choose another product or ask the assistant.",
  );
  await expect(group(page, "Needs your approval")).toContainText(
    "What you can do: approve below.",
  );
  await expect(group(page, "Good to know")).toContainText(
    "What you can do: nothing, the amount is an estimate.",
  );
});

test("each code has a short human text and keeps its code as a small label", async ({
  page,
}) => {
  await open(page, { reasons: ALL, outcome: "needs_resolution" });
  const blockers = group(page, "Cannot order yet");
  await expect(blockers).toContainText("No pack size");
  await expect(blockers).toContainText("QUANTITY_UNRESOLVED");
  await expect(blockers).toContainText("Total unknown");
  // Q-134 (b): unconfirmed stock is something the customer can approve, not a blocker.
  await expect(group(page, "Needs your approval")).toContainText(
    "Stock not confirmed by the supplier. Approve to order anyway.",
  );
  await expect(group(page, "Needs your approval")).toContainText(
    "UNVERIFIED_STOCK",
  );
  await expect(blockers).not.toContainText("UNVERIFIED_STOCK");
  await expect(group(page, "Needs your approval")).toContainText(
    "Substitute product",
  );
  await expect(group(page, "Needs your approval")).toContainText(
    "Pack larger than needed",
  );
  await expect(group(page, "Good to know")).toContainText("Weight varies");
  // Not the server's wall of text.
  await expect(checks(page)).not.toContainText("server text for");
});

test("a line's product name is shown with its check", async ({ page }) => {
  await open(page, { reasons: ALL, outcome: "needs_resolution" });
  await expect(group(page, "Cannot order yet")).toContainText("Spaghetti");
});

test("groups with nothing in them are not shown", async ({ page }) => {
  await open(page, {
    reasons: [reason("SUBSTITUTION_REQUIRES_APPROVAL", "exception")],
    outcome: "approval_required",
  });
  await expect(group(page, "Needs your approval")).toBeVisible();
  await expect(group(page, "Cannot order yet")).toHaveCount(0);
  await expect(group(page, "Good to know")).toHaveCount(0);
});

test("the old flat sentence is gone", async ({ page }) => {
  await open(page, { reasons: ALL, outcome: "needs_resolution" });
  await expect(checks(page)).not.toContainText(
    "This purchase cannot be approved. Resolve the purchasing checks below.",
  );
});

test("reason_classes from the server wins over the built-in table", async ({
  page,
}) => {
  await open(page, {
    reasons: [reason("UNVERIFIED_STOCK", "exception")],
    reasonClasses: { UNVERIFIED_STOCK: "warning" },
    outcome: "ready_to_commit",
  });
  await expect(group(page, "Good to know")).toContainText(
    "Stock not confirmed",
  );
  await expect(group(page, "Cannot order yet")).toHaveCount(0);
});

test("an unknown code falls back to its severity and the server's text", async ({
  page,
}) => {
  await open(page, {
    reasons: [
      reason("BRAND_NEW_CODE", "unresolved", "Something new happened."),
    ],
    outcome: "needs_resolution",
  });
  await expect(group(page, "Cannot order yet")).toContainText(
    "Something new happened.",
  );
});

test("a denied order with no listed reason still says it cannot be ordered", async ({
  page,
}) => {
  await open(page, { reasons: [], outcome: "denied" });
  await expect(group(page, "Cannot order yet")).toBeVisible();
  await expect(group(page, "Cannot order yet")).toContainText(
    "What you can do: choose another product or ask the assistant.",
  );
});

test("an expired approval has an Expired group; Refresh asks the server to prepare the basket again", async ({
  page,
}) => {
  const bodies: Record<string, unknown>[] = [];
  const csrf: (string | undefined)[] = [];
  const world = await open(page, { expired: true, reasons: [] });
  await page.route(
    `**/api/conversations/${ids.conversation}/refresh-basket`,
    (route) => {
      bodies.push(route.request().postDataJSON());
      csrf.push(route.request().headers()["x-csrf-token"]);
      world.expired = false; // the fresh basket is not expired
      return json(route, { proposal: proposalOf(world), not_included: [] });
    },
  );
  const expired = group(page, "Expired");
  await expect(expired).toBeVisible();
  await expect(expired).toContainText("This approval expired.");
  await expired.getByRole("button", { name: "Refresh" }).click();
  await expect(group(page, "Expired")).toHaveCount(0);
  expect(bodies).toEqual([{ request_id: expect.stringMatching(/^.{8,120}$/) }]);
  expect(csrf).toEqual(["test-csrf"]);
});

test("a refused refresh shows the server's message in the group and Refresh works again", async ({
  page,
}) => {
  await open(page, { expired: true, reasons: [] });
  await page.route(
    `**/api/conversations/${ids.conversation}/refresh-basket`,
    (route) =>
      problem(route, 409, "BASKET_NOT_EXPIRED", "This basket has not expired."),
  );
  const expired = group(page, "Expired");
  await expired.getByRole("button", { name: "Refresh" }).click();
  await expect(expired.getByRole("alert")).toHaveText(
    "This basket has not expired.",
  );
  await expect(expired.getByRole("button", { name: "Refresh" })).toBeEnabled();
});

test("a live basket has no Expired group and no Refresh button", async ({
  page,
}) => {
  await open(page, { reasons: [] });
  await expect(group(page, "Expired")).toHaveCount(0);
  await expect(
    checks(page).getByRole("button", { name: "Refresh" }),
  ).toHaveCount(0);
});
