# Aimo chat purchasing architecture

This describes the implemented chat product. The [chat purchasing migration](chat-purchasing.md)
supersedes the external-agent/MCP entry points in the [original brief](brief.md).
GitHub renders both Mermaid diagrams directly; edit their text here when the architecture changes.

## System overview

```mermaid
flowchart TB
    Buyer["Buyer in browser"]
    UI["React + TypeScript<br/>Chat, basket review, purchase history"]
    Buyer <--> UI

    subgraph App["One FastAPI application / production image"]
        API["Authenticated JSON API + SSE<br/>Serves built React assets"]
        Conversations["Conversation persistence<br/>Turn leases and retry recovery"]
        Agent["Internal meal-purchasing agent<br/>Typed tools bound to buyer identity"]
        Service["Shared purchasing Service"]
        Search["Hybrid catalog search<br/>Full-text + vector ranking"]
        Workflow["Purchase workflow<br/>Quantity/evidence validation, confirmation, commit"]
        Policy["Deterministic policy evaluation<br/>Scope, limits, exceptions, authority"]
        Embeddings["Local pinned embedding model"]
        Supplier["Supplier connector<br/>Authored fixtures by default"]
        API --> Conversations --> Agent --> Service
        API -->|"Customer confirmation and purchase review"| Workflow
        Service --> Search --> Embeddings
        Service --> Workflow --> Policy
        Service --> Supplier
        Workflow -->|"Fresh commercial evidence"| Supplier
    end

    UI <-->|"Same-origin session + CSRF<br/>JSON requests / persisted-state SSE"| API
    DB[("PostgreSQL + pgvector<br/>Catalog and vectors; policies and identities;<br/>conversations, revisions, confirmations,<br/>approvals, mock orders and audit")]
    Conversations <--> DB
    Search <--> DB
    Workflow <--> DB

    LLM["External conversational LLM provider"]
    Agent <-->|"Server-side provider calls"| LLM
    Valio["External Valio API<br/>Optional live price / availability"]
    Supplier <-->|"Live mode only"| Valio

    Importer["Explicit catalog ingestion command / Job<br/>Same application image, runs to completion"]
    Catalog["Private catalog snapshot<br/>or authenticated Valio download"]
    Catalog --> Importer --> DB
    Importer --> Embeddings
```

- **Runtime:** one backend serves the frontend and runs the agent, search and purchasing modules.
  The embedding model runs locally in the process. The conversational LLM is a separate provider;
  its credentials stay on the server.
- **Data:** PostgreSQL stores both the derived catalog index and durable business records.
  Catalog ingestion is an explicit operator command, never a request/startup hook. Fixture
  embeddings and a small fixture catalog are available for testing independently of supplier mode.
- **Authority:** the backend binds tool calls to a trusted internal identity. The agent can plan,
  search and prepare; its tool registry has no approval or commit operation. Policy and identity
  provisioning are privileged setup operations, with no runtime policy editor.
- **Ordering:** even with live prices/availability, acceptance is a persistent **mock order**.
  There is no supplier checkout or stock reservation. `/mcp` and `/api/agent/*` are removed.

Optional Kubernetes hosting uses one application Deployment plus a PostgreSQL endpoint and an
occasional ingestion/setup Job. Infrastructure configuration does not establish that it has been
deployed; see the [deployment guide](../deploy/README.md) and [Terraform runbook](../infra/README.md).

## Purchase and confirmation sequence

```mermaid
sequenceDiagram
    actor Buyer as Buyer in React UI
    participant API as FastAPI / conversations
    participant Agent as Internal typed agent
    participant Service as Purchasing Service / workflow
    participant Supplier as Supplier connector
    participant DB as PostgreSQL

    Buyer->>API: Send message with stable retry key
    API->>DB: Persist message and reserve bounded turn
    API->>Agent: Run with trusted buyer identity and saved context
    Note over Buyer,Agent: Clarify portions, date, destination, dietary needs and budget
    Agent->>Service: Read policy, search and load actual products
    Service->>DB: Read catalog, quantity evidence and policy
    DB-->>Service: Buyer-scoped facts
    Service-->>Agent: Product matches and effective rules
    Agent->>Agent: Publish complete matched meal plan
    Agent->>Service: Prepare exact matching basket with server-generated retry key
    Service->>Supplier: Check current price and availability
    Supplier-->>Service: Commercial evidence with fixture/live label
    Service->>Service: Validate quantities, costs, evidence and policy
    Service->>DB: Save immutable proposal revision and any approval request
    Service-->>Agent: Proposal, outcome and reasons
    Agent-->>API: Reply, meal plan and actual proposal reference
    API->>DB: Persist completed assistant response
    API-->>Buyer: Saved chat state and basket review
    Note over Buyer,Service: denied / needs_resolution remain blocked<br/>Approval cannot repair missing facts

    Buyer->>API: Click Confirm purchase for exact proposal revision
    API->>API: Verify session, Origin and CSRF
    API->>DB: Under buyer lock, check current authority and persist exact confirmation / approval
    API->>Service: Commit confirmed revision with stable retry key
    Service->>Supplier: Re-fetch commercial evidence
    Supplier-->>Service: Current prices and availability
    Service->>DB: Lock buyer/proposal and read current policy and authority
    Service->>Service: Revalidate terms, policy and confirmation
    alt Terms or effective authorization changed
        Service->>DB: Save new revision and invalidate earlier approval
        Service-->>API: Revised proposal without confirmation
        API-->>Buyer: Review new terms and explicitly confirm again if eligible
    else Unchanged, valid and currently authorized
        Service->>DB: Atomically save mock order, receipt, retry result and audit
        Service-->>API: Accepted by demo order service
        API-->>Buyer: Saved mock receipt with no supplier order or reservation
    else Commitment is blocked
        Service-->>API: Explain policy, evidence or authorization failure
        API-->>Buyer: Resolve the issue before proceeding
    end
    Note over API,DB: Completed confirmation retries return the saved receipt without another supplier/provider call
```

Recipe agreement or approval text in chat never authorizes a purchase. Both `ready_to_commit`
and `approval_required` proposals still need the authenticated confirmation action for the internal
agent. A changed revision needs a new confirmation. Idempotency and one-order-per-proposal
constraints prevent duplicate acceptance; persisted conversations and receipts survive restarts.

## Code map

| Responsibility | Main source |
| --- | --- |
| Browser screens and generated API types | [frontend/src](../frontend/src) |
| HTTP routes, sessions, Origin/CSRF and SSE | [api.py](../src/aimo/api.py), [auth.py](../src/aimo/auth.py) |
| Conversation recovery and customer confirmation | [conversations.py](../src/aimo/conversations.py) |
| Provider loop and allowed typed tools | [agent.py](../src/aimo/agent.py), [chat_schemas.py](../src/aimo/chat_schemas.py) |
| Shared purchasing entry points | [service.py](../src/aimo/service.py) |
| Catalog normalization, ingestion and hybrid search | [catalog.py](../src/aimo/catalog.py), [ingest.py](../src/aimo/ingest.py), [search.py](../src/aimo/search.py) |
| Commercial evidence and quantity snapshots | [upstream.py](../src/aimo/upstream.py), [purchases.py](../src/aimo/purchases.py) |
| Policy decisions and durable purchase workflow | [approval_policy.py](../src/aimo/approval_policy.py), [approval_workflow.py](../src/aimo/approval_workflow.py) |
| Purchasing contracts and database schema | [schemas.py](../src/aimo/schemas.py), [migrations](../migrations) |
