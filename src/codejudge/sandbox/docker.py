"""Docker backend: the production isolation boundary.

Each command runs in a fresh, throwaway container with:

* no network (``--network none``)
* read-only root filesystem and read-only workspace mount
* a small ``noexec`` tmpfs for scratch space, plus one writable output dir
* all Linux capabilities dropped, ``no-new-privileges``, non-root user
* cgroup limits on memory (no swap), CPU and number of processes
* a wall-clock timeout enforced from outside (``docker kill``)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from codejudge.models import ResourceLimits
from codejudge.sandbox.base import (
    ExecResult,
    Sandbox,
    SandboxUnavailable,
    collect_outputs,
    truncate,
)

SANDBOX_UID = "10001"


class DockerSandbox(Sandbox):
    name = "docker"

    def __init__(self, image: str, docker_bin: str = "docker") -> None:
        self.image = image
        self.docker_bin = docker_bin

    def check(self) -> None:
        if shutil.which(self.docker_bin) is None:
            raise SandboxUnavailable("docker CLI not found")
        proc = subprocess.run(
            [self.docker_bin, "image", "inspect", self.image],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            raise SandboxUnavailable(
                f"sandbox image {self.image!r} unavailable: {truncate(proc.stderr, 500)}"
            )

    def build_command(
        self,
        name: str,
        workspace: Path,
        out_dir: Path,
        command: list[str],
        limits: ResourceLimits,
        env: dict[str, str],
    ) -> list[str]:
        subst = {
            "{python}": "python",
            "{workspace}": "/workspace",
            "{out}": "/out",
            "{rules}": "/opt/codejudge/semgrep-rules.yml",
        }
        argv = [_substitute(a, subst) for a in command]
        cmd = [
            self.docker_bin, "run", "--rm",
            "--name", name,
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", f"{SANDBOX_UID}:{SANDBOX_UID}",
            "--memory", f"{limits.memory_mb}m",
            "--memory-swap", f"{limits.memory_mb}m",
            "--cpus", str(limits.cpus),
            "--pids-limit", str(limits.pids),
            "--ulimit", "nofile=256:256",
            "--ulimit", f"fsize={64 * 1024 * 1024}",
            "-v", f"{workspace}:/workspace:ro",
            "-v", f"{out_dir}:/out:rw",
            "-w", "/workspace",
            "-e", "CJ_OUT=/out",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "PYTHONHASHSEED=0",
        ]  # fmt: skip
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append(self.image)
        cmd += argv
        return cmd

    def run(
        self,
        workspace: Path,
        command: list[str],
        limits: ResourceLimits,
        *,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        name = f"codejudge-{uuid.uuid4().hex[:16]}"
        # The output dir must live where the Docker daemon can bind-mount it.
        # When the worker itself runs in a container, CODEJUDGE_WORK_DIR must be
        # a path shared with the host at the same location.
        base = os.environ.get("CODEJUDGE_WORK_DIR")
        out_dir = Path(tempfile.mkdtemp(prefix="cj-out-", dir=base))
        out_dir.chmod(0o777)  # writable by the unprivileged sandbox user
        cmd = self.build_command(name, workspace, out_dir, command, limits, env or {})
        start = time.perf_counter()
        timed_out = False
        try:
            # Give the container a little slack for startup on top of the limit.
            proc = subprocess.run(
                cmd, capture_output=True, timeout=limits.timeout_seconds + 10, check=False
            )
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            subprocess.run(
                [self.docker_bin, "kill", name], capture_output=True, timeout=30, check=False
            )
            stdout, stderr, code = exc.stdout or b"", exc.stderr or b"", -9
        duration = (time.perf_counter() - start) * 1000
        if code == 125:
            # Docker itself failed (bad image, daemon error): not the candidate's fault.
            shutil.rmtree(out_dir, ignore_errors=True)
            raise SandboxUnavailable(f"docker run failed: {truncate(stderr, 2000)}")
        try:
            outputs = collect_outputs(out_dir)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
        return ExecResult(
            exit_code=code,
            stdout=truncate(stdout),
            stderr=truncate(stderr),
            duration_ms=duration,
            timed_out=timed_out or duration > limits.timeout_seconds * 1000 + 10_000,
            # 137 = SIGKILL, which inside a memory-limited container is the OOM killer.
            oom_killed=code == 137 and not timed_out,
            outputs=outputs,
        )


def _substitute(arg: str, subst: dict[str, str]) -> str:
    for k, v in subst.items():
        arg = arg.replace(k, v)
    return arg
