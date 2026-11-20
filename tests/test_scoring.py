from codejudge.models import (
    BenchmarkResult,
    CandidateReport,
    Scorecard,
    StageResult,
    StageStatus,
    TestCaseResult,
    TestCategory,
    Verdict,
)
from codejudge.scoring import apply_relative_performance, build_scorecard, finalize, rank


def tc(cat, ok, hidden=False):
    return TestCaseResult(
        nodeid=f"x::{cat}{ok}",
        suite="s",
        category=cat,
        hidden=hidden,
        outcome="passed" if ok else "failed",
    )


def stage(name, status=StageStatus.passed, score=100.0, **kw):
    return StageResult(stage=name, status=status, score=score, **kw)


def report(label, stages):
    by = {s.stage: s for s in stages}
    return CandidateReport(
        label=label, verdict=Verdict.failed, scorecard=build_scorecard(by), stages=stages
    )


def test_categories_scored_separately():
    tests = [tc(TestCategory.correctness, True)] * 3 + [tc(TestCategory.edge_case, False)]
    sc = build_scorecard({"hidden_tests": stage("hidden_tests", tests=tests)})
    assert sc.functional_correctness == 100 and sc.edge_case_handling == 0


def test_llm_weight_renormalised_when_missing():
    r = report("a", [stage("build"), stage("static_analysis", score=80)])
    finalize(r)
    assert r.scorecard.overall == 80


def test_correctness_gate():
    tests = [tc(TestCategory.correctness, False)] * 3 + [tc(TestCategory.correctness, True)]
    r = report(
        "a", [stage("build"), stage("visible_tests", status=StageStatus.failed, tests=tests)]
    )
    finalize(r)
    assert r.verdict == Verdict.failed and "functional_correctness" in r.gates_failed


def test_relative_performance():
    def perf(ms):
        return stage(
            "performance", score=None, benchmarks=[BenchmarkResult(name="b", ok=True, median_ms=ms)]
        )

    fast, slow = (
        report("fast", [stage("build"), perf(10)]),
        report("slow", [stage("build"), perf(40)]),
    )
    apply_relative_performance([fast, slow])
    assert fast.scorecard.performance_score == 100
    assert slow.scorecard.performance_score == 25


def test_rank_puts_failures_last():
    good = CandidateReport(
        label="g", verdict=Verdict.passed_with_warnings, scorecard=Scorecard(overall=60), stages=[]
    )
    bad = CandidateReport(
        label="b", verdict=Verdict.failed, scorecard=Scorecard(overall=90), stages=[]
    )
    assert rank([bad, good]) == ["g", "b"]
