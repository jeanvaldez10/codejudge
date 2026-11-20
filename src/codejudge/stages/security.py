"""Security scanning: Bandit + Semgrep (offline rules), inside the sandbox."""

from __future__ import annotations

import json
from typing import Any

from codejudge.models import Finding, Severity, StageResult, StageStatus
from codejudge.stages.base import Stage, StageContext, clamp

_BANDIT_SEV = {"LOW": Severity.low, "MEDIUM": Severity.medium, "HIGH": Severity.high}
_SEMGREP_SEV = {"INFO": Severity.low, "WARNING": Severity.medium, "ERROR": Severity.high}
_PENALTY = {Severity.low: 5, Severity.medium: 15, Severity.high: 40, Severity.critical: 60}


class SecurityStage(Stage):
    name = "security"
    requires = ("integrity",)

    def run(self, ctx: StageContext) -> StageResult:
        files = ctx.solution_paths
        findings: list[Finding] = []
        errors: list[str] = []
        tools_ran: list[str] = []

        bandit = ctx.run(
            ["{python}", "-m", "bandit", "-q", "-f", "json", "--exit-zero", *files], timeout=60
        )
        try:
            bandit_data = _require_results(bandit.stdout)
            for r in bandit_data["results"]:
                sev = _BANDIT_SEV.get(r.get("issue_severity", "LOW"), Severity.low)
                # Low-confidence high-severity hits are downgraded one level.
                if r.get("issue_confidence") == "LOW" and sev == Severity.high:
                    sev = Severity.medium
                findings.append(
                    Finding(
                        tool="bandit",
                        rule=f"{r.get('test_id')}:{r.get('test_name')}",
                        message=r.get("issue_text", ""),
                        severity=sev,
                        file=_norm(r.get("filename")),
                        line=r.get("line_number"),
                    )
                )
            tools_ran.append("bandit")
        except (json.JSONDecodeError, KeyError):
            errors.append("bandit: " + (bandit.stderr or bandit.stdout)[-1500:])

        semgrep = ctx.run(
            [
                "semgrep", "scan", "--config", "{rules}", "--json", "--metrics", "off",
                "--disable-version-check", "--no-git-ignore", "--quiet", *files,
            ],
            timeout=120,
        )  # fmt: skip
        try:
            semgrep_data = _require_results(semgrep.stdout)
            for r in semgrep_data["results"]:
                extra = r.get("extra", {})
                findings.append(
                    Finding(
                        tool="semgrep",
                        rule=r.get("check_id", "semgrep").split(".")[-1],
                        message=extra.get("message", ""),
                        severity=_SEMGREP_SEV.get(extra.get("severity", "INFO"), Severity.low),
                        file=_norm(r.get("path")),
                        line=(r.get("start") or {}).get("line"),
                    )
                )
            tools_ran.append("semgrep")
        except (json.JSONDecodeError, KeyError):
            errors.append("semgrep: " + (semgrep.stderr or semgrep.stdout)[-1500:])

        findings = _dedupe(findings)
        if errors:
            # Fail closed: a scanner that crashed must never read as "no findings".
            return StageResult(
                stage=self.name,
                status=StageStatus.error,
                summary=f"scanner(s) failed to run: {', '.join(e.split(':')[0] for e in errors)}",
                findings=findings,
                metrics={"tools": tools_ran},
                logs="\n".join(errors),
            )
        score = clamp(100 - sum(_PENALTY[f.severity] for f in findings))
        high = [f for f in findings if f.severity in (Severity.high, Severity.critical)]
        status = (
            StageStatus.failed if high else StageStatus.warning if findings else StageStatus.passed
        )
        counts = {s.value: sum(f.severity == s for f in findings) for s in Severity}
        return StageResult(
            stage=self.name,
            status=status,
            score=score,
            summary=(
                f"{len(high)} high-severity issue(s): {high[0].message}"
                if high
                else f"{len(findings)} low/medium finding(s)"
                if findings
                else "no security findings"
            ),
            metrics={"by_severity": counts, "tools": tools_ran},
            findings=findings,
            logs="\n".join(errors),
        )


def _require_results(stdout: str) -> dict[str, list[dict[str, Any]]]:
    data = json.loads(stdout)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise KeyError("results")
    results: dict[str, list[dict[str, Any]]] = data
    return results


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Bandit and Semgrep often flag the same line; keep the most severe."""
    order = list(Severity)
    best: dict[tuple[str | None, int | None, str], Finding] = {}
    for f in findings:
        family = _family(f)
        key = (f.file, f.line, family)
        if key not in best or order.index(f.severity) > order.index(best[key].severity):
            best[key] = f
    return list(best.values())


def _family(f: Finding) -> str:
    text = f"{f.rule} {f.message}".lower()
    for fam in (
        "eval",
        "exec",
        "shell",
        "subprocess",
        "pickle",
        "yaml",
        "sql",
        "md5",
        "sha1",
        "random",
        "password",
        "secret",
        "verify",
    ):
        if fam in text:
            return fam
    return f.rule


def _norm(path: object) -> str | None:
    if not isinstance(path, str):
        return None
    for prefix in ("./", "/workspace/"):
        if path.startswith(prefix):
            path = path[len(prefix) :]
    return path
