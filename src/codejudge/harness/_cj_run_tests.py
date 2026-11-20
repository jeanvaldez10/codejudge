"""Run pytest under coverage and write machine-readable results to $CJ_OUT.

Usage: python _cj_run_tests.py <result-name> <config.json>
config: {"paths": [...test paths...], "include": [...files to measure...]}
"""

import json
import os
import sys
import time

import coverage
import pytest

OUT = os.environ["CJ_OUT"]


class Collector:
    def __init__(self) -> None:
        self.results = []
        self.collect_errors = []

    def pytest_collectreport(self, report):
        if report.failed:
            self.collect_errors.append(
                {"nodeid": report.nodeid, "message": str(report.longrepr)[-4000:]}
            )

    def pytest_runtest_logreport(self, report):
        # One record per test: the call phase, or setup/teardown if they failed.
        if report.when == "call" or (report.when != "call" and report.outcome != "passed"):
            if report.when != "call" and report.outcome == "skipped" and report.when == "setup":
                outcome = "skipped"
            elif report.when != "call":
                outcome = "error"
            else:
                outcome = report.outcome
            message = None
            if report.outcome != "passed" and report.longrepr is not None:
                message = str(report.longrepr)[-4000:]
            self.results.append(
                {
                    "nodeid": report.nodeid,
                    "outcome": outcome,
                    "duration_ms": round(report.duration * 1000, 3),
                    "message": message,
                }
            )


def main() -> int:
    name, config_path = sys.argv[1], sys.argv[2]
    with open(config_path) as fh:
        config = json.load(fh)
    include = [os.path.abspath(p) for p in config.get("include", [])]
    collector = Collector()
    cov = coverage.Coverage(data_file=None, include=include or None, branch=True)
    started = time.perf_counter()
    cov.start()
    try:
        rc = pytest.main(
            [
                "-q",
                "-p",
                "no:cacheprovider",
                "--import-mode=importlib",
                "--rootdir",
                os.getcwd(),
                "-o",
                "console_output_style=classic",
                *config["paths"],
            ],
            plugins=[collector],
        )
    finally:
        cov.stop()
    elapsed = (time.perf_counter() - started) * 1000
    coverage_pct = None
    if include:
        try:
            cov_out = os.path.join(OUT, f"{name}.coverage.json")
            cov.json_report(outfile=cov_out)
            with open(cov_out) as fh:
                coverage_pct = json.load(fh)["totals"]["percent_covered"]
        except coverage.exceptions.NoDataError:
            coverage_pct = 0.0
    with open(os.path.join(OUT, f"{name}.json"), "w") as fh:
        json.dump(
            {
                "exit_code": int(rc),
                "elapsed_ms": elapsed,
                "tests": collector.results,
                "collect_errors": collector.collect_errors,
                "coverage_percent": coverage_pct,
            },
            fh,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
