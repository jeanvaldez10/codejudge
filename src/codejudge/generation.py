"""Candidate generators: turn a task prompt into candidate source files.

A generator is anything that can produce code for a task. Two kinds are
built in:

``anthropic:<model>[:<effort>]``
    Calls the Claude API (needs ``ANTHROPIC_API_KEY``). Each sample is an
    independent request, so repeated samples measure run-to-run variance.

``reference``
    The task author's reference solution: an upper bound, and a check that
    the tasks themselves are sound.

``dir:<name>=<path>``
    Reads solutions collected elsewhere (another assistant's IDE plugin, a
    chat UI, a teammate). Layout: ``<path>/<task_id>/<sample>/*.py``, or
    ``<path>/<task_id>/*.py`` for a single sample.

Generators only ever see :meth:`Task.public_view`. Hidden tests never leave
the evaluator.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

from codejudge.loader import load_candidate
from codejudge.models import Candidate, Task

_SLUG = re.compile(r"[^A-Za-z0-9._-]+")

SYSTEM_PROMPT = """You are an expert Python engineer completing a programming \
task for an automated evaluation. Your code will be run against hidden tests \
covering correctness and edge cases, then checked by linters, a type checker, \
security scanners and benchmarks.

Write production-quality, idiomatic, type-annotated Python 3.12 that uses \
only the standard library. Handle every edge case the specification mentions \
and the ones it implies."""


class GeneratedFile(BaseModel):
    path: str
    content: str


class GeneratedSolution(BaseModel):
    files: list[GeneratedFile]
    notes: str


@dataclass
class GenerationResult:
    files: dict[str, str] | None
    error: str | None = None
    latency_s: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)


class Generator(Protocol):
    name: str

    def generate(self, task: Task, sample: int) -> GenerationResult: ...


def slug(text: str) -> str:
    return _SLUG.sub("-", text).strip("-")[:60] or "generator"


def build_prompt(task: Task, *, with_tests: bool = True) -> str:
    """The prompt a generator receives. Built from the public view only."""
    public = task.public_view()
    parts = [
        f"# Task: {public['title']}\n",
        public["description"].strip(),
        "",
        f"Put the solution in `{public['module']}.py`.",
    ]
    if with_tests:
        parts.append(
            f"Also write thorough pytest tests for your solution in "
            f"`test_{public['module']}.py`. They will be run, and their coverage "
            f"of your solution will be measured."
        )
    if public["tests"]:
        parts.append("\nExample tests your solution must pass:\n")
        for suite in public["tests"]:
            parts.append(f"```python\n# {suite['name']}.py\n{suite['code'].strip()}\n```")
    parts.append(
        "\nReturn every file you want to submit. Do not include conftest.py or any "
        "configuration files."
    )
    return "\n".join(parts)


def _effort(value: str) -> Literal["low", "medium", "high", "xhigh", "max"]:
    for e in ("low", "medium", "high", "xhigh", "max"):
        if value == e:
            return e
    raise ValueError(f"unknown effort level {value!r}")


class AnthropicGenerator:
    """Generates candidates with the Claude API."""

    def __init__(
        self, model: str, effort: str = "high", *, client: Any = None, with_tests: bool = True
    ) -> None:
        self.model = model
        self.effort = _effort(effort)
        self.name = slug(model if effort == "high" else f"{model}-{effort}")
        self.with_tests = with_tests
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def generate(self, task: Task, sample: int) -> GenerationResult:
        start = time.perf_counter()
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": build_prompt(task, with_tests=self.with_tests)}
                ],
                output_format=GeneratedSolution,
                output_config={"effort": self.effort},
                thinking={"type": "adaptive"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except Exception as exc:
            return GenerationResult(
                files=None,
                error=f"{type(exc).__name__}: {exc}"[:2000],
                latency_s=time.perf_counter() - start,
            )
        latency = time.perf_counter() - start
        usage = {
            "input_tokens": getattr(response.usage, "input_tokens", None),
            "output_tokens": getattr(response.usage, "output_tokens", None),
            # Recorded because server-side fallback may route a declined
            # request to another model; the leaderboard should know.
            "served_by": getattr(response, "model", None),
            "stop_reason": response.stop_reason,
        }
        if response.stop_reason == "refusal":
            return GenerationResult(None, "model declined the request", latency, usage)
        parsed: GeneratedSolution | None = response.parsed_output
        if parsed is None:
            return GenerationResult(
                None, f"no structured output (stop_reason={response.stop_reason})", latency, usage
            )
        files = {f.path.strip().removeprefix("./"): f.content for f in parsed.files}
        return GenerationResult(files, None, latency, usage)


class DirectoryGenerator:
    """Reads pre-collected candidates from disk."""

    def __init__(self, name: str, root: str | Path) -> None:
        self.name = slug(name)
        self.root = Path(root)

    def samples_for(self, task_id: str) -> list[Path]:
        task_dir = self.root / task_id
        if not task_dir.is_dir():
            return []
        subdirs = sorted(
            (p for p in task_dir.iterdir() if p.is_dir() and p.name.isdigit()),
            key=lambda p: int(p.name),
        )
        return subdirs or [task_dir]

    def generate(self, task: Task, sample: int) -> GenerationResult:
        samples = self.samples_for(task.id)
        if sample > len(samples):
            return GenerationResult(None, f"no sample {sample} for {task.id} in {self.root}")
        cand = load_candidate(f"x={samples[sample - 1]}")
        return GenerationResult(cand.files)


class ReferenceGenerator:
    """Submits each task's reference solution: a ceiling and sanity baseline
    for the leaderboard. Anything below 100% here is a bug in the task."""

    name = "reference"

    def __init__(self, task_dirs: dict[str, Path]) -> None:
        self.task_dirs = task_dirs

    def generate(self, task: Task, sample: int) -> GenerationResult:
        ref = self.task_dirs.get(task.id, Path("/nonexistent")) / "reference"
        if not ref.is_dir():
            return GenerationResult(None, f"task {task.id} has no reference solution")
        return GenerationResult(load_candidate(f"x={ref}").files)


def parse_generator(spec: str, task_dirs: dict[str, Path] | None = None) -> Generator:
    if spec == "reference":
        return ReferenceGenerator(task_dirs or {})
    kind, _, rest = spec.partition(":")
    if kind == "anthropic" and rest:
        model, _, effort = rest.partition(":")
        return AnthropicGenerator(model, effort or "high")
    if kind == "dir" and "=" in rest:
        name, _, path = rest.partition("=")
        return DirectoryGenerator(name, path)
    raise ValueError(
        f"bad generator spec {spec!r}; expected anthropic:<model>[:<effort>], "
        "dir:<name>=<path> or reference"
    )


def to_candidate(label: str, generator: str, result: GenerationResult) -> Candidate | str:
    """Validate generated files. Returns a Candidate, or an error message."""
    if result.files is None:
        return result.error or "generation failed"
    try:
        return Candidate(label=label, model=generator, files=result.files)
    except ValidationError as exc:
        errors = "; ".join(e["msg"] for e in exc.errors())
        return f"generated files rejected: {errors}"


def write_sample(dest: Path, result: GenerationResult) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    meta = {
        "error": result.error,
        "latency_s": round(result.latency_s, 3),
        "usage": result.usage,
        "files": sorted(result.files or {}),
    }
    files = result.files or {}
    root = dest.resolve()
    escaping = [rel for rel in files if root not in (root / rel).resolve().parents]
    if escaping:
        # Check every path before writing anything, so nothing lands outside.
        meta["error"] = f"generated path escapes sample dir: {escaping[0]!r}"
        meta["files"] = []
        files = {}
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
