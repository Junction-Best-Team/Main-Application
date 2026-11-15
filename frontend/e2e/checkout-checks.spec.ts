import { expect, test, type Page } from "@playwright/test";
import { newCart, openCart, type CartWorld } from "./support/cartFixtures";
import type { Proposal } from "../src/shared/api/types";

// SPEC (written before the build). The Checks tab groups the purchasing checks by what the customer can do:
//  - "Cannot order yet" (blockers: UNVERIFIED_STOCK, QUANTITY_UNRESOLVED, TOTAL_UNRESOLVED, CUTOFF_PASSED),
//    first, with "What you can do: choose another product or ask the assistant.";
//  - "Needs your approval" (exceptions: SUBSTITUTION_REQUIRES_APPROVAL, OVERBUY_REQUIRES_APPROVAL),
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
  reason("UNVERIFIED_STOCK", "unresolved"),
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
  await expect(blockers).toContainText("Stock not confirmed");
  await expect(blockers).toContainText("UNVERIFIED_STOCK");
  await expect(blockers).toContainText("Total unknown");
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
    reasons: [reason("UNVERIFIED_STOCK", "unresolved")],
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

test("an expired approval has an Expired group with a Refresh button that asks for the basket again", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (r) => {
    if (/\/api\/purchases\/[^/]+$/.test(new URL(r.url()).pathname))
      requests.push(r.url());
  });
  await open(page, { expired: true, reasons: [] });
  const expired = group(page, "Expired");
  await expect(expired).toBeVisible();
  await expect(expired).toContainText("This approval expired.");
  const before = requests.length;
  await expired.getByRole("button", { name: "Refresh" }).click();
  await expect.poll(() => requests.length).toBeGreaterThan(before);
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
