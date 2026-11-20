import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from codejudge.api import github as gh
from codejudge.api.app import app
from codejudge.config import get_settings
from codejudge.worker import run_once


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def quick_task(task):
    # Static/security stages only: keeps API tests fast.
    return task.model_copy(update={"benchmarks": [], "entrypoint": None})


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_submit_process_and_fetch(client, quick_task, candidate_a, candidate_b):
    r = client.put(f"/api/tasks/{quick_task.id}", json=quick_task.model_dump(mode="json"))
    assert r.status_code == 200
    tasks = client.get("/api/tasks").json()
    assert tasks[0]["hidden_tests"] == 3

    body = {
        "task_id": quick_task.id,
        "candidates": [candidate_a.model_dump(), candidate_b.model_dump()],
        "stages": ["visible_tests", "hidden_tests", "security"],
    }
    r = client.post("/api/submissions", json=body)
    assert r.status_code == 202
    sid = r.json()["id"]
    assert client.get(f"/api/submissions/{sid}").json()["status"] == "queued"

    assert run_once() == 1  # the worker, not the API, executes code

    detail = client.get(f"/api/submissions/{sid}").json()
    assert detail["status"] == "completed"
    assert detail["report"]["ranking"] == ["Model A", "Model B"]
    md = client.get(f"/api/submissions/{sid}/report.md").text
    assert "| Security checks | Pass | Fail |" in md

    public = client.get(f"/api/submissions/{sid}", params={"view": "public"}).json()
    hidden = [
        s
        for c in public["report"]["candidates"]
        for s in c["stages"]
        if s["stage"] == "hidden_tests"
    ]
    assert hidden and all(s["tests"] == [] for s in hidden)


def test_token_required_when_configured(client, monkeypatch, quick_task):
    monkeypatch.setenv("CODEJUDGE_API_TOKEN", "s3cret")
    get_settings.cache_clear()
    spec = quick_task.model_dump(mode="json")
    assert client.put(f"/api/tasks/{quick_task.id}", json=spec).status_code == 401
    ok = client.put(
        f"/api/tasks/{quick_task.id}", json=spec, headers={"Authorization": "Bearer s3cret"}
    )
    assert ok.status_code == 200
    # Without the token, task details exclude hidden tests.
    public = client.get(f"/api/tasks/{quick_task.id}").json()
    assert all(not t["hidden"] for t in public["tests"])
    full = client.get(
        f"/api/tasks/{quick_task.id}", headers={"Authorization": "Bearer s3cret"}
    ).json()
    assert any(t["hidden"] for t in full["tests"])


def test_rejects_unknown_task_and_bad_files(client, candidate_a):
    r = client.post(
        "/api/submissions", json={"task_id": "nope", "candidates": [candidate_a.model_dump()]}
    )
    assert r.status_code == 404
    bad = {"label": "x", "files": {"conftest.py": "import os"}}
    r = client.post("/api/submissions", json={"task_id": "nope", "candidates": [bad]})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

REPO_FILES = {
    ".codejudge.yml": "task_id: interval-merge\ncandidates:\n  - {label: PR, model: bot, path: impl}\n",
}


def fake_github(candidate_a, calls):
    files = {f"impl/{k}": v for k, v in candidate_a.files.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(201, json={})
        rel = path.split("/contents/", 1)[1]
        raw = "raw" in request.headers.get("accept", "")
        if rel in REPO_FILES:
            return httpx.Response(200, text=REPO_FILES[rel])
        if rel in files:
            if raw:
                return httpx.Response(200, text=files[rel])
            return httpx.Response(
                200, json={"name": rel.split("/")[-1], "path": rel, "type": "file"}
            )
        if rel == "impl":
            return httpx.Response(
                200,
                json=[{"name": k.split("/")[-1], "path": k, "type": "file"} for k in files],
            )
        return httpx.Response(404)

    return lambda: httpx.Client(base_url=gh.API, transport=httpx.MockTransport(handler))


def test_webhook_end_to_end(client, monkeypatch, quick_task, candidate_a):
    monkeypatch.setenv("CODEJUDGE_GITHUB_WEBHOOK_SECRET", "whsec")
    get_settings.cache_clear()
    calls: list = []
    monkeypatch.setattr(gh, "_client", fake_github(candidate_a, calls))
    client.put(f"/api/tasks/{quick_task.id}", json=quick_task.model_dump(mode="json"))

    event = {
        "action": "opened",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {
            "number": 7,
            "head": {"sha": "abc123", "repo": {"full_name": "acme/repo"}},
        },
    }
    body = json.dumps(event).encode()
    sig = "sha256=" + hmac.new(b"whsec", body, hashlib.sha256).hexdigest()

    bad = client.post(
        "/api/github/webhook",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=00"},
    )
    assert bad.status_code == 401

    r = client.post(
        "/api/github/webhook",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sig},
    )
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    run_once()
    detail = client.get(f"/api/submissions/{sid}").json()
    assert detail["status"] == "completed" and detail["source"] == "github"
    posted = [p for m, p in calls if m == "POST"]
    assert "/repos/acme/repo/statuses/abc123" in posted
    assert "/repos/acme/repo/issues/7/comments" in posted
