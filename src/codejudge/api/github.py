"""GitHub integration.

Two entry points:

* ``POST /api/github/evaluate`` - evaluate files from a repo at a ref.
* ``POST /api/github/webhook`` - on ``pull_request`` events, read
  ``.codejudge.yml`` from the PR head, evaluate the listed candidates and
  report back with a commit status and a PR comment.

``.codejudge.yml``::

    task_id: interval-merge
    candidates:
      - label: Model A
        model: assistant-a
        path: solutions/model_a        # a .py file or a directory
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx
import yaml
from pydantic import BaseModel, Field

from codejudge.config import get_settings
from codejudge.models import Candidate, EvaluationReport

API = "https://api.github.com"
CONFIG_FILE = ".codejudge.yml"
MAX_FILES = 50


class RepoCandidate(BaseModel):
    label: str
    model: str | None = None
    path: str


class RepoConfig(BaseModel):
    task_id: str
    candidates: list[RepoCandidate] = Field(min_length=1)
    stages: list[str] | None = None


class GitHubEvaluateRequest(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    ref: str = "HEAD"
    task_id: str | None = None
    candidates: list[RepoCandidate] | None = Field(
        default=None, description="Defaults to the repo's .codejudge.yml"
    )


def _client() -> httpx.Client:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = get_settings().github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=API, headers=headers, timeout=20.0)


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _get_raw(client: httpx.Client, repo: str, path: str, ref: str) -> str:
    r = client.get(
        f"/repos/{repo}/contents/{path}",
        params={"ref": ref},
        headers={"Accept": "application/vnd.github.raw+json"},
    )
    r.raise_for_status()
    return r.text


def fetch_python_files(client: httpx.Client, repo: str, path: str, ref: str) -> dict[str, str]:
    """Return {relative_path: source} for a .py file or every .py under a dir."""
    r = client.get(f"/repos/{repo}/contents/{path.strip('/')}", params={"ref": ref})
    r.raise_for_status()
    listing = r.json()
    if isinstance(listing, dict):  # a single file
        name = listing["name"]
        return {name: _get_raw(client, repo, listing["path"], ref)}
    files: dict[str, str] = {}
    stack: list[tuple[str, list[dict[str, Any]]]] = [("", listing)]
    while stack:
        prefix, entries = stack.pop()
        for e in entries:
            rel = f"{prefix}{e['name']}"
            if e["type"] == "dir":
                sub = client.get(f"/repos/{repo}/contents/{e['path']}", params={"ref": ref})
                sub.raise_for_status()
                stack.append((rel + "/", sub.json()))
            elif e["type"] == "file" and e["name"].endswith(".py"):
                files[rel] = _get_raw(client, repo, e["path"], ref)
                if len(files) > MAX_FILES:
                    raise ValueError(f"more than {MAX_FILES} Python files under {path}")
    return files


def load_repo_config(client: httpx.Client, repo: str, ref: str) -> RepoConfig:
    return RepoConfig.model_validate(yaml.safe_load(_get_raw(client, repo, CONFIG_FILE, ref)))


def candidates_from_repo(
    client: httpx.Client, repo: str, ref: str, specs: list[RepoCandidate]
) -> list[Candidate]:
    return [
        Candidate(label=c.label, model=c.model, files=fetch_python_files(client, repo, c.path, ref))
        for c in specs
    ]


def post_results(github: dict[str, Any], report_json: dict[str, Any], submission_id: str) -> None:
    """Commit status on the head SHA + a PR comment (hidden tests redacted)."""
    from codejudge.report import redact_hidden, render_markdown

    report = redact_hidden(EvaluationReport.model_validate(report_json))
    best = next(c for c in report.candidates if c.label == report.ranking[0])
    state = "success" if best.verdict.value != "fail" else "failure"
    with _client() as client:
        client.post(
            f"/repos/{github['repo']}/statuses/{github['sha']}",
            json={
                "state": state,
                "context": "codejudge",
                "description": f"best: {best.label} ({best.scorecard.overall:.1f}, {best.verdict.value})"[
                    :140
                ],
            },
        ).raise_for_status()
        if github.get("pr_number"):
            body = (
                render_markdown(report) + f"\n\n<sub>CodeJudge submission `{submission_id}`</sub>"
            )
            client.post(
                f"/repos/{github['repo']}/issues/{github['pr_number']}/comments",
                json={"body": body[:65000]},
            ).raise_for_status()
