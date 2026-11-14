import { expect, test, type Page } from "@playwright/test";
import type { Proposal } from "../src/shared/api/types";

const session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf",
};

function acceptedOrder(
  overrides: Partial<Proposal> & {
    proposal_id: string;
    order_id: string;
    request_id: string;
    placed_at: string;
    gross_total: string;
  },
): Proposal {
  const { proposal_id, order_id, request_id, placed_at, gross_total, ...rest } =
    overrides;
  return {
    recipe_basis: "free_form",
    proposal_id,
    revision: 1,
    fingerprint: "a".repeat(64),
    current_revision: 1,
    committed_revision: 1,
    current_proposal_url: `/purchases/${proposal_id}`,
    policy_version: 1,
    policy_outcome: "ready_to_commit",
    approval_status: "approved",
    order_status: "accepted_mock",
    reasons: [],
    expires_at: "2099-11-15T12:00:00Z",
    next_action: { type: "wait" },
    approval_id: null,
    approval_url: null,
    order_id,
    buyer_id: "demo-hotel",
    agent_id: "internal-demo-hotel",
    request: {
      request_id,
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
          gross: gross_total,
          tax: "14.00",
          deposits_gross: "0",
          deposit_lines: [],
          product_evidence: {},
          commercial_evidence: {},
        },
      ],
      currency: "EUR",
      net_total: "100.00",
      gross_total,
      tax_total: "14.00",
      deposits_gross: "0",
      charges_gross: "0",
      charges_basis: "demo",
      mode: "fixture",
      observed_at: placed_at,
      reasons: [],
    },
    history: [
      {
        event: "purchase_confirmed",
        created_at: placed_at,
        actor: "buyer",
        detail: {},
      },
    ],
    can_decide: false,
    ...rest,
  };
}

async function mockSession(page: Page) {
  await page.route("**/api/session", (route) =>
    route.fulfill({ status: 200, json: session }),
  );
  await page.route("**/api/login", (route) => route.fulfill({ json: session }));
  await page.route("**/api/logout", (route) => route.fulfill({ status: 204 }));
  await page.route("**/api/conversations*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
}

test("Past Orders search, period, sort and status filter loaded accepted orders", async ({
  page,
}) => {
  await mockSession(page);
  const recent = acceptedOrder({
    proposal_id: "recent-order",
    order_id: "VA-1001",
    request_id: "Carbonara for 200",
    placed_at: new Date().toISOString(),
    gross_total: "114.00",
  });
  const older = acceptedOrder({
    proposal_id: "older-order",
    order_id: "VA-2002",
    request_id: "Weekend tasting cheeses",
    placed_at: new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString(),
    gross_total: "382.00",
  });
  const ancient = acceptedOrder({
    proposal_id: "ancient-order",
    order_id: "VA-3003",
    request_id: "Spring pantry restock",
    placed_at: new Date(Date.now() - 120 * 24 * 60 * 60 * 1000).toISOString(),
    gross_total: "50.00",
  });
  await page.route("**/api/purchases?*", (route) =>
    route.fulfill({
      json: { items: [recent, older, ancient], next_offset: null },
    }),
  );
  await page.goto("/purchases");
  await expect(
    page.getByRole("heading", { name: "Past Orders" }),
  ).toBeVisible();
  const rows = page.locator(".purchase-row");
  // Default period is last 90 days: recent + older, newest first.
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("VA-1001");
  await expect(rows.nth(1)).toContainText("VA-2002");

  await page.getByLabel("Period").selectOption("all");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(2)).toContainText("VA-3003");

  await page.getByLabel("Sort").selectOption("total_desc");
  await expect(rows.nth(0)).toContainText("VA-2002");
  await expect(rows.nth(1)).toContainText("VA-1001");
  await expect(rows.nth(2)).toContainText("VA-3003");

  await page.getByLabel("Search past orders").fill("VA-3003");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("Spring pantry restock");

  await page.getByLabel("Search past orders").fill("no-such-order");
  await expect(rows).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "No matching past orders" }),
  ).toBeVisible();

  await page.getByLabel("Search past orders").fill("");
  await page.getByLabel("Period").selectOption("7d");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("VA-1001");

  await page.getByLabel("Period").selectOption("all");
  await page.getByLabel("Status").selectOption("accepted_mock");
  await expect(rows).toHaveCount(3);
});
