// THROWAWAY prototype fake backend. Everything here is in-memory and reset
// on page reload. No network calls. Simulated latency stands in for the
// real app's fetch() round trips so busy/loading states are visible.
//
// This intentionally keeps the real trust-boundary SHAPE: confirm/reject
// are revision-bound, authenticated-session-gated calls with an idempotency
// key — never something chat text can trigger. See README.md.

import {
  INITIAL_CONVERSATIONS,
  PROPOSALS,
  MANY_ORDERS,
  SESSION,
  CARBONARA_PLAN,
} from "./fixtures";
import type { Conversation, Message, Proposal, Scenario, Session } from "./types";

export class FakeApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type State = {
  session: Session | null;
  conversations: Map<string, Conversation>;
  conversationOrder: string[];
  proposals: Map<string, Proposal>;
  revised: Set<string>;
  scenario: Scenario;
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function approvalIndex(proposals: Map<string, Proposal>) {
  const index = new Map<string, string>();
  for (const p of proposals.values()) if (p.approval_id) index.set(p.approval_id, p.proposal_id);
  return index;
}

function freshState(): State {
  const conversations = new Map<string, Conversation>();
  const order: string[] = [];
  for (const c of clone(INITIAL_CONVERSATIONS)) {
    conversations.set(c.id, c);
    order.push(c.id);
  }
  const proposals = new Map<string, Proposal>();
  for (const [id, p] of Object.entries(clone(PROPOSALS))) proposals.set(id, p);
  return {
    session: null,
    conversations,
    conversationOrder: order,
    proposals,
    revised: new Set(),
    scenario: "default",
  };
}

let state = freshState();
const listeners = new Set<() => void>();
function notify() {
  for (const l of listeners) l();
}

const PURCHASE_PAGE_SIZE = 4;

const delay = () => new Promise((r) => setTimeout(r, state.scenario === "slow-network" ? 2600 : 650));

export const store = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getSnapshot() {
    return state;
  },

  // --- session -----------------------------------------------------------
  async login(username: string, password: string): Promise<Session> {
    await delay();
    if (!username.trim() || !password.trim())
      throw new FakeApiError(422, "Check the submitted values.");
    if (username === "baduser")
      throw new FakeApiError(401, "Incorrect username or password.");
    const session = { ...SESSION, username };
    state = { ...state, session };
    notify();
    return session;
  },
  async logout(): Promise<void> {
    await delay();
    state = { ...state, session: null };
    notify();
  },

  // --- conversations -------------------------------------------------------
  async listConversations() {
    await delay();
    return {
      items: state.conversationOrder.map((id) => {
        const c = state.conversations.get(id)!;
        return { id: c.id, title: c.title };
      }),
      next_offset: null,
    };
  },
  async getConversation(id: string): Promise<Conversation> {
    await delay();
    const c = state.conversations.get(id);
    if (!c) throw new FakeApiError(404, "Conversation not found.");
    return clone(c);
  },
  async sendMessage(conversationId: string | null, text: string): Promise<Conversation> {
    let id = conversationId;
    if (!id) {
      id = `conv-${Date.now()}`;
      const fresh: Conversation = {
        id,
        title: text.slice(0, 120),
        busy: false,
        messages: [],
        purchases: [],
      };
      state.conversations.set(id, fresh);
      state.conversationOrder.unshift(id);
    }
    const conversation = state.conversations.get(id)!;
    conversation.messages.push({
      id: `m-${Date.now()}`,
      role: "user",
      text,
      created_at: new Date().toISOString(),
    });
    conversation.busy = true;
    conversation.retry_message = null;
    notify();
    await delay();

    if (state.scenario === "send-error") {
      conversation.busy = false;
      conversation.retry_message = { text, idempotency_key: `retry-${Date.now()}` };
      state.scenario = "default"; // one-shot: the retry should succeed.
      notify();
      throw new FakeApiError(
        503,
        "The service could not complete this request. Try again.",
      );
    }

    const assistant: Message = {
      id: `m-${Date.now()}-a`,
      role: "assistant",
      text: "Could you tell me the meal, portion count and delivery kitchen? I'll match catalog products and prepare the exact basket for your review.",
      created_at: new Date().toISOString(),
    };
    if (/carbonara/i.test(text)) {
      const propId = `prop-${id}`;
      const base = clone(PROPOSALS["prop-ready"]);
      const proposal: Proposal = { ...base, proposal_id: propId, approval_id: `appr-${id}` };
      state.proposals.set(propId, proposal);
      assistant.text =
        "Here is a proposed plan for 200 portions of carbonara. I matched five catalog products and prepared the exact basket below for your review.";
      assistant.meal_plan = CARBONARA_PLAN;
      assistant.proposal_id = propId;
      conversation.purchases.push({
        proposal_id: propId,
        request: { request_id: proposal.request.request_id },
        snapshot: { gross_total: proposal.snapshot.gross_total },
        approval_status: proposal.approval_status,
        order_status: proposal.order_status,
        policy_outcome: proposal.policy_outcome,
        expires_at: proposal.expires_at,
      });
    }
    conversation.messages.push(assistant);
    conversation.busy = false;
    notify();
    return clone(conversation);
  },

