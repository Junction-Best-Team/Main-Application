variable "kubeconfig_path" {
  type    = string
  default = "~/.kube/config"
}

variable "kubeconfig_context" {
  type    = string
  default = null
}

variable "namespace" {
  type    = string
  default = "junction"
}

variable "image" {
  description = "PR #4 application image built for the worker architecture and pushed to an OCI registry."
  type        = string
  validation {
    condition     = !endswith(var.image, ":latest") && can(regex("(:[A-Za-z0-9_.-]+|@sha256:[a-f0-9]{64})$", var.image)) && !strcontains(var.image, "example.invalid")
    error_message = "Supply a real image with an immutable commit tag or digest, not :latest."
  }
}

variable "image_pull_secret_names" {
  description = "Existing registry pull Secrets in the target namespace; public images need none."
  type        = list(string)
  default     = []
}

variable "hostname" {
  description = "DNS name pointing to the ingress load balancer. A domain and DNS access must already be available."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]+\\.[a-z]{2,}$", var.hostname)) && !endswith(var.hostname, ".invalid")
    error_message = "Supply a real DNS hostname, without scheme or path."
  }
}

variable "database_url" {
  description = "Runtime PostgreSQL URL with sslmode=verify-full and sslrootcert=/etc/aimo-db/ca.crt."
  type        = string
  sensitive   = true
  validation {
    condition     = strcontains(var.database_url, "sslmode=verify-full") && strcontains(var.database_url, "sslrootcert=/etc/aimo-db/ca.crt")
    error_message = "Use verified PostgreSQL TLS and the mounted CA file."
  }
}

variable "database_ca" {
  type      = string
  sensitive = true
}

variable "session_secret" {
  type      = string
  sensitive = true
  validation {
    condition     = length(var.session_secret) >= 32
    error_message = "Generate at least 32 random characters for browser sessions."
  }
}

variable "runtime_secrets" {
  description = "Extra backend-only secrets, e.g. VALIO_AIMO_API_KEY. Never include demo seed credentials here."
  type        = map(string)
  sensitive   = true
  default     = {}
  validation {
    condition     = length(setintersection(toset(keys(var.runtime_secrets)), toset(["DEMO_AGENT_TOKEN", "DEMO_BUYER_PASSWORD"]))) == 0
    error_message = "Seed credentials belong only in bootstrap_credentials."
  }
}

variable "upstream_mode" {
  type    = string
  default = "fixture"
  validation {
    condition     = contains(["fixture", "live"], var.upstream_mode)
    error_message = "Use fixture or live; fixture mode uses labeled mock supplier responses."
  }
}

variable "app_replicas" {
  description = "Start at zero; enable one replica only after bootstrap and catalog ingestion."
  type        = number
  default     = 0
  validation {
    condition     = contains([0, 1], var.app_replicas)
    error_message = "Use 0 during setup or 1 for the weekend demo."
  }
}

variable "install_ingress" {
  description = "Install a portable Traefik controller with one LoadBalancer; false reuses an existing controller."
  type        = bool
  default     = true
}

variable "ingress_class" {
  type    = string
  default = "junction-traefik"
}

variable "acme_email" {
  description = "Contact email for Let's Encrypt; required when install_ingress=true."
  type        = string
  default     = ""
}

variable "ingress_annotations" {
  description = "Controller-specific annotations when reusing an existing ingress controller."
  type        = map(string)
  default     = {}
}

variable "tls_secret_name" {
  description = "Existing TLS Secret when reusing an ingress controller; Traefik ACME needs none."
  type        = string
  default     = null
}

variable "load_balancer_annotations" {
  description = "Optional cloud-specific Service annotations, isolated from application resources."
  type        = map(string)
  default     = {}
}

variable "storage_class" {
  description = "StorageClass for the 1 GiB ACME certificate volume; null uses the cluster default."
  type        = string
  default     = null
}

variable "bootstrap_credentials" {
  description = "Temporary admin URL, runtime username, and private demo credentials. Remove after successful bootstrap."
  type = object({
    database_url   = string
    database_user  = string
    agent_token    = string
    buyer_password = string
  })
  sensitive = true
  default   = null
  validation {
    condition = var.bootstrap_credentials == null ? true : (
      length(var.bootstrap_credentials.agent_token) >= 24 && length(var.bootstrap_credentials.buyer_password) >= 12
    )
    error_message = "Bootstrap requires a 24+ character agent token and 12+ character buyer password."
  }
}

variable "bootstrap_generation" {
  description = "Set once to run migrations, seed, runtime grants, and full catalog import. Change only for an intentional rerun."
  type        = string
  default     = null
  validation {
    condition     = var.bootstrap_generation == null ? true : can(regex("^[a-z0-9][a-z0-9-]{0,29}$", var.bootstrap_generation))
    error_message = "Use a lowercase generation suffix of at most 30 characters."
  }
}
