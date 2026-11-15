# Verification

## Chat turn throughput — 2026-11-15

- Isolated task worktree started from `origin/develop` at `b1bdd7c`.
- Python lint passed; 625 focused harness/guardrail/tool/activity/provider regressions
  passed, as did the 96-test PR selection and all 11 strict fixture HTTP sweep checks.
- Frontend formatting/lint/type checking/build passed. Terraform formatting,
  Kubernetes validation and all 20 mocked plans passed; 51 infrastructure unit tests passed.
- A real Google chat/guardrail run with an authored in-memory catalog drafted
  carbonara for 200 and saved six of six product matches in 40.09 seconds, using
  one recipe search, one draft, six product searches and one plan publication.
  No basket was prepared because delivery details were absent. A separate run
  preserved five matches and explained the missing shell-egg-to-liquid-egg conversion.
- No deployed-catalog benchmark, supplier request, purchase, merge, deployment or
  Terraform apply was performed. Worker shutdown grace changes are declarative only.
