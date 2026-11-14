import contextlib
import importlib.util
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare-runtime.py"


class PrivateRuntimeInputsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.runtime = self.root / "infra/kubernetes"
        self.runtime.mkdir(parents=True)
        spec = importlib.util.spec_from_file_location("prepare_runtime", SCRIPT)
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.helper.__file__ = str(self.root / "infra/scripts/prepare-runtime.py")
        self.argv = [
            str(SCRIPT), "--cloud-directory", str(self.root / "cloud"),
            "--worker-image", "ghcr.io/team/app:worker-test",
            "--frontend-image", "ghcr.io/team/app:frontend-test",
            "--image", "ghcr.io/team/app:test", "--hostname", "aimo.example.com",
            "--acme-email", "demo@example.com",
        ]
        values = {
            "database_url": "synthetic-runtime-url",
            "bootstrap_database_url": "synthetic-admin-url",
            "database_ca": "synthetic-ca",
            "database_user": "synthetic-role",
            "kubeconfig": "synthetic-kubeconfig",
        }
        self.result = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({key: {"value": value} for key, value in values.items()}),
        )

    def invoke(self):
        output = io.StringIO()
        with patch("sys.argv", self.argv), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.helper.main()
        return output.getvalue()

    def test_private_files_without_provisioning_or_secret_output(self):
        with patch.object(self.helper.subprocess, "run", return_value=self.result) as run:
            output = self.invoke()
        self.assertNotIn("synthetic", output)
        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["output", "-json"])
        self.assertEqual(command[1], f"-chdir={self.root / 'cloud'}")
        for name in ("kubeconfig.generated.yaml", "runtime.auto.tfvars.json"):
            self.assertEqual(stat.S_IMODE((self.runtime / name).stat().st_mode), 0o600)
        inputs = json.loads((self.runtime / "runtime.auto.tfvars.json").read_text())
        self.assertEqual(inputs["app_replicas"], 0)
        self.assertIsNone(inputs["bootstrap_generation"])
        self.assertEqual(inputs["migration_credentials"], {
            "database_url": "synthetic-admin-url", "database_user": "synthetic-role",
        })
        self.assertNotIn("agent_token", inputs["bootstrap_credentials"])
        self.assertGreaterEqual(len(inputs["bootstrap_credentials"]["buyer_password"]), 12)

    def test_catalog_sync_role_reaches_only_its_secret_and_grant_inputs(self):
        data = json.loads(self.result.stdout)
        data["catalog_sync_database_url"] = {"value": "synthetic-catalog-url"}
        data["catalog_sync_database_user"] = {"value": "synthetic-catalog-role"}
        result = SimpleNamespace(returncode=0, stdout=json.dumps(data))
        with patch.object(self.helper.subprocess, "run", return_value=result):
            output = self.invoke()
        self.assertNotIn("synthetic", output)
        inputs = json.loads((self.runtime / "runtime.auto.tfvars.json").read_text())
        self.assertEqual(inputs["catalog_sync_database_url"], "synthetic-catalog-url")
        self.assertEqual(inputs["database_url"], "synthetic-runtime-url")
        self.assertEqual(
            inputs["migration_credentials"]["catalog_sync_database_user"], "synthetic-catalog-role"
        )
        self.assertEqual(
            inputs["bootstrap_credentials"]["catalog_sync_database_user"], "synthetic-catalog-role"
        )
        self.assertNotIn("catalog_sync", inputs)  # the CronJob is enabled explicitly later

    def test_half_configured_catalog_sync_outputs_write_nothing(self):
        data = json.loads(self.result.stdout)
        data["catalog_sync_database_url"] = {"value": "synthetic-catalog-url"}
        result = SimpleNamespace(returncode=0, stdout=json.dumps(data))
        with patch.object(self.helper.subprocess, "run", return_value=result), self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_existing_credentials_are_never_overwritten(self):
        existing = self.runtime / "runtime.auto.tfvars.json"
        existing.write_text("preserve-me")
        with patch.object(self.helper.subprocess, "run") as run, self.assertRaises(SystemExit):
            self.invoke()
        run.assert_not_called()
        self.assertEqual(existing.read_text(), "preserve-me")

    def test_missing_outputs_do_not_write_partial_credentials(self):
        result = SimpleNamespace(returncode=0, stdout="{}")
        with patch.object(self.helper.subprocess, "run", return_value=result), self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_other_cloud_uses_the_same_interface(self):
        self.argv[self.argv.index("--cloud-directory") + 1] = str(self.root / "future-cloud")
        data = json.loads(self.result.stdout)
        data["provider_specific_id"] = {"value": "must-not-reach-the-app"}
        result = SimpleNamespace(returncode=0, stdout=json.dumps(data))
        with patch.object(self.helper.subprocess, "run", return_value=result) as run:
            self.invoke()
        self.assertEqual(run.call_args.args[0][1], f"-chdir={self.root / 'future-cloud'}")
        inputs = (self.runtime / "runtime.auto.tfvars.json").read_text()
        self.assertNotIn("must-not-reach-the-app", inputs)
        self.assertNotIn("provider_specific_id", inputs)

    def test_invalid_output_types_do_not_write_credentials(self):
        data = json.loads(self.result.stdout)
        data["database_url"]["value"] = {"provider_specific": "unsupported-object"}
        result = SimpleNamespace(returncode=0, stdout=json.dumps(data))
        with patch.object(self.helper.subprocess, "run", return_value=result), self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(list(self.runtime.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
