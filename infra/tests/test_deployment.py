import importlib.util
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cluster_access", ROOT / "scripts/ci-cluster-access.py")
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


class ClusterAccessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state.json"
        self.config = Path(self.temp.name) / "kubeconfig"
        self.cluster = {
            "name": "demo", "control_plane_firewall": {
                "enabled": True, "allowed_addresses": ["198.51.100.10/32"],
            },
        }

    def open(self):
        with patch.object(access, "urlopen", return_value=io.BytesIO(b"203.0.113.2")):
            access.open_access(self.state, self.config)

    def test_adds_only_runner_and_writes_private_credentials(self):
        def api(path="", body=None):
            if body:
                self.assertEqual(json.loads(self.state.read_text()), {"added": "203.0.113.2/32"})
                self.assertEqual(body["control_plane_firewall"]["allowed_addresses"],
                                 ["198.51.100.10/32", "203.0.113.2/32"])
                return b"{}"
            if path:
                self.assertIn("expiry_seconds=1800", path)
                return b"private-kubeconfig"
            return json.dumps({"kubernetes_cluster": self.cluster}).encode()
        with patch.object(access, "api", side_effect=api):
            self.open()
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_existing_operator_range_is_not_removed(self):
        self.cluster["control_plane_firewall"]["allowed_addresses"] = ["203.0.113.0/24"]
        with patch.object(access, "api", side_effect=[
            json.dumps({"kubernetes_cluster": self.cluster}).encode(), b"kubeconfig",
        ]) as api:
            self.open()
            access.close_access(self.state)
        self.assertEqual(api.call_count, 2)

    def test_cleanup_preserves_new_operator_addresses(self):
        self.state.write_text(json.dumps({"added": "203.0.113.2/32"}))
        self.cluster["control_plane_firewall"]["allowed_addresses"] += [
            "203.0.113.2/32", "192.0.2.5/32",
        ]
        with patch.object(access, "api", side_effect=[
            json.dumps({"kubernetes_cluster": self.cluster}).encode(), b"{}",
        ]) as api:
            access.close_access(self.state)
        self.assertEqual(api.call_args.kwargs["body"]["control_plane_firewall"]["allowed_addresses"],
                         ["198.51.100.10/32", "192.0.2.5/32"])
        self.assertFalse(self.state.exists())

    def test_failed_update_keeps_cleanup_intent(self):
        with patch.object(access, "api", side_effect=[
            json.dumps({"kubernetes_cluster": self.cluster}).encode(), RuntimeError("API timeout"),
        ]), self.assertRaises(RuntimeError):
            self.open()
        self.assertEqual(json.loads(self.state.read_text())["added"], "203.0.113.2/32")

    def test_disabled_firewall_is_not_enabled(self):
        self.cluster["control_plane_firewall"]["enabled"] = False
        with patch.object(access, "api", side_effect=[
            json.dumps({"kubernetes_cluster": self.cluster}).encode(), b"kubeconfig",
        ]) as api, patch.object(access, "urlopen") as ip:
            access.open_access(self.state, self.config)
        self.assertEqual(api.call_count, 2)
        ip.assert_not_called()

    def test_cleanup_before_access_is_a_noop(self):
        with patch.object(access, "api") as api:
            access.close_access(self.state)
        api.assert_not_called()


