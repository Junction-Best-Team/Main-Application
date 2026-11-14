mock_provider "kubernetes" {}
mock_provider "helm" {}

variables {
  image          = "ghcr.io/junction-best-team/main-application:test-commit"
  hostname       = "aimo.test.example.com"
  acme_email     = "demo@example.com"
  database_url   = "postgresql://test:synthetic@postgres.test:5432/aimo?sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt"
  database_ca    = "synthetic-test-ca"
  session_secret = "synthetic-test-session-secret-at-least-32-chars"
}

run "safe_initial_plan" {
  command = plan
  assert {
    condition     = kubernetes_deployment_v1.aimo.spec[0].replicas == "0" && length(kubernetes_job_v1.bootstrap) == 0
    error_message = "Initial setup must not start the app or run privileged setup jobs."
  }
  assert {
    condition     = kubernetes_service_v1.aimo.spec[0].type == "ClusterIP"
    error_message = "The app should be reachable only through the HTTPS ingress."
  }
  assert {
    condition     = length(helm_release.ingress) == 1 && yamldecode(helm_release.ingress[0].values[0]).persistence.enabled
    error_message = "Install one portable ingress controller and persist its ACME certificates."
  }
  assert {
    condition     = kubernetes_config_map_v1.runtime.data.SECURE_COOKIES == "true" && kubernetes_config_map_v1.runtime.data.UPSTREAM_MODE == "fixture"
    error_message = "Use secure cookies and explicitly mocked supplier responses by default."
  }
}

run "existing_cluster_ingress" {
  command = plan
  variables {
    install_ingress = false
    ingress_class   = "existing-controller"
    tls_secret_name = "existing-tls"
  }
  assert {
    condition     = length(helm_release.ingress) == 0 && kubernetes_ingress_v1.aimo.spec[0].ingress_class_name == "existing-controller"
    error_message = "Existing ingress must not create a second load balancer."
  }
}

run "reject_unverified_database_tls" {
  command = plan
  variables { database_url = "postgresql://test:synthetic@postgres.test/aimo?sslmode=disable" }
  expect_failures = [var.database_url]
}

run "reject_import_with_serving_app" {
  command = plan
  variables {
    app_replicas         = 1
    bootstrap_generation = "demo-v1"
    bootstrap_credentials = {
      database_url   = "postgresql://synthetic-admin@postgres.test/aimo"
      database_user  = "aimo_runtime"
      agent_token    = "synthetic-agent-token-at-least-24-chars"
      buyer_password = "synthetic-password-at-least-12-chars"
    }
  }
  expect_failures = [kubernetes_job_v1.bootstrap]
}
