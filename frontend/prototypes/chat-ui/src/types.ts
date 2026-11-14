// THROWAWAY prototype types — a trimmed hand-written subset of the real
// generated frontend/src/api-types.ts, just enough to drive fake JSON.
// Not generated, not authoritative. See README.md.

export type Session = {
  buyer_id: string;
  username: string;
  csrf_token: string;
};

export type MealPlanIngredient = {
  name: string;
  amount: string;
  unit: string;
};

export type MealPlan = {
  title: string;
  portions: number;
  ingredients: MealPlanIngredient[];
  notes?: string[];
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  created_at: string;
  meal_plan?: MealPlan;
  proposal_id?: string;
};

export type RetryMessage = { text: string; idempotency_key: string };

export type ConversationPurchase = {
  proposal_id: string;
  request: { request_id: string };
  snapshot: { gross_total: string };
  approval_status: string;
  order_status: string;
  policy_outcome: string;
  expires_at: string;
};

export type Conversation = {
  id: string;
  title: string;
  busy: boolean;
  messages: Message[];
  purchases: ConversationPurchase[];
  retry_message?: RetryMessage | null;
};

export type ConversationListItem = { id: string; title: string };
export type ConversationList = {
  items: ConversationListItem[];
  next_offset: number | null;
};

export type ProposalLine = {
  product_id: string;
  name: string;
  substitutes_for?: string | null;
  quantity: {
    requested_amount: string;
    requested_unit: string;
    sales_quantity: string | null;
    sales_unit: string;
    proposed_amount: string;
    excess: string;
  };
  gross: string;
  tax: string;
  deposits_gross: string;
  product_evidence?: unknown;
  commercial_evidence?: unknown;
};

export type ProposalHistoryEvent = {
  event: string;
  actor_id: string;
  created_at: string;
};

export type Proposal = {
  proposal_id: string;
  approval_id: string | null;
  buyer_id: string;
  agent_id: string;
  revision: number;
  current_revision: number;
  policy_version: number;
  approval_status: string;
  order_status: string;
  policy_outcome: string;
  can_decide: boolean;
  order_id: string | null;
  committed_revision: number | null;
  expires_at: string;
  request: {
    request_id: string;
    destination: string;
    delivery_date: string;
    budget_gross: string | null;
  };
  snapshot: {
    mode: "fixture" | "supplier";
    observed_at: string;
    lines: ProposalLine[];
    net_total: string;
    tax_total: string;
    deposits_gross: string;
    charges_gross: string;
    gross_total: string;
  };
  reasons: { code: string; message: string }[];
  history: ProposalHistoryEvent[];
};

export type Inbox = {
  items: (Proposal & { snapshot: { lines: { name: string }[] } & Proposal["snapshot"] })[];
  next_offset: number | null;
};

export type Scenario =
  | "default"
  | "reconnecting"
  | "send-error"
  | "empty-purchases"
  | "slow-network";
