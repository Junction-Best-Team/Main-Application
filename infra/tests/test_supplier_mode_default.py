"""SUP-005 (owner Q-01, Q-55): deployments use live suppliers; fixtures are test-only.

Static checks of the Terraform inputs, the portable plan test and the runbook, so they run without
Terraform. The Terraform plan test itself (portable.tftest.hcl) is not run by this file.
"""

import re
import unittest
from pathlib import Path

INFRA = Path(__file__).resolve().parents[1]


def variable_block(name):
    text = (INFRA / "kubernetes" / "variables.tf").read_text()
    match = re.search(rf'variable "{name}" \{{(.*?)\n\}}', text, re.S)
    assert match, name
    return match.group(1)


class SupplierModeDefaultTest(unittest.TestCase):
    def test_terraform_default_is_live(self):
        self.assertRegex(variable_block("upstream_mode"), r'default\s*=\s*"live"')

    def test_only_live_is_allowed(self):
        block = variable_block("upstream_mode")
        self.assertIn('var.upstream_mode == "live"', block)
        self.assertIn("test harness", block)

    def test_portable_plan_test_expects_live_by_default(self):
        text = (INFRA / "kubernetes" / "tests" / "portable.tftest.hcl").read_text()
        self.assertIn('UPSTREAM_MODE == "live"', text)
        self.assertNotIn('UPSTREAM_MODE == "fixture"', text)

    def test_runbook_does_not_call_fixture_the_default(self):
        text = (INFRA / "README.md").read_text()
        self.assertNotIn('`upstream_mode="fixture"` is the explicit default', text)
        self.assertIn('`upstream_mode="live"` is the default', text)
        self.assertIn("VALIO_AIMO_API_KEY", text)


if __name__ == "__main__":
    unittest.main()
