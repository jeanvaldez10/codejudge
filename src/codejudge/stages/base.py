"""Stage framework: shared context, workspace materialisation, helpers."""

from __future__ import annotations

import abc
import json
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from codejudge.harness import HARNESS_FILES
from codejudge.harness import read as read_harness
from codejudge.models import Candidate, StageResult, StageStatus, Task
from codejudge.sandbox import ExecResult, Sandbox

TASK_TESTS_DIR = "_cj_tests"


@dataclass
class StageContext:
    task: Task
    candidate: Candidate
    sandbox: Sandbox
    workspace: Path
    results: dict[str, StageResult] = field(default_factory=dict)

    @property
    def solution_paths(self) -> list[str]:
        return sorted(self.candidate.solution_files())

    @property
    def candidate_test_paths(self) -> list[str]:
        return sorted(self.candidate.test_files())

    def run(self, command: list[str], *, timeout: float | None = None) -> ExecResult:
        limits = self.task.limits
        if timeout is not None:
            limits = limits.model_copy(update={"timeout_seconds": timeout})
        return self.sandbox.run(self.workspace, command, limits)

    def write_config(self, name: str, data: object) -> str:
        """Configs are written before the (read-only) run, never by the sandbox."""
        path = self.workspace / f"_cj_{name}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        path.chmod(0o644)
        return path.name


@contextmanager
def materialize_workspace(task: Task, candidate: Candidate) -> Iterator[Path]:
    """Lay out candidate files, task test suites and harness scripts on disk.

    Paths were validated by the ``Candidate`` model, but we re-check that each
    resolved path stays inside the workspace as defence in depth.
    """
    import os

    root = Path(tempfile.mkdtemp(prefix="cj-ws-", dir=os.environ.get("CODEJUDGE_WORK_DIR")))
    try:
        files: dict[str, str] = dict(candidate.files)
        for suite in task.tests:
            files[f"{TASK_TESTS_DIR}/{suite.name}.py"] = suite.code
        for name in HARNESS_FILES:
            files[name] = read_harness(name)
        for rel, content in files.items():
            target = (root / PurePosixPath(rel)).resolve()
            if root.resolve() not in target.parents:
                raise ValueError(f"path escapes workspace: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            target.chmod(0o644)
        for d in [root, *[p for p in root.rglob("*") if p.is_dir()]]:
            d.chmod(0o755)
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


class Stage(abc.ABC):
    name: str
    #: Stages that must have passed (not failed/error) for this one to run.
    requires: tuple[str, ...] = ()

    def execute(self, ctx: StageContext) -> StageResult:
        for dep in self.requires:
            dep_result = ctx.results.get(dep)
            if dep_result is not None and dep_result.status in (
                StageStatus.failed,
                StageStatus.error,
            ):
                return StageResult(
                    stage=self.name,
                    status=StageStatus.skipped,
                    summary=f"skipped: prerequisite stage '{dep}' did not pass",
                )
        start = time.perf_counter()
        try:
            result = self.run(ctx)
        except Exception as exc:  # stage infrastructure failure, not a candidate failure
            result = StageResult(
                stage=self.name,
                status=StageStatus.error,
                summary=f"stage crashed: {type(exc).__name__}: {exc}",
            )
        result.duration_ms = round((time.perf_counter() - start) * 1000, 1)
        return result

    @abc.abstractmethod
    def run(self, ctx: StageContext) -> StageResult: ...


def parse_json_output(res: ExecResult, key: str | None = None) -> object | None:
    raw = res.outputs.get(key) if key else res.stdout
    if not raw:
        return None
    try:
        data: object = json.loads(raw)
        return data
    except json.JSONDecodeError:
        return None


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))
