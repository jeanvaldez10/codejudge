"""Domain schemas shared by the API, worker, pipeline and CLI."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.py$")

# Files a candidate may never provide: they would let submitted code hook
# into, reconfigure or replace the test harness itself.
RESERVED_FILENAMES = frozenset(
    {
        "conftest.py",
        "sitecustomize.py",
        "usercustomize.py",
        "pytest.ini",
        "setup.cfg",
        "tox.ini",
        "pyproject.toml",
        "mypy.ini",
        "ruff.toml",
        ".ruff.toml",
    }
)


class TestCategory(StrEnum):
    __test__ = False  # not a pytest test class

    correctness = "correctness"
    edge_case = "edge_case"
    integration = "integration"


class TestSuite(BaseModel):
    """A pytest file owned by the task author."""

    __test__ = False  # not a pytest test class

    name: str = Field(description="File stem, e.g. 'test_basic'.")
    code: str
    category: TestCategory = TestCategory.correctness
    hidden: bool = Field(
        default=False,
        description="Hidden suites are never shown to candidates or to the LLM reviewer.",
    )

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _MODULE_RE.match(v) or not v.startswith("test_"):
            raise ValueError("test suite name must be an identifier starting with 'test_'")
        return v


class Benchmark(BaseModel):
    """A performance case. ``setup`` is trusted task code that either binds
    ``args`` (a tuple) and optionally ``kwargs`` (a dict) for a call to the
    task entrypoint, or defines ``bench(module)``, which is timed instead.
    Use ``bench`` for APIs that a single function call can't exercise,
    such as classes."""

    name: str
    setup: str
    repeat: int = Field(default=5, ge=1, le=100)
    warmup: int = Field(default=1, ge=0, le=10)
    time_budget_ms: float | None = Field(
        default=None, description="Median wall time above which the benchmark fails."
    )

    @property
    def defines_bench(self) -> bool:
        return re.search(r"^def bench\(", self.setup, re.MULTILINE) is not None


class ResourceLimits(BaseModel):
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    memory_mb: int = Field(default=512, ge=64, le=8192)
    cpus: float = Field(default=1.0, gt=0, le=8)
    pids: int = Field(default=128, ge=16, le=4096)


class Task(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    title: str
    description: str = Field(description="The prompt given to the code generator.")
    language: Literal["python"] = "python"
    module: str = Field(default="solution", description="Module candidates must provide.")
    entrypoint: str | None = Field(
        default=None, description="Callable in `module` used by benchmarks."
    )
    tests: list[TestSuite] = Field(default_factory=list)
    benchmarks: list[Benchmark] = Field(default_factory=list)
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    rubric: list[str] = Field(
        default_factory=lambda: [
            "readability",
            "maintainability",
            "idiomatic_usage",
            "error_handling",
            "algorithmic_reasoning",
        ],
        description="Qualitative criteria for the LLM reviewer.",
    )

    @field_validator("module")
    @classmethod
    def _valid_module(cls, v: str) -> str:
        if not _MODULE_RE.match(v):
            raise ValueError("module must be a valid Python identifier")
        return v

    @model_validator(mode="after")
    def _benchmarks_need_entrypoint(self) -> Task:
        if not self.entrypoint and any(not b.defines_bench for b in self.benchmarks):
            raise ValueError("benchmarks without a bench(module) function need an entrypoint")
        names = [s.name for s in self.tests]
        if len(names) != len(set(names)):
            raise ValueError("test suite names must be unique")
        return self

    def public_view(self) -> dict[str, Any]:
        """Task as shown to candidates/LLM reviewers: hidden tests removed."""
        data = self.model_dump(mode="json")
        data["tests"] = [t for t in data["tests"] if not t["hidden"]]
        return data


# ---------------------------------------------------------------------------
# Candidates and submissions
# ---------------------------------------------------------------------------


class Candidate(BaseModel):
    label: str = Field(min_length=1, max_length=80, description="e.g. 'Model A'")
    model: str | None = Field(default=None, description="Which generator produced it.")
    files: dict[str, str] = Field(
        description="Relative path -> source. Must include '<task.module>.py'. "
        "Files named test_*.py are treated as the candidate's own tests."
    )

    @field_validator("files")
    @classmethod
    def _safe_paths(cls, files: dict[str, str]) -> dict[str, str]:
        if not files:
            raise ValueError("candidate must contain at least one file")
        for path in files:
            p = PurePosixPath(path)
            if p.is_absolute() or ".." in p.parts or not _FILENAME_RE.match(path):
                raise ValueError(f"illegal file path: {path!r}")
            if p.name in RESERVED_FILENAMES or p.name.startswith("_cj_"):
                raise ValueError(f"reserved file name not allowed: {path!r}")
        return files

    def solution_files(self) -> dict[str, str]:
        return {
            k: v for k, v in self.files.items() if not PurePosixPath(k).name.startswith("test_")
        }

    def test_files(self) -> dict[str, str]:
        return {k: v for k, v in self.files.items() if PurePosixPath(k).name.startswith("test_")}


class SubmissionRequest(BaseModel):
    task: Task | None = None
    task_id: str | None = None
    candidates: list[Candidate] = Field(min_length=1)
    stages: list[str] | None = Field(
        default=None, description="Subset of stages to run; default is all."
    )

    @model_validator(mode="after")
    def _task_xor_id(self) -> SubmissionRequest:
        if (self.task is None) == (self.task_id is None):
            raise ValueError("provide exactly one of 'task' or 'task_id'")
        labels = [c.label for c in self.candidates]
        if len(labels) != len(set(labels)):
            raise ValueError("candidate labels must be unique")
        return self


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class StageStatus(StrEnum):
    passed = "passed"
    warning = "warning"
    failed = "failed"
    error = "error"  # the stage itself could not run (infra problem)
    skipped = "skipped"


class Severity(StrEnum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Finding(BaseModel):
    tool: str
    rule: str
    message: str
    severity: Severity = Severity.low
    file: str | None = None
    line: int | None = None


class TestCaseResult(BaseModel):
    __test__ = False  # not a pytest test class

    nodeid: str
    suite: str
    category: TestCategory
    hidden: bool
    outcome: Literal["passed", "failed", "error", "skipped"]
    duration_ms: float = 0.0
    # Failure details for hidden tests are redacted in candidate-facing views.
    message: str | None = None


class BenchmarkResult(BaseModel):
    name: str
    ok: bool
    median_ms: float | None = None
    p95_ms: float | None = None
    min_ms: float | None = None
    peak_memory_kb: float | None = None
    budget_ms: float | None = None
    within_budget: bool | None = None
    error: str | None = None


class StageResult(BaseModel):
    stage: str
    status: StageStatus
    score: float | None = Field(default=None, ge=0, le=100)
    summary: str = ""
    duration_ms: float = 0.0
    metrics: dict[str, Any] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    tests: list[TestCaseResult] = Field(default_factory=list)
    benchmarks: list[BenchmarkResult] = Field(default_factory=list)
    logs: str = ""


class Verdict(StrEnum):
    passed = "pass"
    passed_with_warnings = "pass_with_warnings"
    failed = "fail"
    incomplete = "incomplete"


class Scorecard(BaseModel):
    """Headline numbers, one per evaluation criterion (0-100 unless noted)."""

    functional_correctness: float | None = None
    edge_case_handling: float | None = None
    integration: float | None = None
    test_coverage: float | None = None
    static_quality: float | None = None
    security: Literal["pass", "fail"] | None = None
    security_score: float | None = None
    performance_median_ms: float | None = None
    performance_score: float | None = None
    llm_quality: float | None = None
    # Unset when the verdict is incomplete: an outage is not a measured zero.
    overall: float | None = None


class CandidateReport(BaseModel):
    label: str
    model: str | None = None
    verdict: Verdict
    gates_failed: list[str] = Field(default_factory=list)
    scorecard: Scorecard
    stages: list[StageResult]


class EvaluationReport(BaseModel):
    task_id: str
    task_title: str
    candidates: list[CandidateReport]
    ranking: list[str] = Field(description="Candidate labels, best first.")
    weights: dict[str, float]
    notes: list[str] = Field(default_factory=list)
