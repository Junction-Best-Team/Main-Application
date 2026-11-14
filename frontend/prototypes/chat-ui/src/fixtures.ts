// THROWAWAY prototype fixtures — fake JSON only, no backend. Carbonara-style
// meal plan + proposal data per the #25 parity inventory. Numbers are
// invented for a repeatable demo; this mirrors the real app's own
// "fixture" snapshot mode copy.

import type {
  Conversation,
  MealPlan,
  Proposal,
  Session,
} from "./types";

export const SESSION: Session = {
  buyer_id: "kitchen-helsinki-01",
  username: "chef.helsinki",
  csrf_token: "fake-csrf-prototype",
};

export const CARBONARA_PLAN: MealPlan = {
  title: "Carbonara for 200 portions",
  portions: 200,
  ingredients: [
    { name: "Spaghetti", amount: "22", unit: "kg" },
    { name: "Guanciale", amount: "9", unit: "kg" },
    { name: "Eggs", amount: "480", unit: "pcs" },
    { name: "Pecorino Romano", amount: "6", unit: "kg" },
    { name: "Black pepper", amount: "0.6", unit: "kg" },
  ],
  notes: [
    "Pasta, eggs, pork and cheese require the buyer-authorized substitution exception on this demo policy.",
  ],
};

function line(
  product_id: string,
  name: string,
  requested: string,
  unit: string,
  sales: string | null,
  proposed: string,
  excess: string,
  gross: string,
  tax: string,
  deposits: string,
  substitutes_for?: string,
): Proposal["snapshot"]["lines"][number] {
  return {
    product_id,
    name,
    substitutes_for: substitutes_for ?? null,
    quantity: {
      requested_amount: requested,
      requested_unit: unit,
      sales_quantity: sales,
      sales_unit: unit,
      proposed_amount: proposed,
      excess,
    },
    gross,
    tax,
    deposits_gross: deposits,
    product_evidence: { matched_by: "name+unit fixture similarity" },
    commercial_evidence: { source: "fixture price list" },
  };
}

const CARBONARA_LINES = [
  line("P-1001", "Spaghetti 1kg", "22", "kg", "22", "22", "0", "41.80", "3.99", "0.00"),
  line("P-1002", "Guanciale 500g", "9", "kg", "18", "9", "0", "198.00", "18.86", "0.00"),
  line(
    "P-1003",
    "Free-range eggs, 30-pack",
    "480",
    "pcs",
    "16",
    "480",
    "0",
    "144.00",
    "13.71",
    "4.80",
    "P-0990",
  ),
  line("P-1004", "Pecorino Romano 1kg", "6", "kg", "6", "6", "0", "216.00", "20.57", "0.00"),
  line("P-1005", "Black pepper, ground, 500g", "0.6", "kg", "1", "0.6", "0.4", "18.90", "1.80", "0.00"),
];

function proposal(overrides: Partial<Proposal>): Proposal {
  const base: Proposal = {
    proposal_id: "prop-ready",
    approval_id: "appr-ready",
    buyer_id: SESSION.buyer_id,
    agent_id: "aimo-agent",
    revision: 1,
    current_revision: 1,
    policy_version: 3,
    approval_status: "pending",
    order_status: "none",
    policy_outcome: "ready_to_commit",
    can_decide: true,
    order_id: null,
    committed_revision: null,
    expires_at: new Date(Date.now() + 1000 * 60 * 60 * 20).toISOString(),
    request: {
      request_id: "REQ-CARB-200",
      destination: "Kitchen 4, Teurastamo, Helsinki",
      delivery_date: new Date(Date.now() + 1000 * 60 * 60 * 24 * 2)
        .toISOString()
        .slice(0, 10),
      budget_gross: "650.00",
    },
    snapshot: {
      mode: "fixture",
      observed_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
      lines: CARBONARA_LINES,
      net_total: "561.42",
      tax_total: "58.93",
      deposits_gross: "4.80",
      charges_gross: "2.35",
      gross_total: "627.50",
    },
    reasons: [
      {
        code: "POLICY-OK",
        message: "Within standing purchasing policy for this buyer.",
      },
      {
        code: "SUBSTITUTION-NOTED",
        message: "Eggs substituted to the nearest stocked pack size.",
      },
    ],
    history: [
      {
        event: "proposal_created",
        actor_id: "aimo-agent",
        created_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
      },
    ],
  };
  return { ...base, ...overrides, snapshot: { ...base.snapshot, ...overrides.snapshot } };
}

