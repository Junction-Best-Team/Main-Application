#!/usr/bin/env python3
"""Extract exact Helm values from a mocked Terraform plan for chart validation."""

import json
import sys
from pathlib import Path

for line in Path(sys.argv[1]).read_text().splitlines():
    event = json.loads(line)
    if event.get("type") != "test_plan" or event.get("@testrun") != "safe_initial_plan":
        continue
    for resource in event["test_plan"]["resource_changes"]:
        if resource["address"] == "helm_release.ingress[0]":
            sys.stdout.write(resource["change"]["after"]["values"][0])
            raise SystemExit(0)
raise SystemExit("No tested ingress values found")
