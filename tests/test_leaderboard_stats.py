"""Statistics on a synthetic run with many tasks (no sandbox needed)."""

import json

from codejudge.benchmark import Manifest, build_leaderboard
from codejudge.models import (
    CandidateReport,
    EvaluationReport,
    Scorecard,
    StageResult,
    StageStatus,
    Verdict,
)


def _rep(label, ok, score):
    status = StageStatus.passed if ok else StageStatus.failed
    return CandidateReport(
        label=label,
        verdict=Verdict.passed if ok else Verdict.failed,
        scorecard=Scorecard(overall=score),
        stages=[StageResult(stage="hidden_tests", status=status)],
    )


def _write_run(tmp_path, n_tasks, strong_ok, weak_ok):
    run = tmp_path / "run"
    (run / "results").mkdir(parents=True)
    tasks = {f"t{i:02d}": "unused" for i in range(n_tasks)}
    Manifest(
        created_at="x", tasks=tasks, generators=["strong", "weak"], samples=1
    ).model_dump_json()
    (run / "manifest.json").write_text(
        Manifest(
            created_at="x", tasks=tasks, generators=["strong", "weak"], samples=1
        ).model_dump_json()
    )
    for i, tid in enumerate(tasks):
        reps = [_rep("strong#1", strong_ok(i), 90.0), _rep("weak#1", weak_ok(i), 40.0)]
        report = EvaluationReport(
            task_id=tid, task_title=tid, candidates=reps, ranking=[], weights={}
        )
        (run / "results" / f"{tid}.json").write_text(json.dumps(report.model_dump(mode="json")))
    return run


def test_clear_winner_is_significant(tmp_path):
    run = _write_run(tmp_path, 30, lambda i: True, lambda i: i % 3 == 0)
    lb = build_leaderboard(run, n_boot=500)
    strong, weak = lb.generators
    assert strong.generator == "strong" and strong.pass_at_1 == 1.0
    assert weak.pass_at_1 == round(10 / 30, 4)
    lo, hi = weak.pass_at_1_ci
    assert lo <= weak.pass_at_1 <= hi and hi - lo > 0.1
    pair = lb.pairwise[0]
    assert pair.score_diff == 50.0 and pair.significant and pair.prob_a_better == 1.0


def test_tie_is_not_significant(tmp_path):
    run = _write_run(tmp_path, 4, lambda i: i % 2 == 0, lambda i: i % 2 == 1)
    lb = build_leaderboard(run, n_boot=500)
    # Same solve rate; scores differ only by the fixed 90 vs 40 assignment.
    assert lb.generators[0].pass_at_1 == lb.generators[1].pass_at_1 == 0.5
    assert any("Only 4 tasks" in n for n in lb.notes)


def test_bootstrap_is_deterministic(tmp_path):
    run = _write_run(tmp_path, 12, lambda i: i % 2 == 0, lambda i: i % 4 == 0)
    a = build_leaderboard(run, n_boot=300, seed=1).model_dump()
    b = build_leaderboard(run, n_boot=300, seed=1).model_dump()
    assert a == b
