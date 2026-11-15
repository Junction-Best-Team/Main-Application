import { expect, test, type Page } from "@playwright/test";
import type { Conversation, Session } from "../src/shared/api/types";

const session: Session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf",
  role: "approver",
  scheduler_demo_mode: false,
};
const conversationId = "fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";
const proposalId = "b7b7dc8d-8e75-4f79-ac23-649ed1e5fd96";
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

async function mockSession(page: Page) {
  await page.route("**/api/session", (route) =>
    route.fulfill({ status: 200, json: session }),
  );
  await page.route("**/api/login", (route) => route.fulfill({ json: session }));
  await page.route("**/api/logout", (route) => route.fulfill({ status: 204 }));
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
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({
      json: {
        recipe_basis: "saved_recipe",
        proposal_id: proposalId,
        revision: 1,
        fingerprint: "a".repeat(64),
        current_revision: 1,
        committed_revision: null,
        current_proposal_url: `/purchases/${proposalId}`,
        policy_version: 1,
        policy_outcome: "auto_approved",
        approval_status: "not_required",
        order_status: "not_placed",
        reasons: [],
        expires_at: "2099-11-15T12:00:00Z",
        next_action: { type: "confirm" },
        approval_id: null,
        approval_url: null,
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
              },
              net: "40.00",
              gross: "49.60",
              vat_rate: "0.24",
            },
          ],
          currency: "EUR",
          net_total: "40.00",
          gross_total: "49.60",
          observed_at: timestamp,
        },
      },
    }),
  );
  await page.route("**/api/purchases?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
  await page.route("**/api/orders?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
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

const catalogPlan = {
  title: "Carbonara",
  portions: 200,
  recipe_id: "unitools:carbonara",
  recipe_version: "1",
  instructions: ["Boil the pasta.", "Toss with egg and cheese."],
  ingredients: [
    {
      name: "Dry spaghetti",
      amount: "20",
      unit: "KG",
      status: "matched" as const,
      product_id: "pasta",
      conversion: {
        sales_quantity: "7",
        sales_unit: "ST",
        excess: "1",
      },
    },
    {
      name: "Eggs",
      amount: "120",
      unit: "piece",
      status: "matched" as const,
      product_id: "egg-tray",
    },
  ],
  notes: ["Recipe quantities are estimates."],
};

test("catalog recipe opens near-fullscreen overlay with ingredients then steps", async ({
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
            text: "Here is carbonara for 200 portions.",
            created_at: timestamp,
            proposal_id: proposalId,
            meal_plan: catalogPlan,
          },
        ],
        purchases: [
          {
            recipe_basis: "saved_recipe",
            proposal_id: proposalId,
            revision: 1,
            fingerprint: "a".repeat(64),
            current_revision: 1,
            committed_revision: null,
            current_proposal_url: `/purchases/${proposalId}`,
            policy_version: 1,
            policy_outcome: "auto_approved",
            approval_status: "not_required",
            order_status: "not_placed",
            reasons: [],
            expires_at: "2099-11-15T12:00:00Z",
            next_action: { type: "confirm" },
            approval_id: null,
            approval_url: null,
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
                  },
                  net: "40.00",
                  gross: "49.60",
                  vat_rate: "0.24",
                },
              ],
              currency: "EUR",
              net_total: "40.00",
              gross_total: "49.60",
              observed_at: timestamp,
            },
          },
        ],
      },
    }),
  );
  await page.goto(`/conversations/${conversationId}`);

  const log = page.getByRole("log", { name: "Conversation messages" });
  await expect(
    page.getByRole("button", { name: "Open recipe Carbonara" }),
  ).toBeVisible();
  await expect(log.getByText("Dry spaghetti", { exact: true })).toHaveCount(0);
  await expect(log.getByText("Boil the pasta.", { exact: true })).toHaveCount(
    0,
  );

  await page.getByRole("button", { name: "Open recipe Carbonara" }).click();
  const overlay = page.getByRole("dialog", { name: "Carbonara" });
  await expect(overlay).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.body.style.overflow))
    .toBe("hidden");

  const box = await overlay.boundingBox();
  const viewport = page.viewportSize();
  expect(box && viewport).toBeTruthy();
  if (box && viewport) {
    expect(box.width / viewport.width).toBeGreaterThan(0.6);
    expect(box.height / viewport.height).toBeGreaterThan(0.7);
  }

  const ingredients = overlay.getByRole("region", { name: "Ingredients" });
  const steps = overlay.getByRole("region", { name: "Cooking steps" });
  await expect(ingredients.getByText("Dry spaghetti")).toBeVisible();
  await expect(ingredients.getByText("20 KG", { exact: true })).toBeVisible();
  await expect(ingredients.getByText("Buy 7 ST", { exact: false })).toHaveCount(
    0,
  );
  await expect(steps.getByText("Boil the pasta.")).toBeVisible();
  await expect(steps.getByText("Toss with egg and cheese.")).toBeVisible();

  const ingredientBox = await ingredients.boundingBox();
  const stepsBox = await steps.boundingBox();
  expect(ingredientBox && stepsBox && ingredientBox.y < stepsBox.y).toBeTruthy();

  await expect(
    overlay.getByRole("button", { name: "Download PDF" }),
  ).toBeVisible();
  await expect(
    overlay.getByRole("button", { name: "Open basket" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Review basket to confirm" }),
  ).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(overlay).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Open recipe Carbonara" }),
  ).toBeVisible();
});

test("free-form meal plan still opens overlay with empty steps", async ({
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
            text: "Here is a free-form plan.",
            created_at: timestamp,
            meal_plan: {
              title: "Market stew",
              portions: 40,
              ingredients: [
                {
                  name: "Carrots",
                  amount: "5",
                  unit: "KG",
                  status: "proposed",
                },
              ],
            },
          },
        ],
      },
    }),
  );
  await page.goto(`/conversations/${conversationId}`);
  await page.getByRole("button", { name: "Open recipe Market stew" }).click();
  const overlay = page.getByRole("dialog", { name: "Market stew" });
  await expect(overlay).toBeVisible();
  await expect(overlay.getByText("Carrots")).toBeVisible();
  await expect(overlay.getByText("No cooking steps in this plan.")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(overlay).toHaveCount(0);
});
