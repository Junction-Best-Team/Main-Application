terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.107.0"
    }
  }
}

# Authentication comes only from DIGITALOCEAN_TOKEN, never from tfvars.
provider "digitalocean" {}

resource "digitalocean_vpc" "demo" {
  name     = "${var.name}-network"
  region   = var.region
  ip_range = var.vpc_cidr
}

resource "digitalocean_tag" "demo" {
  name = var.name
}

resource "digitalocean_kubernetes_cluster" "demo" {
  name          = var.name
  region        = var.region
  version       = var.kubernetes_version
  vpc_uuid      = digitalocean_vpc.demo.id
  ha            = false
  auto_upgrade  = false
  surge_upgrade = false
  tags          = [digitalocean_tag.demo.name]

  # No autoscaler, NAT gateway, or paid HA control plane for the weekend.
  node_pool {
    name       = "demo"
    size       = var.worker_size
    node_count = var.worker_count
    auto_scale = false
  }

  control_plane_firewall {
    enabled           = true
    allowed_addresses = var.operator_cidrs
  }
}

resource "digitalocean_database_cluster" "postgres" {
  name                 = "${var.name}-postgres"
  engine               = "pg"
  version              = var.postgres_version
  region               = var.region
  size                 = var.database_size
  node_count           = 1
  private_network_uuid = digitalocean_vpc.demo.id
  tags                 = [digitalocean_tag.demo.name]
}

resource "digitalocean_database_firewall" "postgres" {
  cluster_id = digitalocean_database_cluster.postgres.id
  rule {
    type  = "k8s"
    value = digitalocean_kubernetes_cluster.demo.id
  }
}

resource "digitalocean_database_db" "aimo" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "aimo"
}

resource "digitalocean_database_user" "runtime" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "aimo_runtime"

  # The API returns empty settings on creation; explicitly retain that default.
  # Provider 2.107 otherwise plans a removal that the API rejects with HTTP 400.
  settings {}
}

# Scheduled catalog ingestion connects as its own role. Release migrations grant it only
# the catalog tables; it never reads identities, sessions, policies or purchases.
resource "digitalocean_database_user" "catalog_sync" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "aimo_catalog_sync"

  settings {}
}

data "digitalocean_database_ca" "postgres" {
  cluster_id = digitalocean_database_cluster.postgres.id
}
