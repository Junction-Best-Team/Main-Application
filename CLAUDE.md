@AGENTS.md

## Branch and pull request workflow

- Start each task branch from the latest `origin/develop`.
- Always target `develop` for feature, fix, documentation, and maintenance PRs; use `gh pr create --base develop` and verify the base before creating or merging.
- Request a teammate review before merging into `develop`. Require one approval of the latest commit from a teammate with write access and no outstanding requests for changes, unless the PR has `skip-review`. Check the `review-policy` status; do not add the bypass label without the user's instruction.
- Do not commit or push directly to `develop` or `main`, and do not force-push either branch.
- Only a release PR from `develop` may target `main`, and only when the user explicitly requests that release.