// Scenario "many-orders": a purchase list long enough to need several API pages,
// where the first pages hold no accepted orders (Past Orders must keep paging).
// Order matters: the list is served in this order, then the base PROPOSALS.
function manyOrder(id: string, kind: "accepted" | "rejected" | "expired" | "pending", day: number): Proposal {
  const when = new Date(Date.now() - 1000 * 60 * 60 * 24 * day).toISOString();
  const accepted = kind === "accepted";
  return proposal({
    proposal_id: id,
    approval_id: `appr-${id}`,
    approval_status: accepted ? "approved" : kind === "rejected" ? "rejected" : "pending",
    order_status: accepted ? "accepted_mock" : "none",
    can_decide: kind === "pending",
    order_id: accepted ? `DEMO-ORD-${2000 + day}` : null,
    committed_revision: accepted ? 1 : null,
    expires_at:
      kind === "expired"
        ? new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString()
        : new Date(Date.now() + 1000 * 60 * 60 * 20).toISOString(),
    request: {
      request_id: `REQ-${accepted ? "MANY" : "REJ"}-${String(day).padStart(3, "0")}`,
      destination: "Kitchen 4, Teurastamo, Helsinki",
      delivery_date: when.slice(0, 10),
      budget_gross: null,
    },
    snapshot: {
      mode: "fixture",
      observed_at: when,
      lines: CARBONARA_LINES.slice(0, 1 + (day % 3)),
      net_total: "100.00",
      tax_total: "10.00",
      deposits_gross: "0.00",
      charges_gross: "0.00",
      gross_total: "110.00",
    },
    history: accepted
      ? [
          { event: "proposal_created", actor_id: "aimo-agent", created_at: when },
          { event: "purchase_confirmed", actor_id: SESSION.username, created_at: when },
        ]
      : [{ event: "proposal_created", actor_id: "aimo-agent", created_at: when }],
  });
}

export const MANY_ORDERS: Proposal[] = [
  ...(["rejected", "expired", "pending", "rejected", "pending", "expired", "rejected", "pending"] as const).map(
    (kind, i) => manyOrder(`prop-many-open-${i}`, kind, 40 + i),
  ),
  ...[1, 2, 3, 4, 5, 6, 7].map((day) => manyOrder(`prop-many-done-${day}`, "accepted", day * 4)),
];

