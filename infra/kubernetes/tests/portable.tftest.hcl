mock_provider "kubernetes" {}
mock_provider "helm" {}

variables {
  worker_image    = "ghcr.io/junction-best-team/main-application:worker-test"
  frontend_image  = "ghcr.io/junction-best-team/main-application:frontend-test"
  image           = "ghcr.io/junction-best-team/main-application:test-commit"
  hostname        = "aimo.test.example.com"
  acme_email      = "demo@example.com"
  database_url    = "postgresql://test:synthetic@postgres.test:5432/aimo?sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
  database_ca     = "synthetic-test-ca"
  session_secret  = "synthetic-test-session-secret-at-least-32-chars"
  runtime_secrets = { FORWARDED_ALLOW_IPS = "10.23.0.0/24" }
}

run "safe_initial_plan" {
  command = plan
  assert {
    condition     = kubernetes_deployment_v1.apps["worker"].spec[0].template[0].spec[0].termination_grace_period_seconds == 240
    error_message = "Worker shutdown must leave room for a 180-second chat turn and final persistence."
  }
  assert {
    condition     = kubernetes_deployment_v1.apps["api"].spec[0].replicas == "0" && length(kubernetes_job_v1.bootstrap) == 0
    error_message = "Initial setup must not start the app or run privileged setup jobs."
  }
  assert {
    condition     = kubernetes_service_v1.apps["api"].spec[0].type == "ClusterIP"
    error_message = "The app should be reachable only through the HTTPS ingress."
  }
  assert {
    condition     = length(helm_release.ingress) == 1 && yamldecode(helm_release.ingress[0].values[0]).persistence.enabled
    error_message = "Install one portable ingress controller and persist its ACME certificates."
  }
  assert {
    condition     = kubernetes_config_map_v1.runtime.data.SECURE_COOKIES == "true" && kubernetes_config_map_v1.runtime.data.UPSTREAM_MODE == "live"
    error_message = "Use secure cookies and live supplier data by default; fixture is an explicit opt-in."
  }
  assert {
    condition     = kubernetes_deployment_v1.apps["api"].spec[0].template[0].spec[0].security_context[0].run_as_non_root && kubernetes_deployment_v1.apps["api"].spec[0].template[0].spec[0].container[0].security_context[0].run_as_non_root
    error_message = "The container must not override the pod's non-root requirement; restricted admission rejects an explicit false value."
  }
}

run "restricted_setup_plan" {
  command = plan
  variables {
    bootstrap_generation = "demo-v1"
    bootstrap_credentials = {
      database_url   = "postgresql://synthetic-admin@postgres.test/aimo"
      database_user  = "aimo_runtime"
      buyer_password = "synthetic-password-at-least-12-chars"
    }
  }
  assert {
    condition     = kubernetes_job_v1.bootstrap[0].spec[0].template[0].spec[0].security_context[0].run_as_non_root && kubernetes_job_v1.bootstrap[0].spec[0].template[0].spec[0].container[0].security_context[0].run_as_non_root
    error_message = "The setup container must satisfy the namespace's restricted non-root admission policy."
  }
  assert {
    condition     = [for source in kubernetes_job_v1.bootstrap[0].spec[0].template[0].spec[0].container[0].env_from : try(source.secret_ref[0].name, "")] == ["aimo-bootstrap"]
    error_message = "Setup no longer imports the catalog; it must not receive session, provider or supplier Secrets."
  }
  assert {
    condition     = length(kubernetes_cron_job_v1.catalog_sync) == 0
    error_message = "Catalog sync stays disabled until explicitly enabled."
  }
}

