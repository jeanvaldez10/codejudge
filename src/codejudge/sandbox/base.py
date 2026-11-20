"""Sandbox interface.

A sandbox runs one command against a *workspace* directory (mounted
read-only) and an *output* directory (writable, used by the harness to hand
structured results back). Commands may use these placeholders, which each
backend substitutes with its own paths:

``{python}``     the interpreter inside the sandbox
``{workspace}``  the workspace directory
``{out}``        the output directory
``{rules}``      the bundled Semgrep rules file
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path

from codejudge.config import Settings, get_settings
from codejudge.models import ResourceLimits

MAX_STREAM_BYTES = 64 * 1024
MAX_OUTPUT_FILE_BYTES = 8 * 1024 * 1024


class SandboxUnavailable(RuntimeError):
    """The configured backend cannot run (e.g. Docker daemon unreachable)."""


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    oom_killed: bool = False
    outputs: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.oom_killed

    def describe_failure(self) -> str:
        if self.timed_out:
            return "timed out"
        if self.oom_killed:
            return "killed: out of memory"
        return f"exit code {self.exit_code}"


def truncate(data: bytes, limit: int = MAX_STREAM_BYTES) -> str:
    text = data[:limit].decode("utf-8", errors="replace")
    if len(data) > limit:
        text += f"\n... [truncated {len(data) - limit} bytes]"
    return text


def collect_outputs(out_dir: Path) -> dict[str, str]:
    """Read result files written by the harness. Size-capped and non-recursive
    so a hostile candidate cannot exhaust worker memory via the output dir."""
    outputs: dict[str, str] = {}
    total = 0
    for p in sorted(out_dir.iterdir()):
        if not p.is_file() or p.is_symlink():
            continue
        size = p.stat().st_size
        if total + size > MAX_OUTPUT_FILE_BYTES:
            break
        total += size
        outputs[p.name] = p.read_text(encoding="utf-8", errors="replace")
    return outputs


class Sandbox(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def run(
        self,
        workspace: Path,
        command: list[str],
        limits: ResourceLimits,
        *,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run ``command`` with ``workspace`` as the working directory."""

    def check(self) -> None:  # noqa: B027 - optional hook
        """Raise :class:`SandboxUnavailable` if the backend is unusable."""


def get_sandbox(settings: Settings | None = None) -> Sandbox:
    settings = settings or get_settings()
    if settings.sandbox_backend == "docker":
        from codejudge.sandbox.docker import DockerSandbox

        return DockerSandbox(image=settings.sandbox_image)
    if settings.sandbox_backend == "local":
        from codejudge.sandbox.local import LocalSandbox

        if not settings.allow_local_sandbox:
            raise SandboxUnavailable(
                "the local sandbox runs untrusted code on this host with only rlimits; "
                "set CODEJUDGE_ALLOW_LOCAL_SANDBOX=1 to acknowledge this (dev/CI only)"
            )
        return LocalSandbox()
    raise SandboxUnavailable(f"unknown sandbox backend {settings.sandbox_backend!r}")
