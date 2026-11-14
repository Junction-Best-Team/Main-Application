output "cluster_id" {
  value = digitalocean_kubernetes_cluster.demo.id
}

output "database_id" {
  value = digitalocean_database_cluster.postgres.id
}

output "kubeconfig" {
  value     = digitalocean_kubernetes_cluster.demo.kube_config[0].raw_config
  sensitive = true
}

output "database_ca" {
  value     = data.digitalocean_database_ca.postgres.certificate
  sensitive = true
}

output "database_user" {
  value = digitalocean_database_user.runtime.name
}

locals {
  database_host = digitalocean_database_cluster.postgres.private_host
  database_port = digitalocean_database_cluster.postgres.port
  database_name = digitalocean_database_db.aimo.name
  database_tls  = "sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
}

output "database_url" {
  value     = "postgresql://${urlencode(digitalocean_database_user.runtime.name)}:${urlencode(digitalocean_database_user.runtime.password)}@${local.database_host}:${local.database_port}/${local.database_name}?${local.database_tls}"
  sensitive = true
}

# Optional portable outputs: the dedicated catalog-sync role for the ingestion CronJob.
output "catalog_sync_database_user" {
  value = digitalocean_database_user.catalog_sync.name
}

output "catalog_sync_database_url" {
  value     = "postgresql://${urlencode(digitalocean_database_user.catalog_sync.name)}:${urlencode(digitalocean_database_user.catalog_sync.password)}@${local.database_host}:${local.database_port}/${local.database_name}?${local.database_tls}"
  sensitive = true
}

output "bootstrap_database_url" {
  value     = "postgresql://${urlencode(digitalocean_database_cluster.postgres.user)}:${urlencode(digitalocean_database_cluster.postgres.password)}@${local.database_host}:${local.database_port}/${local.database_name}?${local.database_tls}"
  sensitive = true
}
