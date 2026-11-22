import json
from types import SimpleNamespace

import pytest

from codejudge.generation import (
    AnthropicGenerator,
    DirectoryGenerator,
    GeneratedFile,
    GeneratedSolution,
    GenerationResult,
    build_prompt,
    parse_generator,
    to_candidate,
    write_sample,
)


class FakeMessages:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response, exc, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.response


def fake_client(**kw):
    messages = FakeMessages(**kw)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def response(files, stop_reason="end_turn"):
    parsed = (
        None
        if files is None
        else GeneratedSolution(
            files=[GeneratedFile(path=p, content=c) for p, c in files.items()], notes=""
        )
    )
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=800),
    )


def test_prompt_contains_public_material_only(task):
    prompt = build_prompt(task)
    assert task.description.strip()[:40] in prompt
    assert "test_basic" in prompt
    for suite in task.tests:
        if suite.hidden:
            assert suite.name not in prompt
            assert suite.code.strip() not in prompt
    assert "test_solution.py" in prompt


def test_anthropic_generator_success(task):
    client, messages = fake_client(
        response=response({"solution.py": "x = 1\n", "./test_solution.py": ""})
    )
    gen = AnthropicGenerator("claude-opus-5-5", client=client)
    result = gen.generate(task, 1)
    assert result.error is None
    assert set(result.files) == {"solution.py", "test_solution.py"}
    assert result.usage["output_tokens"] == 800
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "high"}
    assert call["fallbacks"] == "default"
    assert all("test_hidden" not in m["content"] for m in call["messages"])


@pytest.mark.parametrize(
    "kw, expected",
    [
        ({"response": response(None, "refusal")}, "declined"),
        ({"response": response(None, "max_tokens")}, "max_tokens"),
        ({"exc": RuntimeError("boom")}, "boom"),
    ],
)
def test_anthropic_generator_failures(task, kw, expected):
    client, _ = fake_client(**kw)
    result = AnthropicGenerator("claude-opus-5-5", client=client).generate(task, 1)
    assert result.files is None and expected in result.error


def test_generator_name_includes_non_default_effort():
    assert (
        AnthropicGenerator("claude-opus-5-5", "low", client=object()).name == "claude-opus-5-5-low"
    )


def test_directory_generator_layouts(tmp_path, task):
    single = tmp_path / "single" / task.id
    single.mkdir(parents=True)
    (single / "solution.py").write_text("a = 1\n")
    multi = tmp_path / "multi" / task.id
    for k in (1, 2):
        (multi / str(k)).mkdir(parents=True)
        (multi / str(k) / "solution.py").write_text(f"a = {k}\n")

    assert DirectoryGenerator("s", tmp_path / "single").generate(task, 1).files == {
        "solution.py": "a = 1\n"
    }
    assert "no sample 2" in DirectoryGenerator("s", tmp_path / "single").generate(task, 2).error
    assert DirectoryGenerator("m", tmp_path / "multi").generate(task, 2).files == {
        "solution.py": "a = 2\n"
    }


def test_parse_generator():
    assert parse_generator("anthropic:claude-opus-5-5:low").name == "claude-opus-5-5-low"
    assert parse_generator("dir:copilot=/tmp/x").name == "copilot"
    with pytest.raises(ValueError):
        parse_generator("openai")


def test_rejects_harness_files_from_generator():
    out = to_candidate("g#1", "g", GenerationResult({"conftest.py": "", "solution.py": ""}))
    assert isinstance(out, str) and "rejected" in out


def test_write_sample_refuses_path_escape(tmp_path):
    dest = tmp_path / "s"
    write_sample(dest, GenerationResult({"solution.py": "ok", "../evil.py": "bad"}))
    assert not (tmp_path / "evil.py").exists()
    assert not (dest / "solution.py").exists()  # nothing written when any path escapes
    assert "escapes" in json.loads((dest / "meta.json").read_text())["error"]
