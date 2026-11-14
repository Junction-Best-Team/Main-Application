# Architecture diagrams

Architecture and purchasing-flow diagrams with explicit component responsibilities, generated using **free D2 0.9.0 + ELK**.
No paid layout engine or hosted account is required.

| Diagram | View | Editable source |
| --- | --- | --- |
| System architecture | [SVG](architecture.svg) · [PNG](architecture.png) | [architecture.d2](architecture.d2) |
| Agent harness | [SVG](harness.svg) · [PNG](harness.png) | [harness.d2](harness.d2) |

## Editing

Edit the `.d2` files locally or paste them into the [D2 playground](https://play.d2lang.com/).
Use ELK as the layout engine. Render SVG from the repository root:

```sh
d2 docs/diagrams/architecture.d2 docs/diagrams/architecture.svg
d2 docs/diagrams/harness.d2 docs/diagrams/harness.svg
```

D2 also supports PNG output by changing the output extension to `.png`; this needs its
browser export dependencies. Update the source, SVG and PNG together in the same PR.
Keep each component label to its role and two or three supporting lines.
Detailed contracts remain in [architecture.md](../architecture.md).

## Reading the views

- The React web app executes in the buyer’s browser. Nginx serves its files;
  Traefik routes HTTPS to Nginx or the FastAPI API. These are distinct responsibilities.
- Blue: application components. Green: people, data and persisted results. Purple:
  external AI/supplier providers. Gold: deterministic purchasing checks.
- The numbered path is buyer → API → saved PostgreSQL turn → polling worker → saved reply
  → API → browser. The worker is continuously running: it polls for work, rather than
  receiving a direct API call. It waits one second after an empty poll.
- The frontend server, API and worker are separate workloads in the same Kubernetes
  cluster. The green stores are logical areas of one managed PostgreSQL database
  outside that cluster, not three databases.
- PostgreSQL is both the application database and durable job queue. It also stores
  catalog/recipe vectors, policies, confirmations, mock orders and audit history.
- The worker can use local E5 embeddings; hosted search and recipe planning require
  explicit activation. OpenRouter is the configurable conversational-provider default.
- The import job is explicit; the dashed catalog arrow is a batch write. Valio lookups
  use live or labelled fixture evidence. All orders remain mocks, with no reservation.
- The harness reads across the top row, back across the middle, then across the bottom.
  Changed terms or failed checks require resolution/review instead of a receipt.

Checked against `develop` commit `783c7ae3d364ced082cca47ef3ba7cc209df19c4`,
2026-11-14. These are source topology views, not a live cluster inventory.
See [separate apps](../separate-apps.md), [agent tools](../../src/aimo/agent_tools.py),
[worker](../../src/aimo/worker.py), [migrations](../../migrations) and
[Kubernetes definitions](../../infra/kubernetes/main.tf) for implementation details.
