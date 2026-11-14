"""Regenerate the browser contract from the same models used by HTTP and MCP."""

import json
from pathlib import Path

from aimo.api import app

Path("frontend/openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")