  // --- purchases -----------------------------------------------------------
  // Default: every proposal in one page. Scenario "many-orders" serves a longer
  // list in API pages of PURCHASE_PAGE_SIZE (offset paging, like the backend).
  async listPurchases(offset = 0) {
    await delay();
    if (state.scenario === "empty-purchases") return { items: [], next_offset: null };
    const base = Array.from(state.proposals.values());
    if (state.scenario !== "many-orders") return { items: base.map(clone), next_offset: null };
    const all = [...MANY_ORDERS, ...base];
    const next = offset + PURCHASE_PAGE_SIZE;
    return {
      items: all.slice(offset, next).map(clone),
      next_offset: next < all.length ? next : null,
    };
  },
  findConversationForProposal(proposalId: string): string | undefined {
    for (const c of state.conversations.values()) {
      if (c.purchases.some((purchase) => purchase.proposal_id === proposalId)) return c.id;
    }
    return undefined;
  },
  async getProposal(proposalId?: string, approvalId?: string): Promise<Proposal> {
    await delay();
    const id = proposalId ?? approvalIndex(state.proposals).get(approvalId ?? "");
    const p = id
      ? state.proposals.get(id) ??
        (state.scenario === "many-orders" ? MANY_ORDERS.find((m) => m.proposal_id === id) : undefined)
      : undefined;
    if (!p) throw new FakeApiError(404, "Purchase not found.");
    return clone(p);
  },
  async confirm(proposalId: string, revision: number): Promise<{ status: "accepted" | "revised"; proposal: Proposal }> {
    await delay();
    const p = state.proposals.get(proposalId);
    if (!p) throw new FakeApiError(404, "Purchase not found.");
    if (proposalId === "prop-conflict" && revision === 1 && !state.revised.has(proposalId)) {
      state.revised.add(proposalId);
      p.revision = 2;
      p.current_revision = 2;
      p.snapshot.gross_total = "536.40";
      p.snapshot.net_total = "489.33";
      p.snapshot.tax_total = "47.07";
      p.history.push({
        event: "price_revised",
        actor_id: "aimo-agent",
        created_at: new Date().toISOString(),
      });
      notify();
      return { status: "revised", proposal: clone(p) };
    }
    if (p.revision !== p.current_revision) {
      notify();
      return { status: "revised", proposal: clone(p) };
    }
    p.order_status = "accepted_mock";
    p.order_id = `DEMO-ORD-${Math.floor(1000 + Math.random() * 9000)}`;
    p.approval_status = "approved";
    p.committed_revision = p.revision;
    p.can_decide = false;
    p.history.push({
      event: "purchase_confirmed",
      actor_id: state.session?.username ?? "buyer",
      created_at: new Date().toISOString(),
    });
    notify();
    return { status: "accepted", proposal: clone(p) };
  },
  async reject(proposalId: string): Promise<Proposal> {
    await delay();
    const p = state.proposals.get(proposalId);
    if (!p) throw new FakeApiError(404, "Purchase not found.");
    p.approval_status = "rejected";
    p.can_decide = false;
    p.history.push({
      event: "purchase_rejected",
      actor_id: state.session?.username ?? "buyer",
      created_at: new Date().toISOString(),
    });
    notify();
    return clone(p);
  },

  // Simplified fixture-only recovery for the "superseded" demo: the real
  // backend would simply return the already-current revision on reload.
  // Here we fake that same effect explicitly so the link is clickable.
  advanceSuperseded(proposalId: string) {
    const p = state.proposals.get(proposalId);
    if (!p) return;
    p.revision = p.current_revision;
    p.approval_status = "pending";
    p.policy_outcome = "ready_to_commit";
    p.can_decide = true;
    notify();
  },

  // --- prototype-only scenario control --------------------------------------
  setScenario(scenario: Scenario) {
    state = { ...state, scenario };
    notify();
  },
  getScenario() {
    return state.scenario;
  },
  reset() {
    state = freshState();
    notify();
  },
};

export function proposalStatus(p: Proposal): string {
  if (p.approval_status === "superseded") return "superseded";
  if (p.order_status === "accepted_mock") return "accepted_mock";
  if (p.approval_status === "rejected") return "rejected";
  if (new Date(p.expires_at) <= new Date()) return "expired";
  return p.approval_status === "not_required" ? p.policy_outcome : p.approval_status;
}
