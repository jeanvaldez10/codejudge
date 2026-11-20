"""Build stage: syntax check and import of the candidate module, in the sandbox."""

from __future__ import annotations

import json

from codejudge.models import Finding, Severity, StageResult, StageStatus
from codejudge.stages.base import Stage, StageContext

_BUILD_SCRIPT = """
import importlib, json, sys, traceback
files = json.loads(sys.argv[1])
module = sys.argv[2]
errors = []
for path in files:
    try:
        with open(path, encoding="utf-8") as fh:
            compile(fh.read(), path, "exec")
    except SyntaxError as exc:
        errors.append({"file": path, "line": exc.lineno, "message": f"SyntaxError: {exc.msg}"})
if not errors:
    sys.path.insert(0, ".")
    try:
        importlib.import_module(module)
    except BaseException as exc:
        errors.append({"file": module + ".py", "line": None,
                       "message": "import failed: " + "".join(
                           traceback.format_exception_only(type(exc), exc)).strip()})
print(json.dumps({"errors": errors}))
"""


class BuildStage(Stage):
    name = "build"
    requires = ("integrity",)

    def run(self, ctx: StageContext) -> StageResult:
        module_file = f"{ctx.task.module}.py"
        if module_file not in ctx.candidate.files:
            return StageResult(
                stage=self.name,
                status=StageStatus.failed,
                score=0,
                summary=f"missing required module file '{module_file}'",
            )
        res = ctx.run(
            [
                "{python}",
                "-I",
                "-c",
                _BUILD_SCRIPT,
                json.dumps(ctx.solution_paths),
                ctx.task.module,
            ],
            timeout=min(ctx.task.limits.timeout_seconds, 30),
        )
        errors: list[dict[str, object]] = []
        try:
            errors = json.loads(res.stdout.strip().splitlines()[-1])["errors"]
        except (IndexError, ValueError, KeyError):
            errors = [{"file": None, "line": None, "message": f"build {res.describe_failure()}"}]
        if res.timed_out:
            errors = [{"file": module_file, "line": None, "message": "import timed out"}]
        findings = [
            Finding(
                tool="python",
                rule="build",
                message=str(e["message"]),
                severity=Severity.high,
                file=e.get("file") if isinstance(e.get("file"), str) else None,
                line=e.get("line") if isinstance(e.get("line"), int) else None,
            )
            for e in errors
        ]
        ok = not findings
        return StageResult(
            stage=self.name,
            status=StageStatus.passed if ok else StageStatus.failed,
            score=100 if ok else 0,
            summary="compiled and imported cleanly" if ok else findings[0].message,
            findings=findings,
            logs=res.stderr[-4000:],
        )
