import pytest
from pydantic import ValidationError

from codejudge.models import Candidate, SubmissionRequest, Task, TestSuite


@pytest.mark.parametrize(
    "path",
    [
        "../evil.py",
        "/etc/passwd.py",
        "conftest.py",
        "pkg/conftest.py",
        "sitecustomize.py",
        "_cj_run_tests.py",
        "notes.txt",
        "a/../../b.py",
    ],
)
def test_rejects_dangerous_paths(path):
    with pytest.raises(ValidationError):
        Candidate(label="x", files={path: "print(1)"})


def test_splits_solution_and_tests():
    c = Candidate(label="x", files={"solution.py": "", "test_solution.py": "", "pkg/util.py": ""})
    assert sorted(c.solution_files()) == ["pkg/util.py", "solution.py"]
    assert list(c.test_files()) == ["test_solution.py"]


def test_public_view_hides_hidden_tests():
    t = Task(
        id="t",
        title="t",
        description="d",
        tests=[TestSuite(name="test_a", code=""), TestSuite(name="test_b", code="", hidden=True)],
    )
    assert [s["name"] for s in t.public_view()["tests"]] == ["test_a"]


def test_benchmarks_need_entrypoint():
    with pytest.raises(ValidationError):
        Task(id="t", title="t", description="d", benchmarks=[{"name": "b", "setup": "args=()"}])


def test_submission_requires_task_xor_id():
    c = Candidate(label="x", files={"solution.py": ""})
    with pytest.raises(ValidationError):
        SubmissionRequest(candidates=[c])
    with pytest.raises(ValidationError):
        SubmissionRequest(task_id="a", candidates=[c, c])  # duplicate labels
