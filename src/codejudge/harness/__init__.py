"""Scripts copied into the sandbox workspace. They run *inside* the sandbox,
must depend only on the stdlib plus pytest/coverage, and must never be
imported by the API or worker processes."""

from importlib import resources

HARNESS_FILES = ("_cj_run_tests.py", "_cj_bench.py")


def read(name: str) -> str:
    return (resources.files(__package__) / name).read_text(encoding="utf-8")