class AppDeploymentTest(unittest.TestCase):
    def run_deploy(self, replicas="1", fail_rollout=False, image=None, previous_image=None,
                   llm_refreshed=False, migration_status="Complete", cronjob=True,
                   fail_rollout_component="frontend", fail_update_component="", supplier_refreshed=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kubectl = root / "kubectl"
            kubectl.write_text('''#!/usr/bin/env bash
echo "$*" >> "$CALL_LOG"
case "$*" in
  *"get deployment aimo-api -o json") echo '{"spec":{"template":{"spec":{}}}}' ;;
  *"get job"*) printf '{"status":{"conditions":[{"type":"%s","status":"True"}]}}\\n' "$MIGRATION_STATUS" ;;
  *"get cronjob"*) if [[ "$CRONJOB" == 1 ]]; then echo "$PREVIOUS_IMAGE"; fi ;;
  *spec.replicas*) echo "$REPLICAS" ;;
  *jsonpath*) echo "$PREVIOUS_IMAGE" ;;
  *"set image"*)
    if [[ "$*" == *"=$PREVIOUS_IMAGE" ]]; then
      touch "$UNDONE"
    elif [[ -n "$FAIL_UPDATE_COMPONENT" && "$*" == *"deployment/aimo-$FAIL_UPDATE_COMPONENT "* ]]; then
      # Model an API error after the update may already have reached Kubernetes.
      exit 1
    fi ;;
  *"rollout status"*)
    if [[ "$FAIL_ROLLOUT" == 1 && "$*" == *"aimo-$FAIL_ROLLOUT_COMPONENT"* && ! -f "$UNDONE" ]]; then exit 1; fi ;;
esac
''')
            kubectl.chmod(0o700)
            log = root / "calls"
            result = subprocess.run(["bash", str(ROOT / "scripts/deploy-app.sh")],
                env={**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                     "NAMESPACE": "junction", "IMAGE": image or "ghcr.io/team/app@sha256:" + "a" * 64,
                     "WORKER_IMAGE": "ghcr.io/team/app@sha256:" + "a" * 64,
                     "FRONTEND_IMAGE": "ghcr.io/team/app@sha256:" + "a" * 64,
                     "MIGRATION_STATUS": migration_status,
                     "REPLICAS": replicas, "FAIL_ROLLOUT": "1" if fail_rollout else "0",
                     "FAIL_ROLLOUT_COMPONENT": fail_rollout_component,
                     "FAIL_UPDATE_COMPONENT": fail_update_component,
                     "LLM_REFRESHED": "true" if llm_refreshed else "false",
                     "SUPPLIER_REFRESHED": "true" if supplier_refreshed else "false",
                     "CRONJOB": "1" if cronjob else "0",
                     "PREVIOUS_IMAGE": previous_image or "ghcr.io/team/app@sha256:" + "b" * 64,
                     "CALL_LOG": str(log), "UNDONE": str(root / "undone")},
                capture_output=True, text=True)
            return result, log.read_text() if log.exists() else ""

    def test_deploys_published_digest_and_waits_for_readiness(self):
        result, calls = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("set image deployment/aimo-api api=ghcr.io/team/app@sha256:", calls)
        self.assertIn("rollout status", calls)
        self.assertLess(calls.index("create -f -"), calls.index("set image"))
        self.assertLess(calls.index("get job"), calls.index("set image"))
        for component in ("worker", "api", "frontend"):
            self.assertLess(calls.index(f"set image deployment/aimo-{component}"),
                            calls.index("rollout status"))
        self.assertNotIn("rollout undo", calls)

    def test_worker_rollout_waits_for_long_turn_including_rollback(self):
        for failed in (False, True):
            with self.subTest(rollback=failed):
                result, calls = self.run_deploy(fail_rollout=failed)
                self.assertEqual(result.returncode == 0, not failed, result.stderr)
                waits = [line for line in calls.splitlines() if "rollout status" in line]
                for component in ("worker", "api", "frontend"):
                    component_waits = [line for line in waits if f"aimo-{component} " in line]
                    self.assertEqual(len(component_waits), 2 if failed else 1)
                    timeout = "10m" if component == "worker" else "5m"
                    self.assertTrue(all(f"--timeout={timeout}" in line for line in component_waits))

    def test_catalog_sync_cronjob_follows_the_released_worker_digest(self):
        result, calls = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("set image cronjob/aimo-catalog-sync catalog-sync=ghcr.io/team/app@sha256:"
                      + "a" * 64, calls)
        self.assertLess(calls.index("rollout status deployment/aimo-worker"),
                        calls.index("set image cronjob/aimo-catalog-sync"))

    def test_absent_catalog_sync_cronjob_is_not_created_by_releases(self):
        result, calls = self.run_deploy(cronjob=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("cronjob/aimo-catalog-sync", calls)

    def test_failed_rollout_never_moves_the_catalog_sync_cronjob(self):
        result, calls = self.run_deploy(fail_rollout=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("cronjob", calls)

    def test_release_keeps_the_api_voice_key_reference(self):
        # Releases never re-apply Terraform, so the API's optional Google key reference
        # (infra/kubernetes/main.tf) must be ensured by the release itself.
        for previous in (None, "ghcr.io/team/app@sha256:" + "a" * 64):
            with self.subTest(same_image=previous is not None):
                result, calls = self.run_deploy(previous_image=previous)
                self.assertEqual(result.returncode, 0, result.stderr)
                line = next(c for c in calls.splitlines() if c.startswith(
                    "-n junction patch deployment aimo-api --type=strategic -p "))
                patch = json.loads(line.split(" -p ", 1)[1])
                container, = patch["spec"]["template"]["spec"]["containers"]
                self.assertEqual(container, {"name": "api", "env": [{
                    "name": "GEMINI_API_KEY", "valueFrom": {"secretKeyRef": {
                        "name": "aimo-worker-runtime", "key": "GEMINI_API_KEY",
                        "optional": True}}}]})
                self.assertLess(calls.index("get job"), calls.index("patch deployment"))
                self.assertLess(calls.index("patch deployment"), calls.index("rollout status"))
                if previous is None:
                    self.assertLess(calls.index("patch deployment"), calls.index("set image"))

    def test_migration_failure_prevents_any_rollout_or_restart(self):
        result, calls = self.run_deploy(migration_status="Failed", llm_refreshed=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("create -f -", calls)
        self.assertNotIn("patch deployment", calls)
        self.assertNotIn("set image", calls)
        self.assertNotIn("rollout", calls)

    def test_stopped_app_is_not_accidentally_enabled(self):
        result, calls = self.run_deploy(replicas="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("set image", calls)

    def test_failed_rollout_restores_previous_image_and_fails(self):
        for failed in ("worker", "api", "frontend"):
            with self.subTest(failed=failed):
                result, calls = self.run_deploy(fail_rollout=True, fail_rollout_component=failed)
                self.assertNotEqual(result.returncode, 0)
                for component in ("api", "worker", "frontend"):
                    self.assertIn(component + "=ghcr.io/team/app@sha256:" + "b" * 64, calls)
                self.assertNotIn("cronjob", calls)

    def test_ambiguous_image_update_restores_every_attempted_component(self):
        components = ("worker", "api", "frontend")
        for index, failed in enumerate(components):
            with self.subTest(failed=failed):
                result, calls = self.run_deploy(fail_update_component=failed)
                self.assertNotEqual(result.returncode, 0)
                for component in components[:index + 1]:
                    self.assertIn(component + "=ghcr.io/team/app@sha256:" + "b" * 64, calls)
                for component in components[index + 1:]:
                    self.assertNotIn("set image deployment/aimo-" + component, calls)
                self.assertNotIn("cronjob", calls)

    def test_same_image_failure_does_not_roll_back_an_unrelated_revision(self):
        image = "ghcr.io/team/app@sha256:" + "a" * 64
        result, calls = self.run_deploy(fail_rollout=True, previous_image=image)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("set image", calls)

    def test_mutable_image_tag_is_rejected(self):
        result, calls = self.run_deploy(image="ghcr.io/team/app:latest")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, "")

    def test_same_image_restarts_provider_consumers_when_settings_were_refreshed(self):
        image = "ghcr.io/team/app@sha256:" + "a" * 64
        result, calls = self.run_deploy(image=image, previous_image=image, llm_refreshed=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rollout restart deployment/aimo-worker", calls)
        self.assertIn("rollout restart deployment/aimo-api", calls)
        self.assertNotIn("rollout restart deployment/aimo-frontend", calls)
        self.assertNotIn("set image", calls)

    def test_unchanged_provider_and_same_image_do_not_restart(self):
        image = "ghcr.io/team/app@sha256:" + "a" * 64
        result, calls = self.run_deploy(image=image, previous_image=image)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("create -f -", calls)
        self.assertNotIn("rollout restart", calls)
        self.assertNotIn("set image", calls)

    def test_same_image_reloads_live_supplier_settings_in_both_consumers(self):
        image = "ghcr.io/team/app@sha256:" + "a" * 64
        result, calls = self.run_deploy(image=image, previous_image=image, supplier_refreshed=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rollout restart deployment/aimo-worker", calls)
        self.assertIn("rollout restart deployment/aimo-api", calls)
        self.assertNotIn("rollout restart deployment/aimo-frontend", calls)


if __name__ == "__main__":
    unittest.main()
