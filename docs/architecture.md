# Architecture and tracks

We build the Valio Aimo side: an open, structured interface that an external purchasing agent can use to find products, request price and availability, place an order, and obtain human approval when its mandate does not cover the order. The buyer's agent is out of scope; a thin reference client only exercises the interface.

Because there is no buyer agent here, the interface must return structured, comparable data (normalised quantity, unit price, delivery date, reliability, labels, alternatives) so that any external agent can rank the options itself.

## The four tracks

Each track is one person (and their agents) working in parallel against stubs of the others.

### Track 1: Catalog and Discovery
Owns how an agent finds products.
- Load and index the product JSON (`data/`).
- Structured search: free text plus filters (nutritional claims such as lactose-free, allergens, category, labels, origin, temperature).
- Product detail with normalised attributes and units (sales unit, pack size, litres or kg).
- Substitute candidates as structured data.
- Join static enrichment: delivery reliability and carbon footprint (both are partial, so represent "unknown").

### Track 2: Quote and Order
Owns the move from inquiry to commitment at fixed prices.
- Request price and availability by wrapping the live APIs, on a shortlist only, with batching, caching and rate-limit handling.
- Interpret Stock vs Terminal, `salesBlock`, `closingTime` and `availableDate` vs the requested date.
- Build an **offer**: fixed price, quantity, delivery date, expiry and ID. No negotiation.
- Exception data in the response: partial availability, earliest date, alternative offers.
- Mock order backend: place an order against an offer ID; order states; status lookup.
- Call Track 3 before accepting an order.

### Track 3: Mandates, Policy and Approvals
Owns what the agent may do alone and what needs a human.
- Agent identity and **mandate** (scoped permissions): spend limit, max quantity, allowed categories, substitution rules.
- Policy engine: `auto_approve`, `needs_approval` or `deny`, each with machine- and human-readable reasons.
- Approval workflow: queue, approve or reject, approver identity, timestamps; the order moves on when decided.
- Trust protocol: the minimum standard for an agent to trust Aimo's claims (for example signed offers with expiry and origin metadata; verifiable credentials are optional).

### Track 4: Interface, Audit and Demo
Owns the public surface, the record, and what judges see.
- **The public interface:** one OpenAPI spec (optionally an MCP wrapper over the same endpoints) that fronts Tracks 1 to 3. It is the open, documented standard for the openness criterion.
- Audit trail: append-only event store and a human-readable timeline.
- Small web UI for the human approver (pending order, reason, approve or reject) and the audit view.
- Reference client and demo scenarios; README, assumptions, rationale for technical choices, path to production.

## Contracts

Agree these in the first 30 to 45 minutes and commit them as OpenAPI or JSON Schema files in `contracts/` (versioned, for example `c1.v1`). Change them only through an issue.

| # | Contract | Provider → consumer |
| --- | --- | --- |
| C1 | **Catalog API:** `search(query, filters)`, `getProduct(id)`, `substitutes(id)` | Track 1 → Tracks 2, 4 |
| C2 | **Quote/Order API:** `requestQuote(items, qty, date)` returns offers (price, availability, delivery date, expiry, alternatives); `placeOrder(offerId, mandateId)` returns an order (`confirmed`, `pending_approval` or `rejected`); `getOrder(id)` | Track 2 → Track 4 |
| C3 | **Policy API:** `evaluate(mandate, proposedOrder)` returns `{decision, reasons[]}` | Track 3 → Track 2 |
| C4 | **Approval API:** `list`, `get`, `decide(approve or reject, by)` | Track 3 → Track 4 UI |
| C5 | **Audit event schema:** `{ts, actor, action, inputs, outcome, reason, refIds}` | all tracks write → Track 4 stores and shows |

Track 4 composes C1 and C2 behind the public spec. C3 sits behind Track 2, so an external agent never calls the policy engine directly.

## Boundaries: who raises issues against whom

Open an entry in `docs/issues.md` against the **provider** track.

| Raised by | Against | Typical issue |
| --- | --- | --- |
| Track 2 | Track 1 | Normalised quantity and unit conversion missing from the product, so an offer cannot be built |
| Track 2 | Track 3 | `evaluate` returned `needs_approval` with no reason or approver role |
| Track 3 | Track 2 | Orders arrive without the offer snapshot, so total spend or substitution cannot be evaluated |
| Track 4 | Tracks 1, 2 | Responses lack a stable shape for display (unit price, labels) |
| Track 4 | Track 3 | Approval objects do not say what was requested or why it was held |
| Tracks 2, 3 | Track 4 | Audit events are not recorded at each decision step |
| Everyone | Track 4 | Public spec change needed (Track 4 owns the public OpenAPI file) |

## Working in parallel

- First 30 to 45 minutes: agree C1 to C5.
- First hour: each track ships a stub matching its contract (canned search results, canned offers, hardcoded decisions), so nobody is blocked.
- Integration points, in order: Track 2 with Track 1; Track 2 with Track 3; Track 4 fronting everything and running the full demo.
- Cut line if time runs short: drop sustainability comparison and substitution ranking. Keep the order, mandate, approval and audit path intact (the end-to-end demo and the autonomy criteria are 50% of the score).
- Record findings in `docs/findings.md` and write your daily history entry (rules in `AGENTS.md`).
