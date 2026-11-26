import pytest

from codejudge.models import (
    BenchmarkResult,
    CandidateReport,
    EvaluationReport,
    Scorecard,
    StageResult,
    StageStatus,
    TestCaseResult,
    TestCategory,
    Verdict,
)
from codejudge.report import render_markdown
from codejudge.scoring import (
    INTEGRITY_BUILD_OVERALL,
    OTHER_GATE_CAP,
    apply_relative_performance,
    build_scorecard,
    finalize,
    rank,
)
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


def _high_score_stages(tests):
    """Signals whose weighted total sits well above the 49 cap."""
    return [
        stage("visible_tests", tests=tests),
        stage("static_analysis", score=100),
        stage("performance", score=100),
        stage("llm_review", score=100),
    ]


def test_gate_caps_are_zero_and_forty_nine():
    assert INTEGRITY_BUILD_OVERALL == 0.0
    assert OTHER_GATE_CAP == 49.0


def test_build_and_integrity_failure_zero_overall():
    tests = [tc(TestCategory.correctness, True)]
    security = stage("security", score=100)
    for gated in (
        stage("build", status=StageStatus.failed, score=0),
        stage("integrity", status=StageStatus.failed, score=0),
    ):
        stages = [gated, security, *_high_score_stages(tests)]
        if gated.stage != "build":
            stages.insert(0, stage("build"))
        r = report("a", stages)
        finalize(r)
        assert r.verdict == Verdict.failed
        assert gated.stage in r.gates_failed
        assert r.scorecard.overall == 0.0


def test_build_failure_outranks_the_security_cap():
    tests = [tc(TestCategory.correctness, True)]
    r = report(
        "a",
        [
            stage("integrity", status=StageStatus.failed, score=0),
            stage("build", status=StageStatus.failed, score=0),
            stage("security", status=StageStatus.failed, score=0),
            *_high_score_stages(tests),
        ],
    )
    finalize(r)
    assert r.scorecard.overall == 0.0
    assert set(r.gates_failed) >= {"integrity", "build", "security"}


def test_security_and_correctness_gates_cap_at_49():
    passing = [tc(TestCategory.correctness, True)]
    security = report(
        "sec",
        [
            stage("build"),
            stage("security", status=StageStatus.failed, score=0),
            *_high_score_stages(passing),
        ],
    )
    finalize(security)
    assert security.verdict == Verdict.failed
    assert security.gates_failed == ["security"]
    assert security.scorecard.overall == 49.0

    weak = [tc(TestCategory.correctness, False)] * 3 + [tc(TestCategory.correctness, True)]
    correctness = report(
        "cor",
        [
            stage("build"),
            stage("security", score=100),
            stage("visible_tests", status=StageStatus.failed, tests=weak),
            stage("static_analysis", score=100),
            stage("performance", score=100),
            stage("llm_review", score=100),
        ],
    )
    finalize(correctness)
    assert "functional_correctness" in correctness.gates_failed
    assert correctness.scorecard.functional_correctness == 25.0
    assert correctness.scorecard.overall == 49.0


def test_gate_cap_does_not_raise_a_low_score():
    r = report(
        "a",
        [
            stage("build"),
            stage("static_analysis", score=20),
            stage("security", status=StageStatus.failed, score=0),
        ],
    )
    finalize(r)
    assert r.gates_failed == ["security"]
    assert r.scorecard.overall == 10.0


def test_rank_prefers_clean_pass_over_higher_warned_score():
    clean = CandidateReport(
        label="clean",
        verdict=Verdict.passed,
        scorecard=Scorecard(overall=60, functional_correctness=70),
        stages=[],
    )
    warned = CandidateReport(
        label="warned",
        verdict=Verdict.passed_with_warnings,
        scorecard=Scorecard(overall=95, functional_correctness=100),
        stages=[],
    )
    failed = CandidateReport(
        label="failed",
        verdict=Verdict.failed,
        scorecard=Scorecard(overall=99, functional_correctness=100),
        stages=[],
    )
    assert rank([warned, failed, clean]) == ["clean", "warned", "failed"]


def test_rank_breaks_overall_ties_on_functional_correctness():
    low = CandidateReport(
        label="low",
        verdict=Verdict.passed,
        scorecard=Scorecard(overall=80, functional_correctness=60),
        stages=[],
    )
    high = CandidateReport(
        label="high",
        verdict=Verdict.passed,
        scorecard=Scorecard(overall=80, functional_correctness=90),
        stages=[],
    )
    assert rank([low, high]) == ["high", "low"]


@pytest.mark.parametrize(
    "stage_name",
    [
        "integrity",
        "build",
        "visible_tests",
        "hidden_tests",
        "candidate_tests",
        "static_analysis",
        "security",
    ],
)
def test_stage_error_is_incomplete_and_leaves_overall_unset(stage_name):
    crashed = stage(stage_name, status=StageStatus.error, score=None)
    stages = [crashed] if stage_name == "build" else [stage("build"), crashed]
    r = report("a", stages)
    finalize(r)
    assert r.verdict == Verdict.incomplete
    assert r.scorecard.overall is None


def test_performance_or_llm_error_stays_a_dropped_signal():
    tests = [tc(TestCategory.correctness, True)]
    for name in ("performance", "llm_review"):
        r = report(
            "a",
            [
                stage("build"),
                stage("visible_tests", tests=tests),
                stage(name, status=StageStatus.error, score=None),
            ],
        )
        finalize(r)
        assert r.verdict == Verdict.passed
        assert r.scorecard.overall == 100.0


def test_incomplete_sorts_with_fail_after_measured_scores():
    clean = CandidateReport(
        label="clean", verdict=Verdict.passed, scorecard=Scorecard(overall=60), stages=[]
    )
    failed = CandidateReport(
        label="failed", verdict=Verdict.failed, scorecard=Scorecard(overall=0), stages=[]
    )
    outage = CandidateReport(
        label="outage", verdict=Verdict.incomplete, scorecard=Scorecard(), stages=[]
    )
    assert rank([outage, failed, clean]) == ["clean", "failed", "outage"]


def test_markdown_renders_incomplete_without_a_fake_zero():
    r = report("a", [stage("static_analysis", status=StageStatus.error, score=None)])
    finalize(r)
    md = render_markdown(
        EvaluationReport(
            task_id="t",
            task_title="T",
            candidates=[r],
            ranking=["a"],
            weights={},
        )
    )
    assert "incomplete" in md
    assert "overall n/a" in md
