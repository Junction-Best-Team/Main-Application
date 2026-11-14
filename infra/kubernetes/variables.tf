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
  description = "Temporary admin URL, runtime username, optional catalog-sync username, and private demo credentials. Remove after successful bootstrap."
  type = object({
    database_url               = string
    database_user              = string
    buyer_password             = string
    catalog_sync_database_user = optional(string)
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
  description = "Set once to run migrations, seed and runtime/catalog-sync grants. The catalog itself is populated by the catalog-sync Job. Change only for an intentional rerun."
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
  description = "Persistent schema-owner URL, restricted runtime username and optional catalog-sync username, supplied only to release Jobs. Separate from temporary bootstrap/seed credentials."
  type = object({
    database_url               = string
    database_user              = string
    catalog_sync_database_user = optional(string)
  })
  sensitive = true
  default   = null
  validation {
    condition = var.migration_credentials == null ? true : (
      strcontains(var.migration_credentials.database_url, "sslmode=verify-full") &&
      strcontains(var.migration_credentials.database_url, "sslrootcert=/etc/aimo-db/ca.crt") &&
      trimspace(var.migration_credentials.database_user) != "" &&
      coalesce(var.migration_credentials.catalog_sync_database_user, "-") != var.migration_credentials.database_user
    )
    error_message = "Migration credentials require verified database TLS and the restricted runtime role name; the catalog-sync role must be a different role."
  }
}

variable "catalog_sync" {
  description = "Scheduled `aimo sync-catalog` CronJob. Enable after migrations/grants, the dedicated catalog database role and the supplier key exist."
  type = object({
    enabled                 = optional(bool, false)
    suspend                 = optional(bool, false)
    schedule                = optional(string, "30 3 * * *")
    timezone                = optional(string, "Europe/Helsinki")
    active_deadline_seconds = optional(number, 3600)
    backoff_limit           = optional(number, 2)
    cpu_request             = optional(string, "250m")
    cpu_limit               = optional(string, "1")
    memory_request          = optional(string, "768Mi")
    memory_limit            = optional(string, "3Gi")
    storage_request         = optional(string, "512Mi")
    storage_limit           = optional(string, "1Gi")
  })
  default  = {}
  nullable = false
  validation {
    condition     = length(split(" ", trimspace(var.catalog_sync.schedule))) == 5 && trimspace(var.catalog_sync.timezone) != ""
    error_message = "Use a five-field cron schedule and an explicit IANA timezone."
  }
  validation {
    condition     = var.catalog_sync.backoff_limit >= 0 && var.catalog_sync.backoff_limit <= 3 && var.catalog_sync.active_deadline_seconds >= 300 && var.catalog_sync.active_deadline_seconds <= 7200
    error_message = "Bound retries (0-3) and the execution deadline (300-7200 seconds)."
  }
}

variable "catalog_sync_database_url" {
  description = "Dedicated catalog-sync role URL (catalog tables only), never the runtime or admin URL."
  type        = string
  sensitive   = true
  default     = null
  validation {
    condition     = var.catalog_sync_database_url == null ? true : strcontains(var.catalog_sync_database_url, "sslmode=verify-full") && strcontains(var.catalog_sync_database_url, "sslrootcert=/etc/aimo-db/ca.crt")
    error_message = "Use verified PostgreSQL TLS and the mounted CA file for catalog sync."
  }
}
