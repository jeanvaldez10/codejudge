"""Local backend: runs commands as a child process with POSIX rlimits.

This is NOT a security boundary. It exists so the engine can be developed and
tested on machines without Docker. It is refused unless
``CODEJUDGE_ALLOW_LOCAL_SANDBOX=1`` is set.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from importlib import resources
from pathlib import Path

from codejudge.models import ResourceLimits
from codejudge.sandbox.base import ExecResult, Sandbox, collect_outputs, truncate


def _rules_path() -> str:
    packaged = resources.files("codejudge.sandbox") / "semgrep-rules.yml"
    if packaged.is_file():
        return str(packaged)
    repo = Path(__file__).resolve().parents[3] / "sandbox" / "semgrep-rules.yml"
    return str(repo)


class LocalSandbox(Sandbox):
    name = "local"

    def run(
        self,
        workspace: Path,
        command: list[str],
        limits: ResourceLimits,
        *,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        out_dir = Path(tempfile.mkdtemp(prefix="cj-out-"))
        scratch = Path(tempfile.mkdtemp(prefix="cj-tmp-"))
        subst = {
            "{python}": sys.executable,
            "{workspace}": str(workspace),
            "{out}": str(out_dir),
            "{rules}": _rules_path(),
        }
        argv = []
        for a in command:
            for k, v in subst.items():
                a = a.replace(k, v)
            argv.append(a)
        child_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(scratch),
            "TMPDIR": str(scratch),
            "CJ_OUT": str(out_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "SEMGREP_SEND_METRICS": "off",
            "SEMGREP_ENABLE_VERSION_CHECK": "0",
            "MYPY_CACHE_DIR": str(scratch / ".mypy_cache"),
            **(env or {}),
        }

        def limit() -> None:  # runs in the child before exec
            import resource

            os.setsid()
            mem = limits.memory_mb * 1024 * 1024
            # Address-space limits break tools like semgrep (OCaml runtime
            # reserves large virtual regions), so only apply them to Python.
            if Path(argv[0]).name.startswith("python") or argv[0] == sys.executable:
                resource.setrlimit(resource.RLIMIT_AS, (mem * 4, mem * 4))
            cpu = int(limits.timeout_seconds) + 1
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))

        start = time.perf_counter()
        timed_out = False
        proc = subprocess.Popen(
            argv,
            cwd=workspace,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            preexec_fn=limit,
        )
        try:
            stdout, stderr = proc.communicate(timeout=limits.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
        duration = (time.perf_counter() - start) * 1000
        try:
            outputs = collect_outputs(out_dir)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
            shutil.rmtree(scratch, ignore_errors=True)
        return ExecResult(
            exit_code=proc.returncode if not timed_out else -9,
            stdout=truncate(stdout),
            stderr=truncate(stderr),
            duration_ms=duration,
            timed_out=timed_out,
            oom_killed=proc.returncode == -signal.SIGKILL and not timed_out,
            outputs=outputs,
        )
