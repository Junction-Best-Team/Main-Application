terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.38.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17.0"
    }
  }
}

# Supply kubeconfig from ANY conformant cluster. No cloud provider is used here.
provider "kubernetes" {
  config_path    = pathexpand(var.kubeconfig_path)
  config_context = var.kubeconfig_context
}

provider "helm" {
  kubernetes {
    config_path    = pathexpand(var.kubeconfig_path)
    config_context = var.kubeconfig_context
  }
}

resource "kubernetes_namespace_v1" "aimo" {
  metadata {
    name = var.namespace
    labels = {
      "pod-security.kubernetes.io/enforce" = "restricted"
    }
  }
}

resource "kubernetes_secret_v1" "runtime" {
  metadata {
    name      = "aimo-runtime"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  data = merge(var.runtime_secrets, {
    DATABASE_URL            = var.database_url
    APPROVAL_SESSION_SECRET = var.session_secret
  })
  # Releases own only these fields; Terraform retains all other Secret settings.
  lifecycle {
    ignore_changes = [data["LLM_API_KEY"], data["LLM_BASE_URL"], data["LLM_MODEL"]]
  }
}

resource "kubernetes_secret_v1" "database_ca" {
  metadata {
    name      = "aimo-database-ca"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  data = { "ca.crt" = var.database_ca }
}

resource "kubernetes_config_map_v1" "runtime" {
  metadata {
    name      = "aimo-config"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  data = {
    LLM_BASE_URL        = var.llm_base_url
    LLM_MODEL           = var.llm_model
    LLM_TIMEOUT_SECONDS = "20"
    LLM_MAX_TOOL_ROUNDS = "20"
    PUBLIC_BASE_URL     = "https://${var.hostname}"
    SECURE_COOKIES      = "true"
    UPSTREAM_MODE       = var.upstream_mode
    VALIO_AIMO_BASE_URL = "https://junction26.valioaimo.fi"
    EMBEDDING_BACKEND   = "sentence_transformers"
    # Model name/revision use the application's shared image/runtime pin.
    HF_HUB_OFFLINE         = "1"
    TOKENIZERS_PARALLELISM = "false"
  }
}

resource "kubernetes_deployment_v1" "aimo" {
  metadata {
    name      = "aimo"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  spec {
    replicas = var.app_replicas
    # One small worker: avoid requiring two model-serving pods during a rollout.
    strategy { type = "Recreate" }
    selector { match_labels = { app = "aimo" } }
    template {
      metadata {
        labels = { app = "aimo" }
        annotations = {
          "configuration-hash" = sha256(jsonencode({
            config = kubernetes_config_map_v1.runtime.data
            secret = kubernetes_secret_v1.runtime.data
            ca     = kubernetes_secret_v1.database_ca.data
          }))
        }
      }
      spec {
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
          name  = "aimo"
          image = var.image
          args  = ["serve"]
          port {
            name           = "http"
            container_port = 8000
          }
          env_from {
            config_map_ref { name = kubernetes_config_map_v1.runtime.metadata[0].name }
          }
          env_from {
            secret_ref { name = kubernetes_secret_v1.runtime.metadata[0].name }
          }
          resources {
            requests = { cpu = "500m", memory = "1Gi" }
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
          startup_probe {
            http_get {
              path = "/health/ready"
              port = "http"
            }
            period_seconds    = 5
            failure_threshold = 60
          }
          readiness_probe {
            http_get {
              path = "/health/ready"
              port = "http"
            }
            period_seconds = 10
          }
          liveness_probe {
            http_get {
              path = "/health/live"
              port = "http"
            }
            period_seconds = 10
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
      }
    }
  }
  timeouts { create = "15m" }
  lifecycle {
    precondition {
      condition = var.app_replicas == 0 || (
        trimspace(lookup(var.runtime_secrets, "FORWARDED_ALLOW_IPS", "")) != "" &&
        !strcontains(lookup(var.runtime_secrets, "FORWARDED_ALLOW_IPS", ""), "*")
      )
      error_message = "Before serving behind ingress, set runtime_secrets.FORWARDED_ALLOW_IPS to the actual trusted proxy IPs/CIDRs, never *."
    }
    # Terraform supplies the first image; release CI owns subsequent image updates.
    ignore_changes = [spec[0].template[0].spec[0].container[0].image]
  }
}

resource "kubernetes_service_v1" "aimo" {
  metadata {
    name      = "aimo"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  spec {
    type     = "ClusterIP"
    selector = { app = "aimo" }
    port {
      name        = "http"
      port        = 80
      target_port = "http"
    }
  }
}
