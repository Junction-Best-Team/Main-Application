# Scheduled product-catalog ingestion: a temporary pod runs `aimo sync-catalog` from the
# worker image, exits, and never runs inside the API or worker processes. Unchanged
# snapshots are skipped, so the daily run is cheap. See docs/catalog-sync.md.

locals {
  catalog_sync_enabled = var.catalog_sync.enabled
  # Supplier download, embedding profile and (hosted) embedding credentials only. No
  # browser session key, conversational LLM key, admin URL or seed credentials.
  catalog_sync_secret_keys = [
    "VALIO_AIMO_API_KEY", "SEARCH_API_KEY", "EMBEDDING_BACKEND", "EMBEDDING_MODEL",
    "EMBEDDING_MODEL_REVISION", "SEARCH_TIMEOUT_SECONDS", "SEARCH_MAX_ATTEMPTS",
    "EMBEDDING_BATCH_SIZE", "EMBEDDING_WORKERS",
  ]
  catalog_sync_labels = { app = "aimo-catalog-sync", "app.kubernetes.io/part-of" = "aimo", "app.kubernetes.io/component" = "catalog-sync" }
}

resource "kubernetes_secret_v1" "catalog_sync" {
  count = local.catalog_sync_enabled ? 1 : 0
  metadata {
    name      = "aimo-catalog-sync"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  data = merge(
    { for key, value in var.runtime_secrets : key => value if contains(local.catalog_sync_secret_keys, key) },
    { DATABASE_URL = var.catalog_sync_database_url == null ? "" : var.catalog_sync_database_url },
  )
  lifecycle {
    precondition {
      condition     = var.catalog_sync_database_url != null && var.catalog_sync_database_url != var.database_url
      error_message = "Catalog sync needs its own restricted database URL (catalog_sync_database_url), distinct from the runtime URL."
    }
    precondition {
      condition     = trimspace(lookup(var.runtime_secrets, "VALIO_AIMO_API_KEY", "")) != ""
      error_message = "Catalog sync downloads the supplier snapshot; set runtime_secrets.VALIO_AIMO_API_KEY."
    }
  }
}

resource "kubernetes_cron_job_v1" "catalog_sync" {
  count = local.catalog_sync_enabled ? 1 : 0
  metadata {
    name      = "aimo-catalog-sync"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
    labels    = local.catalog_sync_labels
  }
  spec {
    schedule                      = var.catalog_sync.schedule
    timezone                      = var.catalog_sync.timezone
    suspend                       = var.catalog_sync.suspend
    concurrency_policy            = "Forbid"
    starting_deadline_seconds     = 3600
    successful_jobs_history_limit = 3
    failed_jobs_history_limit     = 3
    job_template {
      metadata { labels = local.catalog_sync_labels }
      spec {
        backoff_limit           = var.catalog_sync.backoff_limit
        active_deadline_seconds = var.catalog_sync.active_deadline_seconds
        # Also bounds manual `kubectl create job --from=cronjob/...` recovery runs.
        ttl_seconds_after_finished = 604800
        template {
          metadata { labels = local.catalog_sync_labels }
          spec {
            restart_policy                   = "Never"
            automount_service_account_token  = false
            termination_grace_period_seconds = 30
            security_context {
              run_as_non_root = true
              run_as_user     = 10001
              run_as_group    = 10001
              fs_group        = 10001
              seccomp_profile { type = "RuntimeDefault" }
            }
            dynamic "image_pull_secrets" {
              for_each = var.image_pull_secret_names
              content { name = image_pull_secrets.value }
            }
            container {
              name  = "catalog-sync"
              image = var.worker_image
              args  = ["sync-catalog"]
              env_from {
                config_map_ref { name = kubernetes_config_map_v1.runtime.metadata[0].name }
              }
              env_from {
                secret_ref { name = kubernetes_secret_v1.catalog_sync[0].metadata[0].name }
              }
              env {
                name  = "CATALOG_WORK_DIR"
                value = "/tmp"
              }
              resources {
                requests = {
                  cpu                 = var.catalog_sync.cpu_request
                  memory              = var.catalog_sync.memory_request
                  "ephemeral-storage" = var.catalog_sync.storage_request
                }
                limits = {
                  cpu                 = var.catalog_sync.cpu_limit
                  memory              = var.catalog_sync.memory_limit
                  "ephemeral-storage" = var.catalog_sync.storage_limit
                }
              }
              security_context {
                run_as_non_root            = true
                allow_privilege_escalation = false
                read_only_root_filesystem  = true
                capabilities { drop = ["ALL"] }
              }
              volume_mount {
                name       = "tmp"
                mount_path = "/tmp"
              }
              volume_mount {
                name       = "database-ca"
                mount_path = "/etc/aimo-db"
                read_only  = true
              }
            }
            volume {
              name = "tmp"
              empty_dir { size_limit = var.catalog_sync.storage_limit }
            }
            volume {
              name = "database-ca"
              secret { secret_name = kubernetes_secret_v1.database_ca.metadata[0].name }
            }
          }
        }
      }
    }
  }
  lifecycle {
    # Releases keep the CronJob on the deployed worker digest, like the Deployments.
    ignore_changes = [spec[0].job_template[0].spec[0].template[0].spec[0].container[0].image]
  }
}
