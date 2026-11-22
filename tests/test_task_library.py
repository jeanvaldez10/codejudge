"""Every task in the library must be solvable: its reference solution must
pass all visible and hidden tests, build cleanly, raise no security gate, and
meet its own performance budgets.

This guards against the most damaging evaluation bug: a wrong hidden test
silently penalising correct candidates.
"""

from pathlib import Path

import pytest

from codejudge.loader import discover_tasks, load_reference, load_task
from codejudge.models import StageStatus
from codejudge.pipeline import evaluate
from codejudge.sandbox.local import LocalSandbox

TASKS = discover_tasks(Path(__file__).resolve().parents[1] / "tasks")


def test_library_is_populated():
    assert len(TASKS) >= 8


@pytest.mark.parametrize("task_dir", TASKS, ids=lambda p: p.name)
def test_task_is_well_formed(task_dir):
    task = load_task(task_dir)
    assert task.id == task_dir.name
    assert any(s.hidden for s in task.tests), "every task needs held-out tests"
    assert any(not s.hidden for s in task.tests), "generators need example tests"
    assert load_reference(task_dir) is not None, "every task needs a reference solution"


@pytest.mark.parametrize("task_dir", TASKS, ids=lambda p: p.name)
def test_reference_solution_passes(task_dir):
    task = load_task(task_dir)
    ref = load_reference(task_dir)
    report = evaluate(
        task,
        [ref],
        LocalSandbox(),
        selected_stages=["visible_tests", "hidden_tests", "security", "performance"],
    )
    rep = report.candidates[0]
    stages = {s.stage: s for s in rep.stages}
    for name in ("visible_tests", "hidden_tests"):
        failing = [t.nodeid for t in stages[name].tests if t.outcome != "passed"]
        assert stages[name].status == StageStatus.passed, f"{name} failing: {failing}"
    assert stages["security"].status == StageStatus.passed, stages["security"].findings
    perf = stages["performance"]
    assert perf.status in (StageStatus.passed, StageStatus.skipped), perf.benchmarks
    assert rep.gates_failed == []
