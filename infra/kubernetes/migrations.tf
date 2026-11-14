# Routine release Jobs are created by CI, never by Terraform. Provision only
# their dedicated credential Secret here; no schema owner URL enters app pods.
resource "kubernetes_secret_v1" "migration" {
  count = nonsensitive(var.migration_credentials == null) ? 0 : 1
  metadata {
    name      = "aimo-migration"
    namespace = kubernetes_namespace_v1.aimo.metadata[0].name
  }
  data = {
    DATABASE_URL          = var.migration_credentials.database_url
    RUNTIME_DATABASE_USER = var.migration_credentials.database_user
  }
}