run "setup_grants_the_catalog_sync_role" {
  command = plan
  variables {
    bootstrap_generation = "demo-v1"
    bootstrap_credentials = {
      database_url               = "postgresql://synthetic-admin@postgres.test/aimo"
      database_user              = "aimo_runtime"
      buyer_password             = "synthetic-password-at-least-12-chars"
      catalog_sync_database_user = "aimo_catalog_sync"
    }
    migration_credentials = {
      database_url               = "postgresql://synthetic-owner@postgres.test/aimo?sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
      database_user              = "aimo_runtime"
      catalog_sync_database_user = "aimo_catalog_sync"
    }
  }
  assert {
    condition     = kubernetes_secret_v1.bootstrap[0].data.CATALOG_SYNC_DATABASE_USER == "aimo_catalog_sync" && kubernetes_secret_v1.migration[0].data.CATALOG_SYNC_DATABASE_USER == "aimo_catalog_sync"
    error_message = "Setup and every release migration must refresh the catalog-sync grants."
  }
}

run "reject_catalog_role_equal_to_runtime_role" {
  command = plan
  variables {
    migration_credentials = {
      database_url               = "postgresql://synthetic-owner@postgres.test/aimo?sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
      database_user              = "aimo_runtime"
      catalog_sync_database_user = "aimo_runtime"
    }
  }
  expect_failures = [var.migration_credentials]
}

run "catalog_sync_cronjob" {
  command = plan
  variables {
    catalog_sync              = { enabled = true }
    catalog_sync_database_url = "postgresql://catalog:synthetic@postgres.test:5432/aimo?sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
    runtime_secrets = {
      FORWARDED_ALLOW_IPS = "10.23.0.0/24"
      VALIO_AIMO_API_KEY  = "synthetic-supplier-key"
      LLM_API_KEY         = "synthetic-llm-key"
      SEARCH_API_KEY      = "synthetic-search-key"
      GEMINI_API_KEY      = "synthetic-google-key"
      CLOUDINARY_URL      = "cloudinary://synthetic:synthetic@demo"
    }
  }
  assert {
    condition = (
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].schedule == "30 3 * * *" &&
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].timezone == "Europe/Helsinki" &&
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].concurrency_policy == "Forbid" &&
      !kubernetes_cron_job_v1.catalog_sync[0].spec[0].suspend
    )
    error_message = "Daily schedule with an explicit timezone and Forbid concurrency."
  }
  assert {
    condition = (
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].successful_jobs_history_limit == 3 &&
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].failed_jobs_history_limit == 3 &&
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].backoff_limit == 2 &&
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].active_deadline_seconds == 3600
    )
    error_message = "Bounded retries, execution deadline and Job history."
  }
  assert {
    condition = (
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].container[0].args == tolist(["sync-catalog"]) &&
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].container[0].image == var.worker_image
    )
    error_message = "Reuse the pinned worker image with the sync-catalog command."
  }
  assert {
    condition = alltrue([
      for key in ["cpu", "memory", "ephemeral-storage"] : (
        contains(keys(kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].container[0].resources[0].requests), key) &&
        contains(keys(kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].container[0].resources[0].limits), key)
      )
    ]) && kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].volume[0].empty_dir[0].size_limit == "1Gi"
    error_message = "Explicit CPU, memory and temporary-storage requests/limits with a bounded download volume."
  }
  assert {
    condition = (
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].security_context[0].run_as_non_root &&
      kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].container[0].security_context[0].read_only_root_filesystem &&
      !kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].container[0].security_context[0].allow_privilege_escalation &&
      !kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].automount_service_account_token
    )
    error_message = "Non-root, read-only root, no privilege escalation, no API token."
  }
  assert {
    condition = (
      [for source in kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].container[0].env_from : try(source.secret_ref[0].name, "")] == ["", "aimo-catalog-sync"]
    )
    error_message = "The ingestion pod must use only its own Secret, never the API or worker runtime Secrets."
  }
  assert {
    condition = (
      kubernetes_secret_v1.catalog_sync[0].data.DATABASE_URL == var.catalog_sync_database_url &&
      kubernetes_secret_v1.catalog_sync[0].data.VALIO_AIMO_API_KEY == "synthetic-supplier-key" &&
      kubernetes_secret_v1.catalog_sync[0].data.SEARCH_API_KEY == "synthetic-search-key" &&
      kubernetes_secret_v1.catalog_sync[0].data.GEMINI_API_KEY == "synthetic-google-key" &&
      length(setintersection(toset(keys(kubernetes_secret_v1.catalog_sync[0].data)), toset(["LLM_API_KEY", "CLOUDINARY_URL", "APPROVAL_SESSION_SECRET", "FORWARDED_ALLOW_IPS", "BOOTSTRAP_DATABASE_URL", "RUNTIME_DATABASE_USER"]))) == 0
    )
    error_message = "Catalog sync gets supplier, embedding and catalog-role database credentials only."
  }
}

