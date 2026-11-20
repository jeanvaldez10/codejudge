"""Integrity stage: host-side AST inspection for harness tampering.

``ast.parse`` never executes code, so this is safe to run outside the
sandbox. It catches the common ways generated code "games" an evaluator:
reaching into the test runner, reading the hidden tests or harness output,
killing the interpreter to skip assertions, patching builtins, and prompt
injection aimed at the LLM reviewer.
"""

from __future__ import annotations

import ast
import re

from codejudge.models import Finding, Severity, StageResult, StageStatus
from codejudge.stages.base import Stage, StageContext

_FORBIDDEN_IMPORTS = {"pytest", "_pytest", "coverage", "pluggy", "unittest.mock", "ctypes"}
_FORBIDDEN_CALLS = {
    ("os", "_exit"),
    ("os", "kill"),
    ("sys", "settrace"),
    ("sys", "setprofile"),
    ("sys", "_getframe"),
    ("inspect", "stack"),
    ("inspect", "currentframe"),
    ("inspect", "getouterframes"),
}
_SUSPICIOUS_STRINGS = re.compile(r"_cj_|CJ_OUT|/out\b|_cj_tests")
_PROMPT_INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior|above) instructions|you are (an? )?(ai|llm|grader|judge)"
    r"|(rate|score|grade) (this|the) (code|solution|submission)|system prompt)",
    re.IGNORECASE,
)


def _dotted(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return tuple(reversed(parts))


def inspect_source(path: str, source: str) -> list[Finding]:
    findings: list[Finding] = []

    def add(rule: str, msg: str, line: int | None, sev: Severity = Severity.critical) -> None:
        findings.append(
            Finding(tool="integrity", rule=rule, message=msg, severity=sev, file=path, line=line)
        )

    for m in _PROMPT_INJECTION.finditer(source):
        line = source.count("\n", 0, m.start()) + 1
        add("prompt-injection", f"text addressed to an AI reviewer: {m.group(0)!r}", line)
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return findings  # reported by the build stage
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                if name in _FORBIDDEN_IMPORTS or name.split(".")[0] in {"_pytest", "pytest"}:
                    add("harness-import", f"imports test/runtime internals: {name}", node.lineno)
        elif isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            if len(dotted) >= 2 and (dotted[-2], dotted[-1]) in _FORBIDDEN_CALLS:
                add("interpreter-tampering", f"calls {'.'.join(dotted)}", node.lineno)
            if dotted in {("__import__",), ("importlib", "import_module")} and any(
                isinstance(a, ast.Constant) and a.value in _FORBIDDEN_IMPORTS for a in node.args
            ):
                add("harness-import", "dynamically imports test internals", node.lineno)
        elif isinstance(node, ast.Assign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                d = _dotted(t) if isinstance(t, ast.Attribute) else ()
                if d[:1] in {("builtins",), ("__builtins__",)} or (
                    isinstance(t, ast.Subscript) and _dotted(t.value) == ("sys", "modules")
                ):
                    add("builtins-patching", "patches builtins or sys.modules", node.lineno)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _SUSPICIOUS_STRINGS.search(node.value)
        ):
            add("harness-probe", "references evaluator internals", node.lineno, Severity.high)
    return findings


class IntegrityStage(Stage):
    name = "integrity"

    def run(self, ctx: StageContext) -> StageResult:
        findings: list[Finding] = []
        for path, source in sorted(ctx.candidate.solution_files().items()):
            findings.extend(inspect_source(path, source))
        if len(ctx.candidate.files) and any(
            len(s.encode()) > 256 * 1024 for s in ctx.candidate.files.values()
        ):
            findings.append(
                Finding(
                    tool="integrity",
                    rule="oversized-file",
                    message="file exceeds 256 KiB",
                    severity=Severity.high,
                )
            )
        blocking = [f for f in findings if f.severity in (Severity.critical, Severity.high)]
        return StageResult(
            stage=self.name,
            status=StageStatus.failed if blocking else StageStatus.passed,
            score=0 if blocking else 100,
            summary=(
                f"{len(blocking)} integrity violation(s): "
                + "; ".join(f.message for f in blocking[:3])
                if blocking
                else "no harness tampering detected"
            ),
            findings=findings,
        )
