
## Chat execution budget — 2026-11-15

Raised the whole-response deadline from 360 to 600 seconds and model rounds from
40 to 80. Worker lease/shutdown is 660 seconds, health freshness is 690 seconds,
and worker rollout/rollback waits are 15 minutes. Existing installations need
the runtime configuration and shutdown grace updated as documented in deploy/README.md.

Verification: 218 core regressions passed with authored providers/clocks and an
isolated fixture database; strict API sweep passed all 11 checks. Ruff, shell
syntax, Terraform format/validation, 21 mocked Kubernetes plan tests and 63
infrastructure unit tests passed. No live model/supplier calls, Terraform apply,
deployment or merge was performed.