export const PROPOSALS: Record<string, Proposal> = {
  "prop-ready": proposal({}),
  "prop-conflict": proposal({
    proposal_id: "prop-conflict",
    approval_id: "appr-conflict",
    request: {
      request_id: "REQ-OAT-RESTOCK",
      destination: "Kitchen 1, Pasila, Helsinki",
      delivery_date: new Date(Date.now() + 1000 * 60 * 60 * 24).toISOString().slice(0, 10),
      budget_gross: "600.00",
    },
    snapshot: {
      mode: "fixture",
      observed_at: new Date(Date.now() - 1000 * 60 * 10).toISOString(),
      lines: [
        line("P-2001", "Oat drink, barista, 1L x12", "40", "case", "40", "40", "0", "398.00", "37.90", "0.00"),
        line("P-2002", "Oat yoghurt, 500g x12", "10", "case", "10", "10", "0", "112.00", "10.67", "0.00"),
      ],
      net_total: "465.43",
      tax_total: "48.57",
      deposits_gross: "0.00",
      charges_gross: "0.00",
      gross_total: "510.00",
    },
    history: [
      {
        event: "proposal_created",
        actor_id: "aimo-agent",
        created_at: new Date(Date.now() - 1000 * 60 * 10).toISOString(),
      },
    ],
  }),
  "prop-done": proposal({
    proposal_id: "prop-done",
    approval_id: "appr-done",
    approval_status: "approved",
    order_status: "accepted_mock",
    policy_outcome: "ready_to_commit",
    can_decide: false,
    order_id: "DEMO-ORD-1180",
    committed_revision: 1,
    request: {
      request_id: "REQ-PREV-0017",
      destination: "Kitchen 4, Teurastamo, Helsinki",
      delivery_date: new Date(Date.now() - 1000 * 60 * 60 * 24 * 3).toISOString().slice(0, 10),
      budget_gross: null,
    },
    snapshot: {
      mode: "fixture",
      observed_at: new Date(Date.now() - 1000 * 60 * 60 * 72).toISOString(),
      lines: CARBONARA_LINES.slice(0, 2),
      net_total: "215.81",
      tax_total: "22.85",
      deposits_gross: "0.00",
      charges_gross: "1.74",
      gross_total: "239.80",
    },
    reasons: [
      { code: "POLICY-OK", message: "Within standing purchasing policy for this buyer." },
    ],
    history: [
      {
        event: "proposal_created",
        actor_id: "aimo-agent",
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 72).toISOString(),
      },
      {
        event: "purchase_confirmed",
        actor_id: SESSION.username,
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 71).toISOString(),
      },
    ],
  }),
  "prop-rejected": proposal({
    proposal_id: "prop-rejected",
    approval_id: "appr-rejected",
    approval_status: "rejected",
    policy_outcome: "denied",
    can_decide: false,
    request: {
      request_id: "REQ-PREV-0022",
      destination: "Kitchen 2, Kallio, Helsinki",
      delivery_date: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString().slice(0, 10),
      budget_gross: "100.00",
    },
    snapshot: {
      mode: "fixture",
      observed_at: new Date(Date.now() - 1000 * 60 * 60 * 48).toISOString(),
      lines: [line("P-3001", "Truffle oil, 250ml", "4", "bottle", "4", "4", "0", "188.00", "17.90", "0.00")],
      net_total: "170.10",
      tax_total: "17.90",
      deposits_gross: "0.00",
      charges_gross: "0.00",
      gross_total: "188.00",
    },
    reasons: [{ code: "OVER-BUDGET", message: "Exceeds the stated mission budget." }],
    history: [
      {
        event: "proposal_created",
        actor_id: "aimo-agent",
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 48).toISOString(),
      },
      {
        event: "purchase_rejected",
        actor_id: SESSION.username,
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 47).toISOString(),
      },
    ],
  }),
  "prop-expired": proposal({
    proposal_id: "prop-expired",
    approval_id: "appr-expired",
    expires_at: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
    request: {
      request_id: "REQ-PREV-0031",
      destination: "Kitchen 3, Vallila, Helsinki",
      delivery_date: new Date(Date.now() - 1000 * 60 * 60 * 24 * 2).toISOString().slice(0, 10),
      budget_gross: null,
    },
    snapshot: {
      mode: "fixture",
      observed_at: new Date(Date.now() - 1000 * 60 * 60 * 30).toISOString(),
      lines: [line("P-4001", "Sourdough starter kit", "3", "kit", "3", "3", "0", "33.60", "3.20", "0.00")],
      net_total: "30.40",
      tax_total: "3.20",
      deposits_gross: "0.00",
      charges_gross: "0.00",
      gross_total: "33.60",
    },
    history: [
      {
        event: "proposal_created",
        actor_id: "aimo-agent",
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 30).toISOString(),
      },
    ],
  }),
  "prop-blocked": proposal({
    proposal_id: "prop-blocked",
    approval_id: "appr-blocked",
    policy_outcome: "denied",
    can_decide: false,
    request: {
      request_id: "REQ-BRUNCH-40",
      destination: "Kitchen 3, Vallila, Helsinki",
      delivery_date: new Date(Date.now() + 1000 * 60 * 60 * 24 * 3).toISOString().slice(0, 10),
      budget_gross: "150.00",
    },
    snapshot: {
      mode: "fixture",
      observed_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
      lines: CARBONARA_LINES.slice(0, 2),
      net_total: "215.81",
      tax_total: "22.85",
      deposits_gross: "0.00",
      charges_gross: "1.74",
      gross_total: "239.80",
    },
    reasons: [
      {
        code: "BUDGET-EXCEEDED",
        message: "The basket total is above the 150.00 EUR budget set for this request.",
      },
    ],
    history: [
      {
        event: "proposal_created",
        actor_id: "aimo-agent",
        created_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
      },
    ],
  }),
  "prop-superseded": proposal({
    proposal_id: "prop-superseded",
    approval_id: "appr-superseded",
    approval_status: "superseded",
    revision: 1,
    current_revision: 2,
    committed_revision: null,
    request: {
      request_id: "REQ-PREV-0040",
      destination: "Kitchen 1, Pasila, Helsinki",
      delivery_date: new Date(Date.now() + 1000 * 60 * 60 * 24 * 5).toISOString().slice(0, 10),
      budget_gross: "300.00",
    },
    snapshot: {
      mode: "fixture",
      observed_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(),
      lines: [line("P-5001", "Parmigiano Reggiano 1kg", "5", "kg", "5", "5", "0", "180.00", "17.14", "0.00")],
      net_total: "162.86",
      tax_total: "17.14",
      deposits_gross: "0.00",
      charges_gross: "0.00",
      gross_total: "180.00",
    },
    history: [
      {
        event: "proposal_created",
        actor_id: "aimo-agent",
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(),
      },
      {
        event: "price_revised",
        actor_id: "aimo-agent",
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 1).toISOString(),
      },
    ],
  }),
};

