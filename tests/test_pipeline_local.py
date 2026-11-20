"""End-to-end pipeline runs on the local backend (the Docker variant lives in
test_docker_sandbox.py)."""

import pytest

from codejudge.models import Candidate, StageStatus, Verdict
from codejudge.pipeline import evaluate
from codejudge.report import redact_hidden, render_markdown
from codejudge.sandbox.local import LocalSandbox
from codejudge.stages.llm_review import CriterionScore, Review


@pytest.fixture
def fast_task(task):
    # Keep the suite quick: Model C's quadratic merge would otherwise run to the limit.
    return task.model_copy(update={"limits": task.limits.model_copy(update={"timeout_seconds": 8})})


@pytest.fixture(scope="module")
def _cache():
    return {}


def run(task, candidates, **kw):
    return evaluate(task, candidates, LocalSandbox(), parallelism=3, **kw)


def test_full_comparison(fast_task, candidate_a, candidate_b, candidate_c):
    report = run(fast_task, [candidate_a, candidate_b, candidate_c])
    by = {c.label: c for c in report.candidates}
    a, b, c = by["Model A"], by["Model B"], by["Model C"]

    assert report.ranking[0] == "Model A"
    assert a.verdict == Verdict.passed
    assert a.scorecard.functional_correctness == 100
    assert a.scorecard.edge_case_handling == 100
    assert a.scorecard.test_coverage == 100
    assert a.scorecard.security == "pass"

    # B is fast and mostly correct but uses eval(): the security gate fails it.
    assert b.verdict == Verdict.failed and "security" in b.gates_failed
    assert b.scorecard.overall <= 49
    assert b.scorecard.edge_case_handling < 100

    # C mutates input, misses touching intervals, and is quadratic.
    assert c.scorecard.edge_case_handling < 100
    perf = next(s for s in c.stages if s.stage == "performance")
    assert perf.status == StageStatus.failed
    assert c.scorecard.performance_median_ms is None  # no flattering partial geomean
    assert c.scorecard.static_quality < a.scorecard.static_quality

    md = render_markdown(report)
    assert "| Functional correctness | 100% |" in md


def test_hidden_failures_are_redacted(fast_task, candidate_b):
    report = run(fast_task, [candidate_b], selected_stages=["hidden_tests"])
    hidden = next(s for s in report.candidates[0].stages if s.stage == "hidden_tests")
    assert any(t.outcome != "passed" and t.message for t in hidden.tests)
    public = redact_hidden(report)
    hidden_pub = next(s for s in public.candidates[0].stages if s.stage == "hidden_tests")
    assert hidden_pub.tests == [] and hidden_pub.logs == ""
    assert hidden_pub.metrics["passed"] == hidden.metrics["passed"]


def test_build_failure_gates_everything(fast_task):
    broken = Candidate(label="Broken", files={"solution.py": "def merge_intervals(:\n"})
    rep = run(fast_task, [broken]).candidates[0]
    assert rep.verdict == Verdict.failed and "build" in rep.gates_failed
    assert rep.scorecard.overall == 0
    statuses = {s.stage: s.status for s in rep.stages}
    assert statuses["visible_tests"] == StageStatus.skipped


def test_missing_module_fails_build(fast_task):
    rep = run(fast_task, [Candidate(label="X", files={"other.py": "x = 1\n"})]).candidates[0]
    assert "build" in rep.gates_failed


def test_runner_crash_counts_as_failure(fast_task):
    """Killing the interpreter mid-test (obfuscated so static checks miss it)
    must not let a candidate escape scoring."""
    sneaky = Candidate(
        label="Sneaky",
        files={
            "solution.py": (
                "def merge_intervals(x):\n"
                "    getattr(__import__('o' + 's'), '_e' + 'xit')(0)\n\n"
                "def parse_intervals(s):\n    return []\n"
            )
        },
    )
    rep = run(fast_task, [sneaky], selected_stages=["visible_tests"]).candidates[0]
    vis = next(s for s in rep.stages if s.stage == "visible_tests")
    assert vis.status == StageStatus.failed and vis.score == 0
    assert rep.verdict == Verdict.failed


def test_integrity_violation_zeroes_score(fast_task, candidate_a):
    files = dict(candidate_a.files)
    files["solution.py"] += "\nimport pytest  # reach into the runner\n"
    rep = run(fast_task, [Candidate(label="T", files=files)]).candidates[0]
    assert "integrity" in rep.gates_failed and rep.scorecard.overall == 0


def test_llm_review_is_capped_and_cannot_rescue(fast_task, candidate_b):
    def glowing(system: str, prompt: str) -> Review:
        assert "<candidate_code>" in prompt
        assert "test_hidden" not in prompt  # hidden test code/names never reach the LLM
        return Review(
            criteria=[
                CriterionScore(criterion=c, score=5, justification="great")
                for c in fast_task.rubric
            ],
            suspected_bugs=[],
            concerns=[],
            time_complexity="O(n log n)",
            summary="perfect",
        )

    rep = run(fast_task, [candidate_b], review_fn=glowing).candidates[0]
    assert rep.scorecard.llm_quality == 100
    assert rep.verdict == Verdict.failed  # security gate still wins
    assert rep.scorecard.overall <= 49
