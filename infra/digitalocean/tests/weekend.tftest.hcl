mock_provider "digitalocean" {}

variables {
  operator_cidrs = ["192.0.2.10/32"]
}

run "weekend_budget_and_database_isolation" {
  command = plan
  assert {
    condition     = digitalocean_kubernetes_cluster.demo.node_pool[0].node_count == 1 && digitalocean_kubernetes_cluster.demo.node_pool[0].size == "s-2vcpu-4gb"
    error_message = "Keep the default to one 4 GB demo worker."
  }
  assert {
    condition     = !digitalocean_kubernetes_cluster.demo.ha && !digitalocean_kubernetes_cluster.demo.node_pool[0].auto_scale
    error_message = "Paid control-plane HA and autoscaling must stay disabled."
  }
  assert {
    condition     = digitalocean_database_cluster.postgres.engine == "pg" && digitalocean_database_cluster.postgres.node_count == 1
    error_message = "Use one managed PostgreSQL primary."
  }
  assert {
    condition     = length(digitalocean_database_firewall.postgres.rule) == 1 && one(digitalocean_database_firewall.postgres.rule).type == "k8s"
    error_message = "The database must trust only the Kubernetes cluster, without public IP rules."
  }
  assert {
    condition     = digitalocean_kubernetes_cluster.demo.control_plane_firewall[0].enabled
    error_message = "The Kubernetes API must use the operator allowlist."
  }
}

run "reject_world_open_api" {
  command = plan
  variables { operator_cidrs = ["0.0.0.0/0"] }
  expect_failures = [var.operator_cidrs]
}

run "reject_unbounded_workers" {
  command = plan
  variables { worker_count = 10 }
  expect_failures = [var.worker_count]
}
