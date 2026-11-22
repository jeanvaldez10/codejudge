import json
import math
import shutil

import pytest

from codejudge.benchmark import (
    build_leaderboard,
    evaluate_run,
    generate_run,
    load_manifest,
    pass_at_k,
    render_leaderboard,
)
from codejudge.generation import DirectoryGenerator
from codejudge.sandbox.local import LocalSandbox

from .conftest import EXAMPLE


@pytest.mark.parametrize(
    "n, c, k, expected",
    [
        (5, 0, 1, 0.0),
        (5, 5, 1, 1.0),
        (5, 2, 1, 0.4),
        (5, 1, 5, 1.0),
        (10, 3, 2, 1 - math.comb(7, 2) / math.comb(10, 2)),
    ],
)
def test_pass_at_k(n, c, k, expected):
    assert pass_at_k(n, c, k) == pytest.approx(expected)


def _assistant_dirs(tmp_path):
    """alpha: two correct samples. beta: one sample that uses eval(), one missing."""
    cands = EXAMPLE / "candidates"
    alpha = tmp_path / "alpha" / "interval-merge"
    beta = tmp_path / "beta" / "interval-merge"
    shutil.copytree(cands / "model_a", alpha / "1")
    shutil.copytree(cands / "model_a", alpha / "2")
    shutil.copytree(cands / "model_b", beta / "1")
    return DirectoryGenerator("alpha", tmp_path / "alpha"), DirectoryGenerator(
        "beta", tmp_path / "beta"
    )


def test_end_to_end_run(tmp_path):
    run = tmp_path / "run"
    alpha, beta = _assistant_dirs(tmp_path)
    stages = ["visible_tests", "hidden_tests", "security"]
    generate_run(run, [EXAMPLE], [alpha, beta], samples=2, stages=stages)

    meta = json.loads((run / "candidates/interval-merge/beta/2/meta.json").read_text())
    assert "no sample 2" in meta["error"]

    evaluate_run(run, LocalSandbox())
    lb = build_leaderboard(run, n_boot=200)

    by = {g.generator: g for g in lb.generators}
    assert [g.generator for g in lb.generators] == ["alpha", "beta"]
    assert by["alpha"].pass_at_1 == 1.0 and by["alpha"].pass_at_k[2] == 1.0
    # beta's real sample fails the security gate and the missing one counts as a failure.
    assert by["beta"].pass_at_1 == 0.0
    assert by["beta"].generation_errors == 1
    assert by["beta"].security_failure_rate == 1.0
    assert lb.per_task["interval-merge"]["alpha"].solved == 2

    md = render_leaderboard(lb)
    assert "| 1 | **alpha** | 100%" in md
    assert "pass@2" in md


def test_resume_skips_existing_work(tmp_path):
    run = tmp_path / "run"
    alpha, _ = _assistant_dirs(tmp_path)

    calls = []

    class Counting(DirectoryGenerator):
        def generate(self, task, sample):
            calls.append(sample)
            return super().generate(task, sample)

    gen = Counting("alpha", alpha.root)
    generate_run(run, [EXAMPLE], [gen], samples=2, stages=["visible_tests"])
    generate_run(run, [EXAMPLE], [gen], samples=2, stages=["visible_tests"])
    assert sorted(calls) == [1, 2]  # second call generated nothing new
    assert load_manifest(run).samples == 2


def test_leaderboard_requires_results(tmp_path):
    run = tmp_path / "run"
    alpha, _ = _assistant_dirs(tmp_path)
    generate_run(run, [EXAMPLE], [alpha], samples=1)
    with pytest.raises(FileNotFoundError):
        build_leaderboard(run)