export const INITIAL_CONVERSATIONS: Conversation[] = [
  {
    id: "conv-carbonara",
    title: "200 portions of carbonara",
    busy: false,
    messages: [
      {
        id: "m-1",
        role: "user",
        text: "I need ingredients for 200 portions of carbonara.",
        created_at: new Date(Date.now() - 1000 * 60 * 40).toISOString(),
      },
      {
        id: "m-2",
        role: "assistant",
        text: "Here is a proposed plan for 200 portions of carbonara. I matched five catalog products and prepared the exact basket below for your review.",
        created_at: new Date(Date.now() - 1000 * 60 * 35).toISOString(),
        meal_plan: CARBONARA_PLAN,
        proposal_id: "prop-ready",
      },
    ],
    purchases: [
      {
        proposal_id: "prop-ready",
        request: { request_id: "REQ-CARB-200" },
        snapshot: { gross_total: "627.50" },
        approval_status: "pending",
        order_status: "none",
        policy_outcome: "ready_to_commit",
        expires_at: PROPOSALS["prop-ready"].expires_at,
      },
    ],
  },
  {
    id: "conv-oat-restock",
    title: "Weekly oat milk restock",
    busy: false,
    messages: [
      {
        id: "m-3",
        role: "user",
        text: "Restock oat drink and oat yoghurt for Pasila kitchen, usual quantities.",
        created_at: new Date(Date.now() - 1000 * 60 * 20).toISOString(),
      },
      {
        id: "m-4",
        role: "assistant",
        text: "I matched your usual oat products and prepared the exact basket. Prices moved slightly since your last order — please review before confirming.",
        created_at: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
        proposal_id: "prop-conflict",
      },
    ],
    purchases: [
      {
        proposal_id: "prop-conflict",
        request: { request_id: "REQ-OAT-RESTOCK" },
        snapshot: { gross_total: "510.00" },
        approval_status: "pending",
        order_status: "none",
        policy_outcome: "ready_to_commit",
        expires_at: PROPOSALS["prop-conflict"].expires_at,
      },
    ],
  },
  {
    id: "conv-blocked",
    title: "Brunch for 40 (over budget)",
    busy: false,
    messages: [
      {
        id: "m-6",
        role: "user",
        text: "Brunch basics for 40 people, budget 150 EUR.",
        created_at: new Date(Date.now() - 1000 * 60 * 8).toISOString(),
      },
      {
        id: "m-7",
        role: "assistant",
        text: "I prepared the basket, but it is above your budget, so it cannot be approved as it stands.",
        created_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
        proposal_id: "prop-blocked",
      },
    ],
    purchases: [
      {
        proposal_id: "prop-blocked",
        request: { request_id: "REQ-BRUNCH-40" },
        snapshot: { gross_total: "239.80" },
        approval_status: "pending",
        order_status: "none",
        policy_outcome: "denied",
        expires_at: PROPOSALS["prop-blocked"].expires_at,
      },
    ],
  },
  {
    id: "conv-expired",
    title: "Vallila dairy (expired)",
    busy: false,
    messages: [
      {
        id: "m-8",
        role: "user",
        text: "Dairy top-up for Vallila.",
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(),
      },
      {
        id: "m-9",
        role: "assistant",
        text: "Here is the basket for your review.",
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 4).toISOString(),
        proposal_id: "prop-expired",
      },
    ],
    purchases: [
      {
        proposal_id: "prop-expired",
        request: { request_id: "REQ-PREV-0031" },
        snapshot: { gross_total: PROPOSALS["prop-expired"].snapshot.gross_total },
        approval_status: "pending",
        order_status: "none",
        policy_outcome: "ready_to_commit",
        expires_at: PROPOSALS["prop-expired"].expires_at,
      },
    ],
  },
  {
    id: "conv-empty",
    title: "Vallila weekend prep",
    busy: false,
    messages: [
      {
        id: "m-5",
        role: "user",
        text: "What do I need for a weekend brunch for 40 people?",
        created_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
      },
    ],
    purchases: [],
    retry_message: null,
  },
];
