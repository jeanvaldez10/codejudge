"""Static analysis: Ruff (lint + complexity), mypy (types), annotation coverage."""

from __future__ import annotations

import ast
import json
import re

from codejudge.models import Finding, Severity, StageResult, StageStatus
from codejudge.stages.base import Stage, StageContext, clamp

RUFF_RULES = "E,F,W,B,C90,UP,SIM,N,RET,PERF,PL,RUF"
_RUFF_HIGH = re.compile(r"^(F|B)\d")  # pyflakes / bugbear: likely real bugs
_MYPY_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?:\d+:)? (?P<sev>error|note): (?P<msg>.*?)(?:  \[(?P<code>[\w-]+)\])?$"
)


def annotation_coverage(sources: dict[str, str]) -> float | None:
    total = annotated = 0
    for src in sources.values():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                total += 1
                args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                args = [a for a in args if a.arg not in ("self", "cls")]
                if node.returns is not None and all(a.annotation is not None for a in args):
                    annotated += 1
    return round(100.0 * annotated / total, 1) if total else None


def _loc(sources: dict[str, str]) -> int:
    return sum(
        1
        for s in sources.values()
        for line in s.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


class StaticAnalysisStage(Stage):
    name = "static_analysis"
    requires = ("build",)

    def run(self, ctx: StageContext) -> StageResult:
        files = ctx.solution_paths
        findings: list[Finding] = []
        logs: list[str] = []

        ruff = ctx.run(
            [
                "ruff", "check", "--isolated", "--no-cache", "--output-format", "json",
                "--select", RUFF_RULES, "--target-version", "py312",
                "--config", "lint.mccabe.max-complexity=10", "--exit-zero", *files,
            ],
            timeout=60,
        )  # fmt: skip
        try:
            for item in json.loads(ruff.stdout or "[]"):
                code = item.get("code") or "ruff"
                findings.append(
                    Finding(
                        tool="ruff",
                        rule=code,
                        message=item.get("message", ""),
                        severity=Severity.medium if _RUFF_HIGH.match(code) else Severity.low,
                        file=item.get("filename", "")
                        .replace(str(ctx.workspace) + "/", "")
                        .replace("/workspace/", ""),
                        line=(item.get("location") or {}).get("row"),
                    )
                )
        except json.JSONDecodeError:
            logs.append("ruff: " + (ruff.stderr or ruff.stdout)[-2000:])

        mypy = ctx.run(
            [
                "{python}", "-m", "mypy", "--ignore-missing-imports", "--check-untyped-defs",
                "--no-error-summary", "--show-column-numbers", "--no-color-output",
                "--hide-error-context", "--python-version", "3.12", *files,
            ],
            timeout=120,
        )  # fmt: skip
        for line in mypy.stdout.splitlines():
            m = _MYPY_LINE.match(line.strip())
            if m and m.group("sev") == "error":
                findings.append(
                    Finding(
                        tool="mypy",
                        rule=m.group("code") or "error",
                        message=m.group("msg"),
                        severity=Severity.medium,
                        file=m.group("file"),
                        line=int(m.group("line")),
                    )
                )
        if mypy.exit_code not in (0, 1):
            logs.append("mypy: " + (mypy.stderr or mypy.stdout)[-2000:])

        sources = ctx.candidate.solution_files()
        loc = max(_loc(sources), 1)
        weights = {Severity.low: 1.0, Severity.medium: 2.0, Severity.high: 4.0}
        weighted = sum(weights.get(f.severity, 1.0) for f in findings)
        density = weighted * 100.0 / max(loc, 20)  # floor avoids punishing tiny files
        score = clamp(100.0 / (1.0 + density / 10.0))
        ruff_n = sum(f.tool == "ruff" for f in findings)
        mypy_n = sum(f.tool == "mypy" for f in findings)
        complexity = [f for f in findings if f.rule == "C901"]
        status = (
            StageStatus.passed
            if not findings
            else StageStatus.warning
            if score >= 50
            else StageStatus.failed
        )
        if logs:
            status = StageStatus.error  # a tool failed: never report a clean bill of health
        return StageResult(
            stage=self.name,
            status=status,
            score=round(score, 2),
            summary=f"{ruff_n} lint issue(s), {mypy_n} type error(s) in {loc} LOC",
            metrics={
                "ruff_issues": ruff_n,
                "mypy_errors": mypy_n,
                "complexity_violations": len(complexity),
                "loc": loc,
                "annotation_coverage_percent": annotation_coverage(sources),
                "issues_per_100_loc": round(density, 2),
            },
            findings=findings,
            logs="\n".join(logs),
        )
