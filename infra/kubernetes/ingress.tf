# Traefik and ACME work on any cluster with a LoadBalancer implementation and
# dynamic storage. Existing ingress/TLS infrastructure can be used instead.
resource "helm_release" "ingress" {
  count            = var.install_ingress ? 1 : 0
  name             = "junction-ingress"
  namespace        = "junction-ingress"
  create_namespace = true
  repository       = "https://traefik.github.io/charts"
  chart            = "traefik"
  version          = "42.4.0"
  atomic           = true
  timeout          = 600
  skip_crds        = true
  values = [yamlencode({
    deployment     = { replicas = 1 }
    updateStrategy = { type = "Recreate", rollingUpdate = null }
    ingressClass   = { enabled = true, isDefaultClass = false, name = var.ingress_class }
    providers = {
      kubernetesCRD     = { enabled = false }
      kubernetesIngress = { enabled = true, ingressClass = var.ingress_class, publishedService = { enabled = true } }
    }
    service = { spec = { type = "LoadBalancer" }, annotations = var.load_balancer_annotations }
    ports = {
      web = { http = { redirections = { entryPoint = { to = "websecure", scheme = "https", permanent = true } } } }
    }
    persistence        = { enabled = true, size = "1Gi", storageClass = var.storage_class }
    podSecurityContext = { fsGroup = 65532, fsGroupChangePolicy = "OnRootMismatch" }
    resources = {
      requests = { cpu = "100m", memory = "128Mi" }
      limits   = { cpu = "500m", memory = "256Mi" }
    }
    certificatesResolvers = {
      letsencrypt = { acme = { email = var.acme_email, storage = "/data/acme.json", httpChallenge = { entryPoint = "web" } } }
    }
  })]
  lifecycle {
    precondition {
      condition     = can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.acme_email))
      error_message = "Set acme_email before installing the HTTPS ingress controller."
    }
  }
}

resource "kubernetes_ingress_v1" "aimo" {
  metadata {
    name      = "aimo"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
    annotations = var.install_ingress ? {
      "traefik.ingress.kubernetes.io/router.entrypoints"      = "websecure"
      "traefik.ingress.kubernetes.io/router.tls"              = "true"
      "traefik.ingress.kubernetes.io/router.tls.certresolver" = "letsencrypt"
    } : var.ingress_annotations
  }
  spec {
    ingress_class_name = var.ingress_class
    tls {
      hosts       = [var.hostname]
      secret_name = var.tls_secret_name
    }
    rule {
      host = var.hostname
      http {
        path {
          path      = "/"
          path_type = "Prefix"
          backend {
            service {
              name = kubernetes_service_v1.aimo.metadata[0].name
              port { name = "http" }
            }
          }
        }
      }
    }
  }
  depends_on = [helm_release.ingress]
  lifecycle {
    precondition {
      condition     = var.install_ingress || var.tls_secret_name != null
      error_message = "An existing ingress controller needs an existing TLS Secret in the app namespace."
    }
  }
}

output "public_url" {
  value = "https://${var.hostname}"
}

output "namespace" {
  value = kubernetes_namespace_v1.aimo.metadata[0].name
}
