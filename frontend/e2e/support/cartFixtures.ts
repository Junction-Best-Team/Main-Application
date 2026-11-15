import type { Page } from "@playwright/test";
import type { components } from "../../src/shared/api/schema";
import type { Conversation, Proposal } from "../../src/shared/api/types";
import { proposal as baseProposal } from "./proposalFixture";
import { ids, json, mockSignedIn, problem } from "./schedulerFixtures";

// Typed fixtures and a stateful mock of PUT /api/conversations/{id}/cart for the quantity-control
// specs (cart-quantity.spec.ts). The shapes come from the generated schema (a7's contract on
// p3/cart-purchase-button, commit a802d54). Everything is mock data.

export type CartEditRequest = components["schemas"]["CartEditRequest"];
export type CartPurchaseResponse =
  components["schemas"]["CartPurchaseResponse"];
export type CartNotIncluded = components["schemas"]["CartNotIncluded"];

export const CART_URL = `**/api/conversations/${ids.conversation}/cart`;
const timestamp = "2026-11-14T10:00:00+02:00";

export type Product = {
  id: string;
  name: string;
  salesUnit: string;
  unitGross: number; // EUR incl. VAT per sales unit
  unit: string; // the recipe unit of the cart item
  amountPerPack: number;
};
export const PASTA: Product = {
  id: "pasta",
  name: "Spaghetti 5 kg",
  salesUnit: "BAG",
  unitGross: 28.5,
  unit: "KG",
  amountPerPack: 5,
};
export const BACON: Product = {
  id: "bacon",
  name: "Diced bacon 1 kg",
  salesUnit: "ST",
  unitGross: 6,
  unit: "KG",
  amountPerPack: 1,
};
export const EGGS: Product = {
  id: "eggs",
  name: "Eggs 30 pcs",
  salesUnit: "TRAY",
  unitGross: 10,
  unit: "piece",
  amountPerPack: 30,
};
export const PRODUCTS = [PASTA, BACON, EGGS];

export type Put = {
  body: CartEditRequest;
  csrf: string | undefined;
};
export type CartWorld = {
  qty: Record<string, number>;
  revision: number;
  puts: Put[];
  confirmations: Record<string, unknown>[];
  failNext: { status: number; code: string; message: string } | null;
  /** While set, the PUT answer waits for this promise (to test "Updating…" and typing meanwhile). */
  gate: Promise<void> | null;
  editable: boolean;
  reason: string | null;
  busy: boolean;
  orderPlaced: boolean;
  /** An older conversation: no cart_editable / cart_edit_reason fields at all. */
  legacy: boolean;
  /** What the conversation holds: nothing, a draft cart, a draft with an unmatched item, or a prepared basket. */
  view: "empty" | "draft" | "unmatched" | "prepared";
  /** The prepared basket's policy outcome (default ready_to_commit) and whether it has expired. */
  outcome:
    "ready_to_commit" | "approval_required" | "denied" | "needs_resolution";
  expired: boolean;
  /** Serve the conversation snapshot on the SSE stream too (reconnects every 300 ms) so a state change shows at once. */
  stream: boolean;
  /** Items without a product or quantity, listed by the conversation as `cart_not_included` (reason no_product / no_quantity). */
  unmatched: CartNotIncluded[];
  /** Like the real backend: an edit prepares a NEW proposal (new id, revision 1) and cancels the older one. */
  renew: boolean;
  /** How many times the proposal was renewed (0: the original id). */
  seq: number;
  /** The cancelled proposals, oldest first. */
  old: Proposal[];
  conversationReads: number;
};
export const newCart = (over: Partial<CartWorld> = {}): CartWorld => ({
  qty: { pasta: 4, bacon: 2, eggs: 1 },
  revision: 1,
  puts: [],
  confirmations: [],
  failNext: null,
  gate: null,
  editable: true,
  reason: null,
  busy: false,
  orderPlaced: false,
  legacy: false,
  view: "prepared",
  outcome: "ready_to_commit",
  expired: false,
  stream: false,
  unmatched: [],
  renew: true,
  seq: 0,
  old: [],
  conversationReads: 0,
  ...over,
});

const money = (n: number) => n.toFixed(2);
/** The current proposal's id: the original, or a new one after each edit (`renew`). */
export const proposalIdOf = (w: CartWorld) =>
  w.seq === 0
    ? ids.proposal
    : `${ids.proposal.slice(0, -3)}${String(w.seq).padStart(3, "0")}`;

export function proposalOf(w: CartWorld): Proposal {
  const lines = PRODUCTS.filter((p) => w.qty[p.id] > 0).map((p) => {
    const q = w.qty[p.id];
    const gross = p.unitGross * q;
    const net = gross / 1.14;
    return {
      product_id: p.id,
      name: p.name,
      quantity: {
        requested_amount: String(q * p.amountPerPack),
        requested_unit: p.unit,
        sales_unit: p.salesUnit,
        sales_quantity: String(q),
        proposed_amount: String(q * p.amountPerPack),
        excess: "0",
        status: "known" as const,
        basis: ["catalog"],
        source_step: "1",
      },
      substitutes_for: null,
      net: money(net),
      gross: money(gross),
      tax: money(gross - net),
      deposits_gross: "0",
      deposit_lines: [],
      product_evidence: {},
      commercial_evidence: {},
    };
  });
  const gross = lines.reduce((sum, l) => sum + Number(l.gross), 0);
  const net = lines.reduce((sum, l) => sum + Number(l.net), 0);
  return {
    ...baseProposal,
    proposal_id: proposalIdOf(w),
    revision: w.revision,
    current_revision: w.revision,
    committed_revision: w.orderPlaced ? w.revision : null,
    policy_outcome: w.outcome,
    expires_at: w.expired ? "2020-01-01T00:00:00Z" : baseProposal.expires_at,
    approval_status: w.orderPlaced ? "approved" : "not_required",
    order_status: w.orderPlaced ? "accepted_mock" : "not_placed",
    order_id: w.orderPlaced ? ids.sourceOrder : null,
    approval_id: null,
    approval_url: null,
    next_action: { type: w.orderPlaced ? "complete" : "commit" },
    can_decide: false,
    request: { ...baseProposal.request, delivery_date: "2026-11-17" },
    snapshot: {
      ...baseProposal.snapshot,
      lines,
      gross_total: money(gross),
      net_total: money(net),
      tax_total: money(gross - net),
    },
  };
}

