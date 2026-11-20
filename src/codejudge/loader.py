"""Load tasks and candidates from disk (YAML/JSON task specs, source dirs)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from codejudge.models import Candidate, Task


def load_task(path: str | Path) -> Task:
    """Load a task spec. Test suites may give ``file:`` (relative to the spec)
    instead of inline ``code:``."""
    path = Path(path)
    if path.is_dir():
        path = path / "task.yaml"
    text = path.read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    for suite in data.get("tests", []):
        if "file" in suite:
            suite["code"] = (path.parent / suite.pop("file")).read_text(encoding="utf-8")
    for bench in data.get("benchmarks", []):
        if "setup_file" in bench:
            bench["setup"] = (path.parent / bench.pop("setup_file")).read_text(encoding="utf-8")
    return Task.model_validate(data)


def load_candidate(spec: str) -> Candidate:
    """``LABEL=PATH[@MODEL]`` where PATH is a .py file or a directory of them."""
    label, _, rest = spec.partition("=")
    if not rest:
        raise ValueError(f"candidate spec must be LABEL=PATH[@MODEL], got {spec!r}")
    location, _, model = rest.partition("@")
    root = Path(location)
    files: dict[str, str] = {}
    if root.is_file():
        files[root.name] = root.read_text(encoding="utf-8")
    else:
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            files[p.relative_to(root).as_posix()] = p.read_text(encoding="utf-8")
    return Candidate(label=label, model=model or None, files=files)
