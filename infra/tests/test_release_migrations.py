import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "migrate_release", ROOT / "infra/scripts/migrate-release.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
IMAGE = "ghcr.io/team/app@sha256:" + "a" * 64


class MigrationJobTest(unittest.TestCase):
    def test_image_secret_isolation_deadline_and_cleanup_wiring(self):
        job = release.job_manifest("junction", IMAGE, "test", [{"name": "registry"}])
        self.assertEqual(job["metadata"]["namespace"], "junction")
        self.assertEqual(job["spec"]["backoffLimit"], 0)
        self.assertEqual(job["spec"]["activeDeadlineSeconds"], 300)
        self.assertEqual(job["spec"]["ttlSecondsAfterFinished"], 86400)
        pod = job["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["restartPolicy"], "Never")
        self.assertEqual(pod["imagePullSecrets"], [{"name": "registry"}])
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        (container,) = pod["containers"]
        self.assertEqual(container["image"], IMAGE)
        self.assertEqual(
            container["args"], ["migrate", "--runtime-role", "$(RUNTIME_DATABASE_USER)"]
        )
        self.assertNotIn("envFrom", container)
        for env in container["env"][:2]:
            self.assertEqual(
                env["valueFrom"]["secretKeyRef"],
                {
                    "name": "aimo-migration",
                    "key": env["name"],
                },
            )
        catalog = container["env"][2]
        self.assertEqual(catalog["name"], "CATALOG_SYNC_DATABASE_USER")
        self.assertEqual(
            catalog["valueFrom"]["secretKeyRef"],
            {"name": "aimo-migration", "key": "CATALOG_SYNC_DATABASE_USER", "optional": True},
        )
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(pod["volumes"][0]["secret"]["secretName"], "aimo-database-ca")
        with self.assertRaises(ValueError):
            release.job_manifest("junction", "ghcr.io/team/app:latest", "test", [])

    def run_job(self, condition="Complete", times=None, create_error=False):
        def kubectl(namespace, *args, payload=None):
            if args[:2] == ("get", "deployment"):
                return json.dumps(
                    {
                        "spec": {
                            "template": {
                                "spec": {
                                    "imagePullSecrets": [{"name": "registry"}],
                                }
                            }
                        }
                    }
                )
            if args[0] == "create" and create_error:
                raise RuntimeError("ambiguous create timeout")
            if args[:2] == ("get", "job"):
                return json.dumps(
                    {
                        "status": {
                            "conditions": [
                                {"type": condition, "status": "True"},
                            ]
                        }
                    }
                )
            return ""

        with (
            patch.object(release, "kubectl", side_effect=kubectl) as calls,
            patch.object(release.time, "sleep"),
            patch.object(release.time, "monotonic", side_effect=times or [0, 1]),
        ):
            if condition == "Complete" and not create_error:
                release.run("junction", IMAGE)
            else:
                with self.assertRaises(RuntimeError):
                    release.run("junction", IMAGE)
        return calls.call_args_list

    def test_success_is_waited_logged_and_deleted(self):
        calls = self.run_job()
        verbs = [call.args[1] for call in calls]
        self.assertLess(verbs.index("create"), verbs.index("logs"))
        self.assertEqual(verbs[-1], "delete")
        manifest = next(call.kwargs["payload"] for call in calls if call.args[1] == "create")
        self.assertEqual(
            manifest["spec"]["template"]["spec"]["imagePullSecrets"], [{"name": "registry"}]
        )

    def test_failed_job_is_retained_for_bounded_diagnostics(self):
        calls = self.run_job(condition="Failed")
        self.assertIn("logs", [call.args[1] for call in calls])
        self.assertNotIn("delete", [call.args[1] for call in calls])

    def test_waiter_timeout_cancels_active_job_and_fails(self):
        calls = self.run_job(condition="Pending", times=[0, 361])
        self.assertEqual(calls[-1].args[1], "delete")

    def test_ambiguous_create_failure_cleans_up_known_name(self):
        calls = self.run_job(create_error=True)
        self.assertEqual(calls[-1].args[1], "delete")
        manifest = next(call.kwargs["payload"] for call in calls if call.args[1] == "create")
        self.assertEqual(calls[-1].args[3], manifest["metadata"]["name"])

    def test_each_invocation_uses_a_fresh_job(self):
        calls = [self.run_job(), self.run_job()]
        names = [
            next(c.kwargs["payload"]["metadata"]["name"] for c in run if c.args[1] == "create")
            for run in calls
        ]
        self.assertNotEqual(*names)

    def test_kubectl_commands_are_bounded(self):
        with patch.object(
            release.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{}")
        ) as run:
            release.kubectl("junction", "get", "job", "test")
        self.assertIn("--request-timeout=10s", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["timeout"], 20)

    def test_release_keeps_cluster_cleanup_and_packaged_migrations(self):
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        self.assertIn("if: always() && steps.config.outcome == 'success'", workflow)
        self.assertIn('rm -f "$KUBECONFIG"', workflow)
        self.assertIn("ci-cluster-access.py close", workflow)
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("COPY migrations/ /app/migrations/", dockerfile)
        self.assertIn("FROM runtime AS api", dockerfile)
        self.assertIn('ENTRYPOINT ["aimo"]', dockerfile)