run "suspended_catalog_sync_with_custom_schedule" {
  command = plan
  variables {
    catalog_sync              = { enabled = true, suspend = true, schedule = "0 5 * * 1", timezone = "UTC", memory_limit = "4Gi" }
    catalog_sync_database_url = "postgresql://catalog:synthetic@postgres.test:5432/aimo?sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
    runtime_secrets           = { FORWARDED_ALLOW_IPS = "10.23.0.0/24", VALIO_AIMO_API_KEY = "synthetic-supplier-key" }
  }
  assert {
    condition     = kubernetes_cron_job_v1.catalog_sync[0].spec[0].suspend && kubernetes_cron_job_v1.catalog_sync[0].spec[0].timezone == "UTC" && kubernetes_cron_job_v1.catalog_sync[0].spec[0].job_template[0].spec[0].template[0].spec[0].container[0].resources[0].limits.memory == "4Gi"
    error_message = "Suspension, schedule, timezone and resources are configurable."
  }
}

run "reject_catalog_sync_without_its_own_database_role" {
  command = plan
  variables {
    catalog_sync    = { enabled = true }
    runtime_secrets = { FORWARDED_ALLOW_IPS = "10.23.0.0/24", VALIO_AIMO_API_KEY = "synthetic-supplier-key" }
  }
  expect_failures = [kubernetes_secret_v1.catalog_sync]
}

run "reject_catalog_sync_with_the_runtime_database_url" {
  command = plan
  variables {
    catalog_sync              = { enabled = true }
    catalog_sync_database_url = "postgresql://test:synthetic@postgres.test:5432/aimo?sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
    runtime_secrets           = { FORWARDED_ALLOW_IPS = "10.23.0.0/24", VALIO_AIMO_API_KEY = "synthetic-supplier-key" }
  }
  expect_failures = [kubernetes_secret_v1.catalog_sync]
}

run "reject_catalog_sync_without_supplier_key" {
  command = plan
  variables {
    catalog_sync              = { enabled = true }
    catalog_sync_database_url = "postgresql://catalog:synthetic@postgres.test:5432/aimo?sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
  }
  expect_failures = [kubernetes_secret_v1.catalog_sync]
}

run "reject_unbounded_catalog_sync" {
  command = plan
  variables {
    catalog_sync = { enabled = true, backoff_limit = 10 }
  }
  expect_failures = [var.catalog_sync]
}

run "reject_catalog_sync_without_timezone" {
  command = plan
  variables {
    catalog_sync = { enabled = true, timezone = " " }
  }
  expect_failures = [var.catalog_sync]
}

run "existing_cluster_ingress" {
  command = plan
  variables {
    install_ingress = false
    ingress_class   = "existing-controller"
    tls_secret_name = "existing-tls"
  }
  assert {
    condition     = length(helm_release.ingress) == 0 && kubernetes_ingress_v1.aimo.spec[0].ingress_class_name == "existing-controller"
    error_message = "Existing ingress must not create a second load balancer."
  }
}

run "reject_unverified_database_tls" {
  command = plan
  variables { database_url = "postgresql://test:synthetic@postgres.test/aimo?sslmode=disable" }
  expect_failures = [var.database_url]
}

run "reject_serving_without_trusted_proxy" {
  command = plan
  variables {
    app_replicas    = 1
    runtime_secrets = {}
  }
  expect_failures = [kubernetes_deployment_v1.apps]
}

run "reject_wildcard_proxy_trust" {
  command = plan
  variables {
    app_replicas    = 1
    runtime_secrets = { FORWARDED_ALLOW_IPS = "*" }
  }
  expect_failures = [kubernetes_deployment_v1.apps]
}

