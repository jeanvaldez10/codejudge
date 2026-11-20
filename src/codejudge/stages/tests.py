"""Deterministic test execution: task-owned suites (visible + hidden) and the
candidate's own tests (with coverage)."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from codejudge.models import (
    StageResult,
    StageStatus,
    TestCaseResult,
    TestCategory,
)
from codejudge.stages.base import TASK_TESTS_DIR, Stage, StageContext


def _run_pytest(
    ctx: StageContext, name: str, paths: list[str], include: list[str]
) -> tuple[dict[str, Any] | None, str]:
    cfg = ctx.write_config(name, {"paths": paths, "include": include})
    res = ctx.run(["{python}", "_cj_run_tests.py", name, cfg])
    raw = res.outputs.get(f"{name}.json")
    if raw is None:
        why = res.describe_failure()
        return (
            None,
            f"test runner produced no results ({why})\n{res.stdout[-3000:]}\n{res.stderr[-3000:]}",
        )
    try:
        return json.loads(raw), res.stdout[-8000:]
    except json.JSONDecodeError:
        return None, "test runner output was corrupted"


def _suite_of(nodeid: str) -> str:
    return PurePosixPath(nodeid.split("::", 1)[0]).stem


class TaskTestsStage(Stage):
    """Runs every task suite once, then reports visible and hidden results as
    separate stages so hidden-test details can be redacted independently."""

    name = "task_tests"
    requires = ("build",)

    def __init__(self, hidden: bool) -> None:
        self.hidden = hidden
        self.name = "hidden_tests" if hidden else "visible_tests"

    def run(self, ctx: StageContext) -> StageResult:
        suites = [s for s in ctx.task.tests if s.hidden == self.hidden]
        if not suites:
            return StageResult(
                stage=self.name, status=StageStatus.skipped, summary="task defines no such tests"
            )
        meta = {s.name: s for s in suites}
        paths = [f"{TASK_TESTS_DIR}/{s.name}.py" for s in suites]
        data, logs = _run_pytest(ctx, self.name, paths, ctx.solution_paths)
        if data is None:
            # Whole-run failure (timeout / crash / OOM) counts as every test failing:
            # a candidate must not escape scoring by crashing the runner.
            return StageResult(
                stage=self.name,
                status=StageStatus.failed,
                score=0,
                summary="test run aborted: " + logs.splitlines()[0] if logs else "test run aborted",
                metrics={"passed": 0, "total": None},
                logs=logs if not self.hidden else "",
            )
        tests: list[TestCaseResult] = []
        for t in data["tests"]:
            suite = meta.get(_suite_of(t["nodeid"]))
            if suite is None:
                continue  # a result we did not ask for (e.g. a forged record)
            tests.append(
                TestCaseResult(
                    nodeid=t["nodeid"],
                    suite=suite.name,
                    category=suite.category,
                    hidden=suite.hidden,
                    outcome=t["outcome"],
                    duration_ms=t.get("duration_ms", 0.0),
                    message=t.get("message"),
                )
            )
        # A suite that failed to collect (e.g. ImportError of a required name)
        # contributes one failing record so it is not silently dropped.
        for err in data.get("collect_errors", []):
            suite = meta.get(_suite_of(err["nodeid"]))
            if suite is not None:
                tests.append(
                    TestCaseResult(
                        nodeid=err["nodeid"] or suite.name,
                        suite=suite.name,
                        category=suite.category,
                        hidden=suite.hidden,
                        outcome="error",
                        message=err["message"],
                    )
                )
        counted = [t for t in tests if t.outcome != "skipped"]
        passed = sum(t.outcome == "passed" for t in counted)
        total = len(counted)
        rate = 100.0 * passed / total if total else 0.0
        by_cat: dict[str, dict[str, int]] = {}
        for cat in TestCategory:
            ts = [t for t in counted if t.category == cat]
            if ts:
                by_cat[cat.value] = {
                    "passed": sum(t.outcome == "passed" for t in ts),
                    "total": len(ts),
                }
        status = (
            StageStatus.passed
            if total and passed == total
            else StageStatus.warning
            if rate >= 50
            else StageStatus.failed
        )
        return StageResult(
            stage=self.name,
            status=status,
            score=round(rate, 2),
            summary=f"{passed}/{total} tests passed",
            metrics={
                "passed": passed,
                "total": total,
                "by_category": by_cat,
                "suite_coverage_percent": data.get("coverage_percent"),
            },
            tests=tests,
            logs="" if self.hidden else logs,
        )


class CandidateTestsStage(Stage):
    """Runs tests the generator wrote itself and measures how much of its own
    solution they cover. Evaluates the *quality of generated tests*."""

    name = "candidate_tests"
    requires = ("build",)

    def run(self, ctx: StageContext) -> StageResult:
        paths = ctx.candidate_test_paths
        if not paths:
            return StageResult(
                stage=self.name,
                status=StageStatus.skipped,
                summary="candidate submitted no tests",
            )
        data, logs = _run_pytest(ctx, self.name, paths, ctx.solution_paths)
        if data is None:
            return StageResult(
                stage=self.name,
                status=StageStatus.failed,
                score=0,
                summary="test run aborted",
                logs=logs,
            )
        tests = [
            TestCaseResult(
                nodeid=t["nodeid"],
                suite=_suite_of(t["nodeid"]),
                category=TestCategory.correctness,
                hidden=False,
                outcome=t["outcome"],
                duration_ms=t.get("duration_ms", 0.0),
                message=t.get("message"),
            )
            for t in data["tests"]
        ]
        passed = sum(t.outcome == "passed" for t in tests)
        total = sum(t.outcome != "skipped" for t in tests)
        cov = float(data.get("coverage_percent") or 0.0)
        all_pass = total > 0 and passed == total and not data.get("collect_errors")
        status = StageStatus.passed if all_pass and cov >= 80 else StageStatus.warning
        if total == 0 or passed < total / 2:
            status = StageStatus.failed
        return StageResult(
            stage=self.name,
            status=status,
            # Coverage only counts if the tests actually pass.
            score=round(cov * (passed / total if total else 0), 2),
            summary=f"{passed}/{total} own tests passed, {cov:.1f}% line+branch coverage",
            metrics={"passed": passed, "total": total, "coverage_percent": round(cov, 2)},
            tests=tests,
            logs=logs,
        )
