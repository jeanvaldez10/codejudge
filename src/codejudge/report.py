"""Render evaluation reports (Markdown) and produce redacted public views."""

from __future__ import annotations

from codejudge.models import CandidateReport, EvaluationReport, StageStatus

_ICON = {
    StageStatus.passed: "✅",
    StageStatus.warning: "⚠️",
    StageStatus.failed: "❌",
    StageStatus.error: "💥",
    StageStatus.skipped: "⏭️",
}


def redact_hidden(report: EvaluationReport) -> EvaluationReport:
    """Candidate-facing view: hidden test names and failure output removed, so
    the report cannot be used to overfit the hidden suite."""
    out = report.model_copy(deep=True)
    for cand in out.candidates:
        for stage in cand.stages:
            if stage.stage == "hidden_tests":
                stage.tests = []
                stage.logs = ""
            for t in stage.tests:
                if t.hidden:
                    t.message = None
    return out


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0f}%"


def comparison_rows(report: EvaluationReport) -> list[tuple[str, list[str]]]:
    cs = report.candidates
    sc = [c.scorecard for c in cs]
    return [
        ("Verdict", [c.verdict.value for c in cs]),
        ("Overall score", [f"{s.overall:.1f}" for s in sc]),
        ("Functional correctness", [_pct(s.functional_correctness) for s in sc]),
        ("Edge-case handling", [_pct(s.edge_case_handling) for s in sc]),
        ("Integration", [_pct(s.integration) for s in sc]),
        ("Own-test coverage", [_pct(s.test_coverage) for s in sc]),
        ("Static quality", [_pct(s.static_quality) for s in sc]),
        ("Security checks", [(s.security or "n/a").capitalize() for s in sc]),
        (
            "Execution time (geomean median)",
            [
                "n/a" if s.performance_median_ms is None else f"{s.performance_median_ms:.2f} ms"
                for s in sc
            ],
        ),
        ("Performance score", [_pct(s.performance_score) for s in sc]),
        ("LLM quality review (advisory)", [_pct(s.llm_quality) for s in sc]),
        ("Gates failed", [", ".join(c.gates_failed) or "—" for c in cs]),
    ]


def render_markdown(report: EvaluationReport) -> str:
    lines = [f"# CodeJudge report: {report.task_title}", ""]
    lines.append(
        f"Task `{report.task_id}` · ranking: " + " > ".join(f"**{x}**" for x in report.ranking)
    )
    lines.append("")
    header = ["Evaluation criterion", *[c.label for c in report.candidates]]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for name, vals in comparison_rows(report):
        lines.append("| " + " | ".join([name, *vals]) + " |")
    lines.append("")
    for c in report.candidates:
        lines += _candidate_section(c)
    if report.notes:
        lines.append("## Notes")
        lines += [f"- {n}" for n in report.notes]
        lines.append("")
    return "\n".join(lines)


def _candidate_section(c: CandidateReport) -> list[str]:
    title = f"## {c.label}" + (f" ({c.model})" if c.model else "")
    lines = [title, "", f"Verdict: **{c.verdict.value}** · overall {c.scorecard.overall:.1f}", ""]
    lines.append("| Stage | Status | Score | Summary |")
    lines.append("|---|---|---|---|")
    for s in c.stages:
        score = "" if s.score is None else f"{s.score:.0f}"
        summary = s.summary.replace("|", "\\|").replace("\n", " ")[:200]
        lines.append(f"| {s.stage} | {_ICON[s.status]} {s.status.value} | {score} | {summary} |")
    lines.append("")
    failing = [t for s in c.stages for t in s.tests if t.outcome != "passed" and not t.hidden][:10]
    if failing:
        lines.append("<details><summary>Failing visible tests</summary>\n")
        for t in failing:
            msg = (t.message or "").strip().splitlines()
            lines.append(f"- `{t.nodeid}` — {msg[-1] if msg else t.outcome}")
        lines.append("\n</details>\n")
    findings = [f for s in c.stages for f in s.findings if f.tool not in ("llm",)][:25]
    if findings:
        lines.append("<details><summary>Findings</summary>\n")
        for f in findings:
            loc = f"{f.file}:{f.line}" if f.file and f.line else (f.file or "")
            lines.append(f"- **{f.severity.value}** `{f.tool}/{f.rule}` {loc} — {f.message}")
        lines.append("\n</details>\n")
    llm = next((s for s in c.stages if s.stage == "llm_review" and s.metrics.get("rubric")), None)
    if llm:
        lines.append("<details><summary>LLM rubric review (advisory)</summary>\n")
        for k, v in llm.metrics["rubric"].items():
            just = llm.metrics.get("justifications", {}).get(k, "")
            lines.append(f"- **{k}**: {v}/5 — {just}")
        if llm.metrics.get("time_complexity"):
            lines.append(f"- **time complexity**: {llm.metrics['time_complexity']}")
        for f in llm.findings:
            lines.append(f"- _{f.rule}_: {f.message}")
        lines.append("\n</details>\n")
    return lines
