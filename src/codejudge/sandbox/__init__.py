"""Isolated execution backends for untrusted candidate code."""

from codejudge.sandbox.base import ExecResult, Sandbox, SandboxUnavailable, get_sandbox

__all__ = ["ExecResult", "Sandbox", "SandboxUnavailable", "get_sandbox"]
