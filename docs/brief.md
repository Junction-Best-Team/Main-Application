# Project brief

Keep it short and update it when the team changes scope. This is a redacted summary of the official challenge; the raw brief is in `local/` (gitignored).

## Problem and challenge

- **Challenge and link:** Trusted Trade Agents, by Valio Aimo. Resources: https://junction26.valioaimo.fi/ (password on the challenge page).
- **Judging criteria:** Working end-to-end demo 30% (full request → lookup → order/approval flow in the mocked environment). Solving the problem and user need 20% (how precisely the request is matched with least manual correction). Autonomy and controls 20% (guardrails, human sign-off, logged and auditable decisions). Robustness to exceptions 15% (partial availability, substitutions, delivery constraints). Openness and credible path to production 15% (open documented standards, visible assumptions, justified technical choices, next steps).
- **Specific user and situation:** An external purchasing agent acting for a food-service buyer (for example a hotel chain) that needs to order from Valio Aimo, which serves 20,000+ professional kitchens.
- **Problem and current workaround:** Ordering is manual or menu-driven in the webshop. There is no defined, safe way for an autonomous agent to find, compare and order, or to know what it may decide alone.
- **Evidence or mentor feedback:** Mentors are available for commercial, online sales, and IT/data-governance questions (see the challenge page). Notes go in `docs/findings.md`.
- **One-sentence solution:** For external purchasing agents of food-service buyers, give Valio Aimo an open, structured interface for product lookup, fixed-price quoting and ordering, with a mandate-based approval model and an auditable decision trail.

## Scope decision

We build the **Valio Aimo side** (the interface and operating model), not the buyer's agent. The brief says it is "not about replacing today's e-commerce UI with a chatbot". A thin reference client exists only to demo and test the interface. See `docs/architecture.md`.

## Demonstration

- **Demo story:** Given the request "I need 1,000 litres of lactose-free milk by Monday", an external agent searches the catalog, requests price and availability, and places an order. Within its mandate the order is confirmed; above its limit it goes to a human, who approves it, and the audit trail shows both decisions and why.
- **Observable success criterion:** One run shows request → lookup → quote → order → (approval) → confirmed order, plus a readable audit trail, and a second run covers an exception (partial availability or substitute).
- **Essential real integration:** Live `/api/price` and `/api/availability` calls on a shortlist, plus the static product data.
- **Sample inputs and expected outputs:** TBD (the three demo scenarios go here once the contracts are agreed).
- **Mocked or simulated parts to disclose:** Order placement, order states, mandates, policy engine, approvals and audit log (the Aimo API has no order endpoint). The Aimo data itself is synthetic.
- **Fallback if a service or network fails:** Cached responses for the demo shortlist (TBD, owner: Track 2).

## Scope

| Priority | Feature | Acceptance criterion | Owner |
| --- | --- | --- | --- |
| Essential 1 | Product, price and availability lookup | An agent can search with structured filters (for example lactose-free) and get products with price, availability and delivery date in structured form | Tracks 1 and 2 |
| Essential 2 | Request price and availability, then place an order at a fixed price | An offer has an ID, fixed price and expiry; an order can only be placed against a valid offer | Track 2 |
| Essential 3 | Permissions and human approval | A mandate decides `auto_approve`, `needs_approval` or `deny` with reasons; a held order can be approved or rejected by a human | Track 3 |

- **Stretch ideas:** delivery reliability and carbon comparison; substitution ranking; recipe-aware substitution; signed offers or verifiable credentials; standing-order drift detection.
- **Outside this weekend's scope:** the buyer's agent itself, the full marketplace, payments (x402 and similar), real systems or data.

## Feasibility and interfaces

- **Riskiest assumption and first experiment:** That quantity and unit can be normalised reliably (for example 1,000 litres to a number of sales units). First experiment: take 10 lactose-free milk products and compute packs needed from `units` and the name text. See `docs/findings.md`.
- **Data/API/hardware access and restrictions:** Synthetic data only. Live APIs are rate limited (undisclosed) and must not be polled for all products. Details in `AGENTS.md` and `docs/findings.md`.
- **Agreed stack and deployment target:** TBD.
- **Shared interfaces:** Contracts C1–C5 in `docs/architecture.md`; schema files go in `contracts/` once agreed.

## Ownership and deadlines

- **Integration coordinator:** TBD
- **Demo/pitch owner:** TBD
- **Submission owner and backup:** TBD
- **Official deadlines and timezone:** TBD — verify on the event platform (event runs November 13–15, Espoo).
- **Internal feature freeze and submission buffer:** TBD
- **Submission checklist:** Required links, repository access, video/pitch format, licences, disclosures, and challenge-specific fields.
