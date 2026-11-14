variable "name" {
  type    = string
  default = "junction-demo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.name))
    error_message = "Use a lowercase name, 3–40 characters."
  }
}

variable "region" {
  type    = string
  default = "ams3"
}

variable "vpc_cidr" {
  type    = string
  default = "10.120.0.0/20"
}

variable "operator_cidrs" {
  description = "Public operator/VPN CIDRs allowed to reach the Kubernetes API. No database access is granted."
  type        = list(string)
  validation {
    condition = length(var.operator_cidrs) > 0 && alltrue([
      for cidr in var.operator_cidrs : can(cidrhost(cidr, 0)) && !endswith(cidr, "/0")
    ])
    error_message = "Provide at least one operator CIDR; world-open /0 ranges are not accepted."
  }
}

variable "kubernetes_version" {
  description = "Exact DOKS version slug; verify availability before planning."
  type        = string
  default     = "1.35.10-do.0"
}

variable "worker_size" {
  type    = string
  default = "s-2vcpu-4gb"
}

variable "worker_count" {
  type    = number
  default = 1
  validation {
    condition     = var.worker_count >= 1 && var.worker_count <= 3 && floor(var.worker_count) == var.worker_count
    error_message = "The weekend environment supports 1–3 workers."
  }
}

variable "postgres_version" {
  type    = string
  default = "17"
}

variable "database_size" {
  type    = string
  default = "db-s-1vcpu-2gb"
}
