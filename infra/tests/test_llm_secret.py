import base64
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync-llm-secret.py"
spec = importlib.util.spec_from_file_location("llm_secret", SCRIPT)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class LlmSecretTest(unittest.TestCase):
    def setUp(self):
        self.env = {"NAMESPACE": "junction", "LLM_API_KEY": "synthetic-secret"}

    def test_patches_only_provider_fields_using_stdin_without_secret_output(self):
        output = io.StringIO()
        with patch.object(helper.subprocess, "run", side_effect=[SimpleNamespace(returncode=0, stdout='{}'), SimpleNamespace(returncode=0)]) as run:
            with contextlib.redirect_stdout(output):
                self.assertTrue(helper.sync(self.env))
        command = run.call_args.args[0]
        self.assertNotIn("synthetic-secret", " ".join(command))
        self.assertNotIn("synthetic-secret", output.getvalue())
        self.assertIn("--patch-file=/dev/stdin", command)
        self.assertEqual(command[3:7], ["patch", "secret", "aimo-worker-runtime", "--type=merge"])
        body = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(body, {"stringData": {
            "LLM_API_KEY": "synthetic-secret", "LLM_BASE_URL": "https://openrouter.ai/api/v1",
            "LLM_MODEL": "anthropic/claude-sonnet-5.5",
        }})
        self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_missing_configuration_never_calls_cluster(self):
        for missing in ("NAMESPACE",):
            with self.subTest(missing=missing), patch.object(helper.subprocess, "run") as run:
                with self.assertRaises(SystemExit):
                    helper.sync(self.env | {missing: ""})
                run.assert_not_called()

    def test_provider_is_configurable(self):
        with patch.object(helper.subprocess, "run", side_effect=[SimpleNamespace(returncode=0, stdout='{}'), SimpleNamespace(returncode=0)]) as run:
            helper.sync(self.env | {"LLM_MODEL": "another/model"})
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["stringData"]["LLM_MODEL"],
                         "another/model")

    def test_unsafe_url_fails_before_cluster_access(self):
        with patch.object(helper.subprocess, "run") as run, self.assertRaises(SystemExit):
            helper.sync(self.env | {"LLM_BASE_URL": "https://user:secret@example.com"})
        run.assert_not_called()

    def test_cluster_error_never_repeats_submitted_secret(self):
        failure = SimpleNamespace(returncode=1, stderr="synthetic-secret", stdout="synthetic-secret")
        with patch.object(helper.subprocess, "run", return_value=failure), self.assertRaises(SystemExit) as error:
            helper.sync(self.env)
        self.assertNotIn("synthetic-secret", str(error.exception))

    def test_transport_error_does_not_expose_input(self):
        with patch.object(helper.subprocess, "run", side_effect=OSError("synthetic-secret")):
            with self.assertRaises(SystemExit) as error:
                helper.sync(self.env)
        self.assertNotIn("synthetic-secret", str(error.exception))



    def test_patch_error_never_repeats_submitted_secret(self):
        with patch.object(helper.subprocess, "run", side_effect=[
            SimpleNamespace(returncode=0, stdout='{}'),
            SimpleNamespace(returncode=1, stderr="synthetic-secret"),
        ]), self.assertRaises(SystemExit) as error:
            helper.sync(self.env)
        self.assertNotIn("synthetic-secret", str(error.exception))


class UnchangedSecretTest(unittest.TestCase):
    def setUp(self):
        self.env = {"NAMESPACE": "junction", "LLM_API_KEY": "synthetic-secret"}

    def test_missing_key_preserves_existing_settings_without_cluster_access(self):
        with patch.object(helper.subprocess, "run") as run:
            self.assertFalse(helper.sync(self.env | {"LLM_API_KEY": ""}))
        run.assert_not_called()

    def test_unchanged_fields_do_not_patch_or_request_restart(self):
        fields = {"LLM_API_KEY": "synthetic-secret", "LLM_BASE_URL": "https://openrouter.ai/api/v1",
                  "LLM_MODEL": "anthropic/claude-sonnet-5.5", "DATABASE_URL": "untouched"}
        current = json.dumps({"data": {k: base64.b64encode(v.encode()).decode() for k, v in fields.items()}})
        with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=current)) as run:
            self.assertFalse(helper.sync(self.env))
        self.assertEqual(run.call_count, 1)

    def test_invalid_secret_response_never_exposes_body(self):
        with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="synthetic-secret")):
            with self.assertRaises(SystemExit) as error:
                helper.sync(self.env)
        self.assertNotIn("synthetic-secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
