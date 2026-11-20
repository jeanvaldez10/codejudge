"""Isolation tests against the real Docker sandbox.

Each test submits deliberately hostile code and asserts the container
contains it. Skipped automatically when Docker or the image is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codejudge.models import ResourceLimits
from codejudge.pipeline import evaluate
from codejudge.sandbox.docker import DockerSandbox

from .conftest import requires_docker

pytestmark = [pytest.mark.docker, requires_docker]

LIMITS = ResourceLimits(timeout_seconds=10, memory_mb=128, cpus=0.5, pids=32)


@pytest.fixture
def sandbox() -> DockerSandbox:
    return DockerSandbox(image="codejudge-sandbox:latest")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    tmp_path.chmod(0o755)
    return tmp_path


def py(sandbox: DockerSandbox, ws: Path, code: str, limits: ResourceLimits = LIMITS):
    return sandbox.run(ws, ["python", "-c", code], limits)


def test_no_network(sandbox, ws):
    res = py(sandbox, ws, "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)")
    assert res.exit_code != 0
    assert "Network is unreachable" in res.stderr or "OSError" in res.stderr


def test_workspace_and_root_are_read_only(sandbox, ws):
    res = py(sandbox, ws, "open('/workspace/x', 'w')")
    assert res.exit_code != 0 and "Read-only file system" in res.stderr
    res = py(sandbox, ws, "open('/usr/local/lib/evil.py', 'w')")
    assert res.exit_code != 0


def test_runs_as_unprivileged_user(sandbox, ws):
    res = py(sandbox, ws, "import os; print(os.getuid())")
    assert res.stdout.strip() == "10001"


def test_memory_bomb_is_killed(sandbox, ws):
    res = py(sandbox, ws, "x = bytearray(1024 * 1024 * 1024)")
    assert not res.ok
    assert res.oom_killed or "MemoryError" in res.stderr


def test_fork_bomb_is_contained(sandbox, ws):
    code = (
        "import os\n"
        "n = 0\n"
        "try:\n"
        "    for _ in range(1000):\n"
        "        if os.fork() == 0:\n"
        "            import time; time.sleep(30); os._exit(0)\n"
        "        n += 1\n"
        "except OSError:\n"
        "    print('blocked after', n)\n"
    )
    res = py(sandbox, ws, code)
    assert "blocked after" in res.stdout
    assert int(res.stdout.split()[-1]) < LIMITS.pids


def test_infinite_loop_times_out(sandbox, ws):
    res = py(sandbox, ws, "while True: pass", LIMITS.model_copy(update={"timeout_seconds": 2}))
    assert res.timed_out


def test_output_dir_is_the_only_writable_path(sandbox, ws):
    res = py(sandbox, ws, "import os; open(os.environ['CJ_OUT'] + '/r.json', 'w').write('{}')")
    assert res.ok and res.outputs == {"r.json": "{}"}


def test_full_pipeline_in_docker(sandbox, task, candidate_a, candidate_b):
    task = task.model_copy(update={"benchmarks": task.benchmarks[:1]})
    report = evaluate(task, [candidate_a, candidate_b], sandbox)
    by = {c.label: c for c in report.candidates}
    assert by["Model A"].verdict.value == "pass"
    assert by["Model B"].scorecard.security == "fail"
    assert report.ranking == ["Model A", "Model B"]