export const notIncludedOf = (w: CartWorld): CartNotIncluded[] =>
  PRODUCTS.filter((p) => w.qty[p.id] === 0).map((p) => ({
    name: p.name,
    amount: null,
    unit: p.unit,
    reason: "removed" as const,
  }));

export function conversationOf(w: CartWorld): Conversation {
  const p = proposalOf(w);
  const prepared = w.view === "prepared";
  const items = PRODUCTS.map((x) => ({
    name: x.name,
    amount: String(w.qty[x.id] * x.amountPerPack),
    unit: x.unit,
    product_id: x.id,
    product_name: x.name,
    matched: true,
  }));
  if (w.view === "unmatched")
    items.push({
      name: "Unobtainium",
      amount: "3",
      unit: "kg",
      product_id: undefined as unknown as string,
      product_name: undefined as unknown as string,
      matched: false,
    });
  return {
    id: ids.conversation,
    title: "Carbonara for 200",
    created_at: timestamp,
    updated_at: timestamp,
    busy: w.busy,
    purchases: prepared ? [...w.old, p] : [],
    messages:
      w.view === "empty"
        ? []
        : [
            {
              id: 1,
              role: "assistant",
              text: "Here is your basket.",
              created_at: timestamp,
              ...(prepared ? { proposal_id: p.proposal_id } : {}),
            },
          ],
    ...(w.view === "empty"
      ? {}
      : {
          draft_cart: {
            turn_id: "turn-1",
            title: "Carbonara for 200",
            items,
            proposal_id: prepared ? p.proposal_id : null,
          },
        }),
    ...(w.legacy
      ? {}
      : {
          cart_editable: w.editable,
          cart_edit_reason: w.reason,
          // What the current basket leaves out, computed by the server on every read (empty until a basket exists).
          cart_not_included: prepared
            ? [...w.unmatched, ...notIncludedOf(w)]
            : [],
        }),
  } as Conversation;
}

/** Signs in, mocks the conversation, the purchase, the confirm and the stateful PUT .../cart route. */
export async function openCart(page: Page, w: CartWorld) {
  // A paused page clock: no timer fires unless a spec runs it (page.clock.runFor).
  await page.clock.install({ time: new Date("2026-11-14T08:00:00Z") });
  await page.clock.pauseAt(new Date("2026-11-14T08:00:01Z"));
  await mockSignedIn(page);
  await page.route("**/api/settings/policy", (route) =>
    json(route, {
      buyer_id: "demo-hotel",
      policy_version: 1,
      rules: { currency: "EUR", destinations: ["hotel-helsinki"] },
      can_edit: true,
      approval_authority: { can_approve: true },
      history: [],
    }),
  );
  await page.route(`**/api/conversations/${ids.conversation}`, (route) => {
    w.conversationReads += 1;
    return json(route, conversationOf(w));
  });
  await page.route(`**/api/conversations/${ids.conversation}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: w.stream
        ? `retry: 300\nevent: conversation\ndata: ${JSON.stringify(conversationOf(w))}\n\n`
        : ": heartbeat\n\n",
    }),
  );
  await page.route(`**/api/purchases/*`, (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-1);
    const found = [...w.old, proposalOf(w)].find((x) => x.proposal_id === id);
    return found
      ? json(route, found)
      : problem(route, 404, "NOT_FOUND", "Not found.");
  });
  await page.route(`**/api/purchases/*/confirm`, (route) => {
    w.confirmations.push(route.request().postDataJSON());
    w.orderPlaced = true;
    return json(route, { status: "accepted_mock", order_id: ids.sourceOrder });
  });
  await page.route(CART_URL, async (route) => {
    const request = route.request();
    if (request.method() !== "PUT") return route.fallback();
    const body = request.postDataJSON() as CartEditRequest;
    w.puts.push({ body, csrf: request.headers()["x-csrf-token"] });
    if (w.gate) await w.gate;
    if (w.failNext) {
      const { status, code, message } = w.failNext;
      w.failNext = null;
      return problem(route, status, code, message);
    }
    const next = { ...w.qty };
    for (const line of body.lines) next[line.product_id] = line.sales_quantity;
    if (PRODUCTS.every((p) => next[p.id] === 0))
      return problem(route, 422, "EMPTY_CART", "The basket cannot be empty.");
    if (PRODUCTS.some((p) => next[p.id] !== w.qty[p.id])) {
      if (w.renew) {
        w.old.push({
          ...proposalOf(w),
          approval_status: "cancelled",
        } as Proposal);
        w.seq += 1;
        w.revision = 1;
      } else w.revision += 1;
      w.qty = next;
    }
    const answer: CartPurchaseResponse = {
      proposal: proposalOf(w),
      not_included: notIncludedOf(w),
    };
    return json(route, answer);
  });
  await page.goto(`/conversations/${ids.conversation}`);
}
