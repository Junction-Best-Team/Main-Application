"""Combine and report the coverage data written by `CI_COVERAGE=1 tests/ci.sh`.

    uv run python tests/coverage_report.py          # tables, HTML/XML, exit 1 below fail_under

Reads .coverage/pytest (pytest-cov) and .coverage/sweep.* (the uvicorn server the black-box sweep
drives, plus the migrate/seed/fixture-catalog CLI steps). Reports pytest only, sweep only and
combined, lists the lines only the sweep reaches, and writes .coverage/html and .coverage/coverage.xml.
The threshold is `fail_under` in pyproject.toml ([tool.coverage.report]); it is applied to the
combined percentage (lines and branches together, coverage.py's own total).
"""

import io
import json
import os
import sys
from pathlib import Path

from coverage import Coverage, CoverageData

DIR = Path(".coverage")
PYTEST, SWEEP, COMBINED = DIR / "pytest", DIR / "sweep", DIR / "combined"


def total(data_file):
    """(percent, per-file {name: percent}, statements, missing) for one data file."""
    cov = Coverage(data_file=str(data_file))
    cov.load()
    out = DIR / f"{data_file.name}.json"
    cov.json_report(outfile=str(out), ignore_errors=True)
    report = json.loads(out.read_text())
    out.unlink()
    files = {n: f["summary"]["percent_covered"] for n, f in report["files"].items()}
    return report["totals"]["percent_covered"], files, report["totals"]


def main():
    if not PYTEST.exists():
        sys.exit("no .coverage/pytest: run `CI_COVERAGE=1 tests/ci.sh` first")
    # The server writes one file per process (parallel mode); merge them, keeping the originals.
    sweep_parts = sorted(DIR.glob("sweep.*"))
    if sweep_parts:
        for old in (SWEEP, COMBINED):
            old.unlink(missing_ok=True)
        merger = Coverage(data_file=str(SWEEP))
        merger.combine([str(p) for p in sweep_parts], keep=True)
        merger.save()
    if not SWEEP.exists():
        sys.exit("no .coverage/sweep*: the sweep server wrote no coverage data")
    COMBINED.unlink(missing_ok=True)
    both = Coverage(data_file=str(COMBINED))
    both.combine([str(PYTEST), str(SWEEP)], keep=True)
    both.save()

    p_total, p_files, _ = total(PYTEST)
    s_total, s_files, _ = total(SWEEP)
    c_total, c_files, c_totals = total(COMBINED)

    rows = [
        "| Source | Line + branch coverage |",
        "| --- | ---: |",
        f"| pytest only | {p_total:.1f}% |",
        f"| sweep server only (incl. migrate/seed CLI) | {s_total:.1f}% |",
        f"| **combined** | **{c_total:.1f}%** |",
    ]
    files = ["| File | pytest | sweep | combined |", "| --- | ---: | ---: | ---: |"]
    for name in sorted(c_files, key=c_files.get):
        files.append(
            f"| {name} | {p_files.get(name, 0):.0f}% | {s_files.get(name, 0):.0f}% "
            f"| {c_files[name]:.0f}% |"
        )

    # Lines that only the sweep executes: the sweep adds this beyond the pytest suite.
    pd, sd = CoverageData(basename=str(PYTEST)), CoverageData(basename=str(SWEEP))
    pd.read()
    sd.read()
    only = []
    for f in sorted(sd.measured_files()):
        extra = set(sd.lines(f) or ()) - set(pd.lines(f) or ())
        if extra:
            only.append(f"| {f} | {len(extra)} |")
    only_table = ["| File | Lines only the sweep executes |", "| --- | ---: |", *only]

    cov = Coverage(data_file=str(COMBINED))
    cov.load()
    cov.html_report(directory=str(DIR / "html"), ignore_errors=True)
    cov.xml_report(outfile=str(DIR / "coverage.xml"), ignore_errors=True)
    buf = io.StringIO()
    cov.report(file=buf, show_missing=True, ignore_errors=True)
    threshold = cov.config.fail_under or 0

    status = "PASS" if c_total >= threshold else "FAIL"
    gate = f"Gate: combined {c_total:.2f}% vs fail_under {threshold:g}% -> {status}"
    sections = [
        "## Python coverage of src/aimo",
        "\n".join(rows),
        gate,
        "### Per file (lowest combined first)",
        "\n".join(files),
        "### Reached only by the black-box sweep",
        "\n".join(only_table) if only else "None.",
    ]
    text = "\n\n".join(sections) + "\n"
    print(text)
    print(buf.getvalue())
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(text)
    if c_totals["num_statements"] == 0:
        sys.exit("no statements measured: configuration problem")
    sys.exit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
