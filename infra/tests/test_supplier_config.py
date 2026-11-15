import base64
import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "supplier_config", ROOT / "infra/scripts/sync-supplier-config.py"
)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
KEY = "synthetic-supplier-key-never-real"


class SupplierConfigTest(unittest.TestCase):
    def setUp(self):
        self.env = {"NAMESPACE": "junction", "VALIO_AIMO_API_KEY": KEY}
        self.resources = {
            ("configmap", "aimo-config"): {
                "data": {
                    "UPSTREAM_MODE": "fixture",
                    "DEMO_CLOCK_ENABLED": "true",
                    "LLM_MODEL": "unchanged",
                }
            },
            ("secret", "aimo-runtime"): {"data": {"DATABASE_URL": "private-database"}},
            ("secret", "aimo-worker-runtime"): {"data": {"GEMINI_API_KEY": "private-google"}},
        }
        for component in ("api", "worker"):
            self.resources["deployment", f"aimo-{component}"] = {
                "spec": {"template": {"spec": {"containers": [{"name": component}]}}},
            }
        self.writes = []

    def run_kubectl(self, command, **kwargs):
        self.assertNotIn(KEY, " ".join(command))
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["timeout"], 45)
        verb, kind, name = command[3:6]
        resource = self.resources[kind, name]
        if verb == "patch":
            self.assertIn("--patch-file=/dev/stdin", command)
            body = json.loads(kwargs["input"])
            self.writes.append((kind, name, body))
            for key, value in body["data"].items():
                if value is None:
                    resource["data"].pop(key, None)
                else:
                    resource["data"][key] = value
        return SimpleNamespace(returncode=0, stdout=json.dumps(resource))

    def test_live_cutover_configures_both_consumers_before_switching_mode_and_verifies(self):
        before = copy.deepcopy(self.resources)
        output = io.StringIO()
        with (
            patch.object(helper.subprocess, "run", side_effect=self.run_kubectl),
            contextlib.redirect_stdout(output),
        ):
            self.assertTrue(helper.sync(self.env))
        self.assertEqual(
            [(k, n) for k, n, _ in self.writes],
            [
                ("secret", "aimo-runtime"),
                ("secret", "aimo-worker-runtime"),
                ("configmap", "aimo-config"),
            ],
        )
        for name in helper.SECRETS:
            data = self.resources["secret", name]["data"]
            self.assertEqual(base64.b64decode(data["VALIO_AIMO_API_KEY"]).decode(), KEY)
            for key, value in before["secret", name]["data"].items():
                self.assertEqual(data[key], value)
        self.assertEqual(
            self.resources["configmap", "aimo-config"]["data"],
            {
                "UPSTREAM_MODE": "live",
                "DEMO_CLOCK_ENABLED": "false",
                "LLM_MODEL": "unchanged",
            },
        )
        self.assertNotIn(KEY, output.getvalue())
        self.assertNotIn(base64.b64encode(KEY.encode()).decode(), output.getvalue())

    def test_unchanged_settings_do_not_write_or_request_restart(self):
        with patch.object(helper.subprocess, "run", side_effect=self.run_kubectl):
            helper.sync(self.env)
            self.writes.clear()
            self.assertFalse(helper.sync(self.env))
        self.assertEqual(self.writes, [])

    def test_secret_mode_overrides_are_removed_so_the_configmap_takes_effect(self):
        for name in helper.SECRETS:
            self.resources["secret", name]["data"].update(
                {
                    "UPSTREAM_MODE": base64.b64encode(b"fixture").decode(),
                    "DEMO_CLOCK_ENABLED": base64.b64encode(b"true").decode(),
                }
            )
        with patch.object(helper.subprocess, "run", side_effect=self.run_kubectl):
            helper.sync(self.env)
        for name in helper.SECRETS:
            self.assertFalse(set(helper.LIVE) & self.resources["secret", name]["data"].keys())

    def test_missing_inputs_fail_without_cluster_access(self):
        for name in self.env:
            with self.subTest(name=name), patch.object(helper.subprocess, "run") as run:
                with self.assertRaises(SystemExit):
                    helper.sync(self.env | {name: "  "})
                run.assert_not_called()

    def test_missing_second_secret_fails_before_any_write(self):
        def missing(command, **kwargs):
            if command[3:6] == ["get", "secret", "aimo-worker-runtime"]:
                return SimpleNamespace(returncode=1, stdout=KEY)
            return self.run_kubectl(command, **kwargs)

        with patch.object(helper.subprocess, "run", side_effect=missing):
            with self.assertRaises(SystemExit) as error:
                helper.sync(self.env)
        self.assertNotIn(KEY, str(error.exception))
        self.assertEqual(self.writes, [])

    def test_failed_secret_update_does_not_enable_live_without_both_keys(self):
        def failure(command, **kwargs):
            if command[3:6] == ["patch", "secret", "aimo-worker-runtime"]:
                return SimpleNamespace(returncode=1, stdout=KEY)
            return self.run_kubectl(command, **kwargs)

        with patch.object(helper.subprocess, "run", side_effect=failure):
            with self.assertRaises(SystemExit) as error:
                helper.sync(self.env)
        self.assertNotIn(KEY, str(error.exception))
        self.assertEqual(
            self.resources["configmap", "aimo-config"]["data"]["UPSTREAM_MODE"], "fixture"
        )

    def test_conflicting_pod_override_fails_before_writing(self):
        pod = self.resources["deployment", "aimo-worker"]["spec"]["template"]["spec"]
        pod["containers"][0]["env"] = [{"name": "UPSTREAM_MODE", "value": "fixture"}]
        with patch.object(helper.subprocess, "run", side_effect=self.run_kubectl):
            with self.assertRaisesRegex(SystemExit, "conflicting supplier"):
                helper.sync(self.env)
        self.assertEqual(self.writes, [])

    def test_write_readback_mismatch_blocks_rollout(self):
        def lost_write(command, **kwargs):
            if command[3:5] == ["patch", "configmap"]:
                return SimpleNamespace(returncode=0, stdout="{}")
            return self.run_kubectl(command, **kwargs)

        with patch.object(helper.subprocess, "run", side_effect=lost_write):
            with self.assertRaisesRegex(SystemExit, "did not verify"):
                helper.sync(self.env)

    def test_transport_and_json_errors_never_expose_credentials(self):
        for failure in (OSError(KEY), subprocess.TimeoutExpired([KEY], 45, output=KEY)):
            with self.subTest(failure=type(failure).__name__):
                with patch.object(helper.subprocess, "run", side_effect=failure):
                    with self.assertRaises(SystemExit) as error:
                        helper.sync(self.env)
                self.assertNotIn(KEY, str(error.exception))
        with patch.object(
            helper.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=KEY)
        ):
            with self.assertRaises(SystemExit) as error:
                helper.sync(self.env)
        self.assertNotIn(KEY, str(error.exception))

    def test_release_wires_supplier_secret_verification_and_refresh(self):
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        self.assertIn("VALIO_AIMO_API_KEY: ${{ secrets.VALIO_AIMO_API_KEY }}", workflow)
        self.assertLess(
            workflow.index("sync-supplier-config.py"),
            workflow.index("bash infra/scripts/deploy-app.sh"),
        )
        self.assertIn("SUPPLIER_REFRESHED: ${{ steps.supplier.outputs.changed }}", workflow)


if __name__ == "__main__":
    unittest.main()
