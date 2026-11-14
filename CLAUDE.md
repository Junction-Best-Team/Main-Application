@AGENTS.md

## Branch and pull request workflow

- Start each task branch from the latest `origin/develop`.
- Always target `develop` for feature, fix, documentation, and maintenance PRs; use `gh pr create --base develop` and verify the base before creating or merging.
- Wait for the latest CI run to pass, then you may self-merge without a human approval. Request teammate review for risky authentication, schema, or shared-interface changes. Reviews are optional; `skip-review` does not bypass CI.
- Do not commit or push directly to `develop` or `main`, and do not force-push either branch.
- Only a release PR from `develop` may target `main`, and only when the user explicitly requests that release.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `Junction-Best-Team/Main-Application` (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` plus `docs/adr/`, created lazily. See `docs/agents/domain.md`.
