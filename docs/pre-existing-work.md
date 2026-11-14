# Pre-existing work and reused material

Maintain this log for the final submission. It records provenance and timing; the official submission platform and challenge rules determine the disclosures required.

## Prepared before the event

| Material | Date | Source or author | Prepared beforehand | Built during the event |
| --- | --- | --- | --- | --- |
| Repository preparation files | 2026-11-10 to 2026-11-12 | Prepared locally with Codex for the team | README, shared agent instructions, brief template, environment example, and source-control defaults | To be completed |

Add any starter code or earlier prototypes separately. Describe which parts existed before the event and which parts were created during it.

## Planning during the event

| Material | Date | Source or author | Work performed |
| --- | --- | --- | --- |
| Valio Aimo implementation plan and diagrams | 2026-11-14 | Team-provided research brief and discussions with AI assistants; Codex checked challenge/API documentation, schema and catalog records, and reviewed [PR #1](https://github.com/Junction-Best-Team/Main-Application/pull/1) at `5a14b3fde3448ec2674d8711bbba676d6c6a1667` | Documentation and read-only catalog analysis only. Covers seeded customer rules, four-outcome policy/workflow modules, read-only policy discovery, shared schemas/evidence, a React/TypeScript/Vite approval inbox served by FastAPI, mission-driven approval without chat, concurrent commit enforcement, normal audit history, ingestion/search, and existing-cluster hosting. Both allergen-group overlaps were checked locally. PR #1 live-API findings are attributed reports, not independently repeated calls in this plan. Outbound notifications, policy editing, hash chaining and direct in-agent approval remain deferred. No application implementation or deployment. See [the plan](brief.md). |

## Reused code, data, models, and assets

During the event on 2026-11-14, Codex prepared Terraform infrastructure at the owner's request: a DigitalOcean adapter, portable Kubernetes/Helm deployment, explicit database/catalog setup Job, plan-only tests and a runbook. It builds on PR #2's design and targets PR #4's image/CLI contract; it does not copy the application implementation. No cloud infrastructure was applied. The ingress reuses the upstream Traefik Helm chart 42.4.0 (MIT); Terraform providers are locked in each stack. See [infra/README.md](../infra/README.md).

| Material/version | Source URL | Licence or usage restrictions | Role in the project | Attribution/disclosure needed |
| --- | --- | --- | --- | --- |
| Valio Aimo synthetic catalog, schema, companion data, and API documentation | [Challenge resource portal](https://junction26.valioaimo.fi/) | Sponsor states the synthetic data is for this challenge only; verify any additional submission/distribution requirements | Supplied inputs for design and planned implementation; raw datasets are not committed with the plan | Identify sponsor-provided data and distinguish live lookups, fixtures, and mock order acceptance |

Include frameworks, datasets, model weights, third-party assets, and earlier work as applicable. Record source/version information while building so submission preparation is straightforward.

The plan names intended frameworks and an embedding-model candidate; that is not a claim that their code or model weights have already been integrated. Add exact versions, licences, and actual usage to this log when implementation starts.

## Final review

- [ ] Check the current event and chosen challenge's rules.
- [ ] Complete the log and the official submission disclosure fields.
- [ ] Confirm the repository licence and required third-party attribution.
- [ ] Clearly describe any mocked or simulated functionality in the submission/demo.

Reference: [Junction general terms](https://www.hackjunction.com/terms-of-service).
