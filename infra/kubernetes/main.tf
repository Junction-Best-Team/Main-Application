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
  data = merge({ for key, value in var.runtime_secrets : key => value if !contains(["LLM_API_KEY", "SEARCH_API_KEY"], key) }, {
    DATABASE_URL            = var.database_url
    APPROVAL_SESSION_SECRET = var.session_secret
  })
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
    LLM_BASE_URL            = var.llm_base_url
    LLM_MODEL               = var.llm_model
    LLM_TIMEOUT_SECONDS     = "20"
    LLM_MAX_TOOL_ROUNDS     = "20"
    PUBLIC_BASE_URL         = "https://${var.hostname}"
    SECURE_COOKIES          = "true"
    RECIPE_PLANNING_ENABLED = tostring(var.recipe_planning_enabled)
    UPSTREAM_MODE           = var.upstream_mode
    VALIO_AIMO_BASE_URL     = "https://junction26.valioaimo.fi"
    EMBEDDING_BACKEND       = "sentence_transformers"
    # Model name/revision use the application's shared image/runtime pin.
    HF_HUB_OFFLINE         = "1"
    TOKENIZERS_PARALLELISM = "false"
  }
}

resource "kubernetes_secret_v1" "worker" {
  metadata {
    name      = "aimo-worker-runtime"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  data = merge({ for key, value in var.runtime_secrets : key => value if contains([
    "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "VALIO_AIMO_API_KEY",
    "SEARCH_API_KEY", "EMBEDDING_BACKEND", "EMBEDDING_MODEL", "EMBEDDING_MODEL_REVISION",
    "SEARCH_TIMEOUT_SECONDS", "SEARCH_MAX_ATTEMPTS", "EMBEDDING_BATCH_SIZE",
    "EMBEDDING_WORKERS", "RERANK_ENABLED", "RERANK_CANDIDATES"
    ], key) }, {
    DATABASE_URL = var.database_url
  })
  # Releases own only these fields; Terraform retains all other Secret settings.
  lifecycle {
    ignore_changes = [data["LLM_API_KEY"], data["LLM_BASE_URL"], data["LLM_MODEL"]]
  }
}

locals {
  apps = {
    api = {
      image = var.image, command = ["serve"], port = 8000, uid = 10001
      cpu   = "100m", memory = "192Mi", memory_limit = "512Mi"
    }
    worker = {
      image = var.worker_image, command = ["worker"], port = 8001, uid = 10001
      cpu   = "500m", memory = "1Gi", memory_limit = "2Gi"
    }
    frontend = {
      image = var.frontend_image, command = [], port = 8080, uid = 101
      cpu   = "50m", memory = "32Mi", memory_limit = "128Mi"
    }
  }
}

resource "kubernetes_deployment_v1" "apps" {
  for_each = local.apps
  metadata {
    name      = "aimo-${each.key}"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
    labels    = { "app.kubernetes.io/part-of" = "aimo", "app.kubernetes.io/component" = each.key }
  }
  spec {
    replicas = var.app_replicas
    strategy { type = "Recreate" }
    selector { match_labels = { app = "aimo-${each.key}" } }
    template {
      metadata {
        labels = { app = "aimo-${each.key}", "app.kubernetes.io/part-of" = "aimo", "app.kubernetes.io/component" = each.key }
        annotations = {
          "configuration-hash" = sha256(jsonencode({
            config = each.key == "frontend" ? {} : kubernetes_config_map_v1.runtime.data
            secret = each.key == "frontend" ? {} : each.key == "worker" ? kubernetes_secret_v1.worker.data : kubernetes_secret_v1.runtime.data
            ca     = each.key == "frontend" ? {} : kubernetes_secret_v1.database_ca.data
          }))
        }
      }
      spec {
        automount_service_account_token  = false
        termination_grace_period_seconds = each.key == "worker" ? 120 : 30
        security_context {
          run_as_non_root = true
          run_as_user     = each.value.uid
          run_as_group    = each.value.uid
          fs_group        = each.value.uid
          seccomp_profile { type = "RuntimeDefault" }
        }
        dynamic "image_pull_secrets" {
          for_each = var.image_pull_secret_names
          content {
            name = image_pull_secrets.value
          }
        }
        container {
          name  = each.key
          image = each.value.image
          args  = each.value.command
          port {
            name           = "http"
            container_port = each.value.port
          }
          dynamic "env_from" {
            for_each = each.key == "frontend" ? [] : [1]
            content {
              config_map_ref { name = kubernetes_config_map_v1.runtime.metadata[0].name }
            }
          }
          dynamic "env_from" {
            for_each = each.key == "frontend" ? [] : [1]
            content {
              secret_ref { name = each.key == "worker" ? kubernetes_secret_v1.worker.metadata[0].name : kubernetes_secret_v1.runtime.metadata[0].name }
            }
          }
          resources {
            requests = { cpu = each.value.cpu, memory = each.value.memory }
            limits   = { cpu = "2", memory = each.value.memory_limit }
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
          dynamic "volume_mount" {
            for_each = each.key == "frontend" ? [] : [1]
            content {
              name       = "database-ca"
              mount_path = "/etc/aimo-db"
              read_only  = true
            }
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
        dynamic "volume" {
          for_each = each.key == "frontend" ? [] : [1]
          content {
            name = "database-ca"
            secret { secret_name = kubernetes_secret_v1.database_ca.metadata[0].name }
          }
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
      error_message = "Set runtime_secrets.FORWARDED_ALLOW_IPS to actual trusted ingress IPs/CIDRs before serving."
    }
    ignore_changes = [spec[0].template[0].spec[0].container[0].image]
  }
}

resource "kubernetes_service_v1" "apps" {
  for_each = local.apps
  metadata {
    name      = "aimo-${each.key}"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  spec {
    type     = "ClusterIP"
    selector = { app = "aimo-${each.key}" }
    port {
      name        = "http"
      port        = 80
      target_port = "http"
    }
  }
}

# Preserve Terraform ownership during the one-time monolith -> API rename.
moved {
  from = kubernetes_deployment_v1.aimo
  to   = kubernetes_deployment_v1.apps["api"]
}
moved {
  from = kubernetes_service_v1.aimo
  to   = kubernetes_service_v1.apps["api"]
}
