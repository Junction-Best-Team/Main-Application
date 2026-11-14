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
  description = "API image (Docker target api), pinned by commit or digest."
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
    condition     = length(setintersection(toset(keys(var.runtime_secrets)), toset(["DEMO_AGENT_TOKEN", "DEMO_BUYER_PASSWORD", "BOOTSTRAP_DATABASE_URL", "MIGRATION_DATABASE_URL", "RUNTIME_DATABASE_USER"]))) == 0
    error_message = "Seed and schema-owner credentials belong only in dedicated bootstrap/migration inputs."
  }
}

variable "upstream_mode" {
  description = "Supplier price/availability source. live is the default and needs runtime_secrets.VALIO_AIMO_API_KEY."
  type        = string
  default     = "live"
  validation {
    condition     = contains(["fixture", "live"], var.upstream_mode)
    error_message = "Use live (the default) or fixture; fixture is an explicit opt-in that uses labeled mock supplier responses."
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
    buyer_password = string
  })
  sensitive = true
  default   = null
  validation {
    condition = var.bootstrap_credentials == null ? true : (
      length(var.bootstrap_credentials.buyer_password) >= 12
    )
    error_message = "Bootstrap requires a private buyer password of at least 12 characters."
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

variable "llm_model" {
  description = "Conversational LLM model; separate from local embedding model."
  type        = string
  default     = "openai/gpt-4.1-mini"
}

variable "llm_base_url" {
  description = "Server-side OpenAI-compatible provider URL; key in runtime_secrets.LLM_API_KEY."
  type        = string
  default     = "https://openrouter.ai/api/v1"
  validation {
    condition     = startswith(var.llm_base_url, "https://")
    error_message = "Hosted LLM provider traffic requires HTTPS."
  }
}

variable "worker_image" {
  description = "Independent worker image (Docker target worker), also used for setup jobs."
  type        = string
  validation {
    condition     = !endswith(var.worker_image, ":latest") && can(regex("(:[A-Za-z0-9_.-]+|@sha256:[a-f0-9]{64})$", var.worker_image))
    error_message = "Pin the worker image by commit tag or digest."
  }
}
variable "frontend_image" {
  description = "Independent static frontend image (Docker target frontend)."
  type        = string
  validation {
    condition     = !endswith(var.frontend_image, ":latest") && can(regex("(:[A-Za-z0-9_.-]+|@sha256:[a-f0-9]{64})$", var.frontend_image))
    error_message = "Pin the frontend image by commit tag or digest."
  }
}

variable "migration_credentials" {
  description = "Persistent schema-owner URL and restricted runtime username, supplied only to release Jobs. Separate from temporary bootstrap/seed credentials."
  type = object({
    database_url  = string
    database_user = string
  })
  sensitive = true
  default   = null
  validation {
    condition = var.migration_credentials == null ? true : (
      strcontains(var.migration_credentials.database_url, "sslmode=verify-full") &&
      strcontains(var.migration_credentials.database_url, "sslrootcert=/etc/aimo-db/ca.crt") &&
      trimspace(var.migration_credentials.database_user) != ""
    )
    error_message = "Migration credentials require verified database TLS and the restricted runtime role name."
  }
}