run "reject_import_with_serving_app" {
  command = plan
  variables {
    app_replicas         = 1
    bootstrap_generation = "demo-v1"
    bootstrap_credentials = {
      database_url   = "postgresql://synthetic-admin@postgres.test/aimo"
      database_user  = "aimo_runtime"
      buyer_password = "synthetic-password-at-least-12-chars"
    }
  }
  expect_failures = [kubernetes_job_v1.bootstrap]
}

run "separate_apps" {
  command = plan
  variables {
    runtime_secrets = {
      FORWARDED_ALLOW_IPS = "10.23.0.0/24"
      SEARCH_API_KEY      = "synthetic-search-key"
      EMBEDDING_BACKEND   = "openrouter"
    }
  }
  assert {
    condition     = length(kubernetes_deployment_v1.apps) == 3 && length(kubernetes_service_v1.apps) == 3
    error_message = "Frontend, API and worker must be independent deployments and services."
  }
  assert {
    condition     = length(kubernetes_deployment_v1.apps["frontend"].spec[0].template[0].spec[0].container[0].env_from) == 0
    error_message = "The static frontend must not receive database/session/provider secrets."
  }
  assert {
    condition     = !contains(keys(kubernetes_secret_v1.worker.data), "APPROVAL_SESSION_SECRET") && !contains(keys(kubernetes_secret_v1.runtime.data), "LLM_API_KEY")
    error_message = "Worker must not receive session signing keys; API must not receive provider keys."
  }
  assert {
    condition     = !contains(keys(kubernetes_secret_v1.runtime.data), "SEARCH_API_KEY") && kubernetes_secret_v1.worker.data.SEARCH_API_KEY == "synthetic-search-key"
    error_message = "Only the worker/importer may receive the hosted search credential."
  }
  assert {
    condition     = kubernetes_secret_v1.runtime.data.EMBEDDING_BACKEND == "openrouter" && kubernetes_secret_v1.worker.data.EMBEDDING_BACKEND == "openrouter"
    error_message = "API readiness and worker search must use the same catalog profile."
  }
}

run "migration_secret_is_separate_from_runtime_and_bootstrap" {
  command = plan
  variables {
    migration_credentials = {
      database_url  = "postgresql://synthetic-owner@postgres.test/aimo?sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
      database_user = "aimo_runtime"
    }
  }
  assert {
    condition     = length(kubernetes_secret_v1.migration) == 1 && length(kubernetes_job_v1.bootstrap) == 0
    error_message = "Persistent release credentials must not cause bootstrap/import to run."
  }
  assert {
    condition     = kubernetes_secret_v1.migration[0].metadata[0].name == "aimo-migration" && kubernetes_secret_v1.migration[0].data.DATABASE_URL == var.migration_credentials.database_url
    error_message = "The dedicated migration Secret must contain the schema-owner URL."
  }
  assert {
    condition     = kubernetes_secret_v1.runtime.data.DATABASE_URL == var.database_url && kubernetes_secret_v1.worker.data.DATABASE_URL == var.database_url
    error_message = "API and worker must retain restricted runtime URLs."
  }
  assert {
    condition = alltrue([
      for component in ["api", "worker"] : (
        length(kubernetes_deployment_v1.apps[component].spec[0].template[0].spec[0].container[0].env_from) == 2 &&
        kubernetes_deployment_v1.apps[component].spec[0].template[0].spec[0].container[0].env_from[1].secret_ref[0].name != "aimo-migration"
      )
    ])
    error_message = "Application pods must not reference migration credentials."
  }
}

run "reject_migration_credentials_without_tls" {
  command = plan
  variables {
    migration_credentials = {
      database_url  = "postgresql://synthetic-owner@postgres.test/aimo"
      database_user = "aimo_runtime"
    }
  }
  expect_failures = [var.migration_credentials]
}

run "reject_owner_credentials_in_runtime_map" {
  command = plan
  variables { runtime_secrets = { BOOTSTRAP_DATABASE_URL = "synthetic-forbidden-url" } }
  expect_failures = [var.runtime_secrets]
}
