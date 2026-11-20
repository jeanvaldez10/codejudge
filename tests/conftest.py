from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from codejudge.config import get_settings
from codejudge.loader import load_candidate, load_task
from codejudge.models import Task

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "interval-merge"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # CI sets CODEJUDGE_TEST_DATABASE_URL to run the same tests on PostgreSQL.
    db = os.environ.get("CODEJUDGE_TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/cj.db"
    monkeypatch.setenv("CODEJUDGE_DATABASE_URL", db)
    monkeypatch.setenv("CODEJUDGE_SANDBOX_BACKEND", "local")
    monkeypatch.setenv("CODEJUDGE_ALLOW_LOCAL_SANDBOX", "1")
    monkeypatch.setenv("CODEJUDGE_LLM_ENABLED", "0")
    monkeypatch.delenv("CODEJUDGE_API_TOKEN", raising=False)
    get_settings.cache_clear()


@pytest.fixture
def task() -> Task:
    return load_task(EXAMPLE)


@pytest.fixture
def candidate_a():
    return load_candidate(f"Model A={EXAMPLE / 'candidates/model_a'}@a")


@pytest.fixture
def candidate_b():
    return load_candidate(f"Model B={EXAMPLE / 'candidates/model_b'}@b")


@pytest.fixture
def candidate_c():
    return load_candidate(f"Model C={EXAMPLE / 'candidates/model_c'}@c")


def docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    proc = subprocess.run(
        ["docker", "image", "inspect", "codejudge-sandbox:latest"], capture_output=True, check=False
    )
    return proc.returncode == 0


requires_docker = pytest.mark.skipif(
    not docker_ready(), reason="docker sandbox image not available"
)
