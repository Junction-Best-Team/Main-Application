resource "kubernetes_secret_v1" "bootstrap" {
  count = var.bootstrap_generation == null ? 0 : 1
  metadata {
    name      = "aimo-bootstrap"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  data = {
    BOOTSTRAP_DATABASE_URL = try(var.bootstrap_credentials.database_url, "")
    RUNTIME_DATABASE_USER  = try(var.bootstrap_credentials.database_user, "")
    DEMO_BUYER_PASSWORD    = try(var.bootstrap_credentials.buyer_password, "")
  }
  lifecycle {
    precondition {
      condition     = var.bootstrap_credentials != null
      error_message = "Provide bootstrap_credentials for the explicit setup Job."
    }
  }
}

resource "kubernetes_config_map_v1" "bootstrap" {
  count = var.bootstrap_generation == null ? 0 : 1
  metadata {
    name      = "aimo-bootstrap-code"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  data = { "bootstrap.py" = file("${path.module}/bootstrap.py") }
}

resource "kubernetes_job_v1" "bootstrap" {
  count = var.bootstrap_generation == null ? 0 : 1
  metadata {
    name      = "aimo-setup-${var.bootstrap_generation}"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  spec {
    backoff_limit = 0
    # No TTL: keep the completed Job until the operator removes setup resources.
    # Otherwise Terraform could recreate the Job on the next apply.
    template {
      metadata { labels = { app = "aimo-setup" } }
      spec {
        restart_policy                  = "Never"
        automount_service_account_token = false
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
          name    = "setup"
          image   = var.worker_image
          command = ["/app/.venv/bin/python", "/setup/bootstrap.py"]
          env_from {
            config_map_ref { name = kubernetes_config_map_v1.runtime.metadata[0].name }
          }
          env_from {
            secret_ref { name = kubernetes_secret_v1.runtime.metadata[0].name }
          }
          env_from {
            secret_ref { name = kubernetes_secret_v1.worker.metadata[0].name }
          }
          env_from {
            secret_ref { name = kubernetes_secret_v1.bootstrap[0].metadata[0].name }
          }
          resources {
            requests = { cpu = "1", memory = "2Gi" }
            limits   = { cpu = "2", memory = "3Gi" }
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
          volume_mount {
            name       = "setup"
            mount_path = "/setup"
            read_only  = true
          }
        }
        volume {
          name = "tmp"
          empty_dir {}
        }
        volume {
          name = "database-ca"
          secret { secret_name = kubernetes_secret_v1.database_ca.metadata[0].name }
        }
        volume {
          name = "setup"
          config_map { name = kubernetes_config_map_v1.bootstrap[0].metadata[0].name }
        }
      }
    }
  }
  wait_for_completion = true
  depends_on          = [kubernetes_deployment_v1.apps]
  timeouts { create = "60m" }
  lifecycle {
    precondition {
      condition     = var.app_replicas == 0
      error_message = "Stop the app (app_replicas=0) for setup/import on the single demo worker."
    }
  }
}
