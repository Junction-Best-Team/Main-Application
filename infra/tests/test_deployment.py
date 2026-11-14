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
    def run_deploy(self, replicas="1", fail_rollout=False, image=None, previous_image=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kubectl = root / "kubectl"
            kubectl.write_text('''#!/usr/bin/env bash
echo "$*" >> "$CALL_LOG"
case "$*" in
  *spec.replicas*) echo "$REPLICAS" ;;
  *jsonpath*) echo "$PREVIOUS_IMAGE" ;;
  *"set image"*)
    if [[ "$*" == *"=$PREVIOUS_IMAGE" ]]; then touch "$UNDONE"; fi ;;
  *"rollout status"*)
    if [[ "$FAIL_ROLLOUT" == 1 && "$*" == *"aimo-frontend"* && ! -f "$UNDONE" ]]; then exit 1; fi ;;
esac
''')
            kubectl.chmod(0o700)
            log = root / "calls"
            result = subprocess.run(["bash", str(ROOT / "scripts/deploy-app.sh")],
                env={**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                     "NAMESPACE": "junction", "IMAGE": image or "ghcr.io/team/app@sha256:" + "a" * 64,
                     "WORKER_IMAGE": "ghcr.io/team/app@sha256:" + "a" * 64,
                     "FRONTEND_IMAGE": "ghcr.io/team/app@sha256:" + "a" * 64,
                     "REPLICAS": replicas, "FAIL_ROLLOUT": "1" if fail_rollout else "0",
                     "PREVIOUS_IMAGE": previous_image or "ghcr.io/team/app@sha256:" + "b" * 64,
                     "CALL_LOG": str(log), "UNDONE": str(root / "undone")},
                capture_output=True, text=True)
            return result, log.read_text() if log.exists() else ""

    def test_deploys_published_digest_and_waits_for_readiness(self):
        result, calls = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("set image deployment/aimo-api api=ghcr.io/team/app@sha256:", calls)
        self.assertIn("rollout status", calls)
        self.assertNotIn("rollout undo", calls)

    def test_stopped_app_is_not_accidentally_enabled(self):
        result, calls = self.run_deploy(replicas="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("set image", calls)

    def test_failed_rollout_restores_previous_image_and_fails(self):
        result, calls = self.run_deploy(fail_rollout=True)
        self.assertNotEqual(result.returncode, 0)
        for component in ("api", "worker", "frontend"):
            self.assertIn(component + "=ghcr.io/team/app@sha256:" + "b" * 64, calls)

    def test_same_image_failure_does_not_roll_back_an_unrelated_revision(self):
        image = "ghcr.io/team/app@sha256:" + "a" * 64
        result, calls = self.run_deploy(fail_rollout=True, previous_image=image)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("set image", calls)

    def test_mutable_image_tag_is_rejected(self):
        result, calls = self.run_deploy(image="ghcr.io/team/app:latest")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, "")


if __name__ == "__main__":
    unittest.main()
