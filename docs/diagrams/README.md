# Editable architecture diagrams

These are original Excalidraw diagrams of the implemented Junction application and its
configured hosting topology, checked against `develop` commit
`783c7ae3d364ced082cca47ef3ba7cc209df19c4` on 2026-11-14. They are not a live cluster inventory.
All purchasing acceptance remains a persistent mock, without supplier checkout or reservation.

| Diagram | View | Edit | Portable preview |
| --- | --- | --- | --- |
| Full system: services, cluster, database, providers and operations | [SVG](architecture.svg) | [Excalidraw source](architecture.excalidraw) | [PNG](architecture.png) |
| Agent harness: durable execution, typed tools and customer confirmation | [SVG](harness.svg) | [Excalidraw source](harness.excalidraw) | [PNG](harness.png) |

## Open and edit for free

1. Download the `.excalidraw` file from GitHub using **Download raw file**.
2. Open [excalidraw.com](https://excalidraw.com/), then drag the file onto the canvas
   (or choose **Open** from the menu). No paid workspace is needed.
3. Edit the text, shapes and arrows. Each card's shape and text are grouped; ungroup
   when needed. Arrows are editable paths; reposition their endpoints when moving cards.
4. Save the `.excalidraw` file, then export SVG and PNG with a white background in
   light mode. Replace all three files together in the same pull request.
5. Update the snapshot reference above and check the README and architecture page previews.

The native Excalidraw files are the editable source. SVG/PNG are exports of those same scenes,
rendered with the open-source Excalidraw export APIs. No additional application dependency was
added. Repository links are the maintained public entry point; a separate Excalidraw share link
is optional and will need refreshing when the diagram changes.

## Scope and source map

| Area | Checked sources |
| --- | --- |
| Three application boundaries, routes and credential separation | [Separate apps](../separate-apps.md), [Kubernetes app definitions](../../infra/kubernetes/main.tf), [ingress](../../infra/kubernetes/ingress.tf) |
| Claim leases, attempt fencing, retries and saved SSE state | [worker.py](../../src/aimo/worker.py), [conversations.py](../../src/aimo/conversations.py) |
| Bounded model loop, typed tools and optional recipe tools | [agent.py](../../src/aimo/agent.py), [agent_provider.py](../../src/aimo/agent_provider.py), [agent_tools.py](../../src/aimo/agent_tools.py) |
| Purchasing, policy, authority and durable confirmation | [Service](../../src/aimo/service.py), [policy](../../src/aimo/approval_policy.py), [workflow](../../src/aimo/approval_workflow.py), [conversations](../../src/aimo/conversations.py) |
| PostgreSQL tables, catalog generations and vectors | [Migrations](../../migrations), [hosted search](../hosted-search.md), [recipes](../recipes.md) |
| Managed database/VPC, jobs, images and releases | [Cloud stack](../../infra/digitalocean/main.tf), [setup Job](../../infra/kubernetes/setup.tf), [migration Job](../../infra/kubernetes/migrations.tf), [release workflow](../../.github/workflows/deploy.yml) |

Hosted Qwen3 search requires a staged product import and coordinated profile activation;
local E5 remains supported. Recipe planning is separately opt-in and needs explicit dataset
import and reviewed matching evidence. Dashed provider arrows denote optional hosted search;
dashed operator arrows denote explicit batch ingestion. PostgreSQL itself is the durable queue.
The database groupings are logical collections inside one database, not separate databases.
ClusterView is an existing separate operator view, not part of the purchasing request path.

[Detailed architecture and purchase sequence](../architecture.md)
