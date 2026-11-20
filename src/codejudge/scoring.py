"""Turn stage results into scorecards, verdicts and a ranking.

Principles:

* Deterministic evidence dominates. The LLM review is capped at
  ``WEIGHTS['llm_quality']`` and is renormalised away when unavailable.
* Hard gates override the weighted score: a candidate that does not build,
  tampers with the harness, ships a high-severity vulnerability, or fails
  most functional tests is a ``fail`` no matter how polished it looks.
* Performance without an explicit budget is scored relative to the fastest
  candidate in the same run.
"""

from __future__ import annotations

import math

from codejudge.models import (
    CandidateReport,
    Scorecard,
    StageResult,
    StageStatus,
    TestCaseResult,
    TestCategory,
    Verdict,
)

WEIGHTS: dict[str, float] = {
    "functional_correctness": 0.35,
    "edge_case_handling": 0.15,
    "integration": 0.05,
    "test_coverage": 0.05,
    "static_quality": 0.10,
    "security_score": 0.10,
    "performance_score": 0.10,
    "llm_quality": 0.10,
}
CORRECTNESS_GATE = 50.0


def _rate(tests: list[TestCaseResult], category: TestCategory | None = None) -> float | None:
    ts = [
        t for t in tests if t.outcome != "skipped" and (category is None or t.category == category)
    ]
    if not ts:
        return None
    return round(100.0 * sum(t.outcome == "passed" for t in ts) / len(ts), 2)


def _ok(r: StageResult | None) -> bool:
    return r is not None and r.status not in (StageStatus.skipped, StageStatus.error)


def build_scorecard(stages: dict[str, StageResult]) -> Scorecard:
    task_tests: list[TestCaseResult] = []
    aborted = False
    for name in ("visible_tests", "hidden_tests"):
        r = stages.get(name)
        if r is not None:
            task_tests += r.tests
            aborted |= r.status == StageStatus.failed and r.metrics.get("total") is None
    sc = Scorecard()
    if task_tests or aborted:
        sc.functional_correctness = _rate(task_tests, TestCategory.correctness) or (
            0.0 if aborted else None
        )
        sc.edge_case_handling = _rate(task_tests, TestCategory.edge_case)
        sc.integration = _rate(task_tests, TestCategory.integration)
        if sc.functional_correctness is None and not aborted:
            sc.functional_correctness = _rate(task_tests)
    ct = stages.get("candidate_tests")
    if _ok(ct) and ct is not None:
        sc.test_coverage = ct.score
    st = stages.get("static_analysis")
    if _ok(st) and st is not None:
        sc.static_quality = st.score
    sec = stages.get("security")
    if _ok(sec) and sec is not None:
        sc.security_score = sec.score
        sc.security = "fail" if sec.status == StageStatus.failed else "pass"
    perf = stages.get("performance")
    if _ok(perf) and perf is not None:
        sc.performance_median_ms = perf.metrics.get("geomean_median_ms")
        sc.performance_score = perf.score
    llm = stages.get("llm_review")
    if _ok(llm) and llm is not None:
        sc.llm_quality = llm.score
    return sc


def apply_relative_performance(reports: list[CandidateReport]) -> None:
    """Score unbudgeted benchmarks relative to the fastest candidate (geomean of
    per-benchmark ``fastest / mine`` ratios)."""
    best: dict[str, float] = {}
    for rep in reports:
        perf = next((s for s in rep.stages if s.stage == "performance"), None)
        for b in perf.benchmarks if perf else []:
            if b.ok and b.median_ms and b.budget_ms is None:
                best[b.name] = min(best.get(b.name, math.inf), b.median_ms)
    if not best:
        return
    for rep in reports:
        perf = next((s for s in rep.stages if s.stage == "performance"), None)
        if perf is None or perf.status in (StageStatus.skipped, StageStatus.error):
            continue
        ratios: list[float] = []
        for b in perf.benchmarks:
            if b.budget_ms is not None:
                ratios.append(min(1.0, b.budget_ms / b.median_ms) if b.ok and b.median_ms else 0.0)
            elif b.name in best:
                ratios.append(best[b.name] / b.median_ms if b.ok and b.median_ms else 0.0)
        if ratios:
            geo = 0.0 if min(ratios) == 0 else math.exp(sum(map(math.log, ratios)) / len(ratios))
            perf.score = round(100.0 * geo, 2)
            rep.scorecard.performance_score = perf.score


def finalize(rep: CandidateReport) -> None:
    """Compute overall score, gates and verdict (call after relative scoring)."""
    sc = rep.scorecard
    stages = {s.stage: s for s in rep.stages}
    gates: list[str] = []
    if stages.get("integrity") and stages["integrity"].status == StageStatus.failed:
        gates.append("integrity")
    if stages.get("build") and stages["build"].status != StageStatus.passed:
        gates.append("build")
    if sc.security == "fail":
        gates.append("security")
    if sc.functional_correctness is not None and sc.functional_correctness < CORRECTNESS_GATE:
        gates.append("functional_correctness")

    values = {k: getattr(sc, k) for k in WEIGHTS}
    available = {k: v for k, v in values.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in available)
    overall = sum(WEIGHTS[k] * v for k, v in available.items()) / total_w if total_w else 0.0
    if "build" in gates or "integrity" in gates:
        overall = 0.0
    elif gates:
        overall = min(overall, 49.0)  # a gated candidate can never outrank a passing one
    sc.overall = round(overall, 2)
    rep.gates_failed = gates

    if gates:
        rep.verdict = Verdict.failed
    elif any(
        s.status in (StageStatus.warning, StageStatus.failed)
        for s in rep.stages
        if s.stage != "llm_review"
    ):
        rep.verdict = Verdict.passed_with_warnings
    else:
        rep.verdict = Verdict.passed


def rank(reports: list[CandidateReport]) -> list[str]:
    order = {Verdict.passed: 0, Verdict.passed_with_warnings: 1, Verdict.failed: 2}
    return [
        r.label
        for r in sorted(
            reports,
            key=lambda r: (
                order[r.verdict],
                -r.scorecard.overall,
                -(r.scorecard.functional_correctness or 0),
            ),
        )
    ]
