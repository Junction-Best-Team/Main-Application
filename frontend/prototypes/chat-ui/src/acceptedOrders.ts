// Accepted orders = proposals with an order_id (order status accepted_mock).
// The purchase list endpoint returns every proposal, so Past Orders and Home
// filter client-side and keep fetching API pages until they hold enough.
import type { Proposal } from "./types";
import { store } from "./store";

export const isAccepted = (p: Proposal) => Boolean(p.order_id) && p.order_status === "accepted_mock";

export const placedAt = (p: Proposal) =>
  p.history?.find((e) => e.event === "purchase_confirmed")?.created_at ?? p.snapshot.observed_at;

/** Fetch API pages from `from` until `want` accepted orders are held (and
 *  `mustHave`, if given, is among them) or the list ends. */
export async function fillAccepted(
  from: number,
  held: Proposal[],
  want: number,
  mustHave?: string,
): Promise<{ orders: Proposal[]; nextOffset: number | null }> {
  let offset: number | null = from;
  let all = held;
  while (offset !== null) {
    const page = await store.listPurchases(offset);
    all = [...all, ...page.items.filter(isAccepted)];
    offset = page.next_offset;
    if (all.length >= want && (!mustHave || all.some((p) => p.proposal_id === mustHave))) break;
  }
  return { orders: all, nextOffset: offset };
}
