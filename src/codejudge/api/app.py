"""REST API.

The API validates and enqueues; it never runs candidate code. Workers
(``codejudge worker``) execute submissions inside the sandbox.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from codejudge import __version__
from codejudge.api import github as gh
from codejudge.config import get_settings
from codejudge.db import SubmissionRow, TaskRow, session_scope
from codejudge.models import EvaluationReport, SubmissionRequest, Task
from codejudge.report import redact_hidden, render_markdown

log = logging.getLogger(__name__)

app = FastAPI(
    title="CodeJudge",
    version=__version__,
    description="Evaluate AI-generated code with independent, sandboxed verification stages.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """If CODEJUDGE_API_TOKEN is set, mutating and privileged endpoints need it."""
    token = get_settings().api_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


def is_privileged(authorization: str | None) -> bool:
    token = get_settings().api_token
    return token is None or authorization == f"Bearer {token}"


Auth = Depends(require_token)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SubmissionCreated(BaseModel):
    id: str
    status: str
    task_id: str


class SubmissionSummary(BaseModel):
    id: str
    task_id: str
    status: str
    source: str
    candidates: list[str]
    ranking: list[str] | None = None
    created_at: str
    finished_at: str | None = None


class SubmissionDetail(SubmissionSummary):
    error: str | None = None
    report: EvaluationReport | None = None


def _summary(row: SubmissionRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "status": row.status,
        "source": row.source,
        "candidates": [c["label"] for c in row.request.get("candidates", [])],
        "ranking": (row.report or {}).get("ranking"),
        "created_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    s = get_settings()
    return {"status": "ok", "version": __version__, "sandbox": s.sandbox_backend}


@app.put("/api/tasks/{task_id}", dependencies=[Auth])
def upsert_task(task_id: str, task: Task) -> dict[str, Any]:
    if task.id != task_id:
        raise HTTPException(400, "task id in path and body differ")
    with session_scope() as s:
        row = s.get(TaskRow, task_id)
        spec = task.model_dump(mode="json")
        if row is None:
            s.add(TaskRow(id=task_id, title=task.title, spec=spec))
        else:
            row.title, row.spec = task.title, spec
    return {"id": task_id, "title": task.title}


@app.get("/api/tasks")
def list_tasks() -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = s.scalars(select(TaskRow).order_by(TaskRow.id)).all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "visible_tests": sum(not t["hidden"] for t in r.spec.get("tests", [])),
                "hidden_tests": sum(t["hidden"] for t in r.spec.get("tests", [])),
                "benchmarks": len(r.spec.get("benchmarks", [])),
            }
            for r in rows
        ]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    with session_scope() as s:
        row = s.get(TaskRow, task_id)
        if row is None:
            raise HTTPException(404, "task not found")
        task = Task.model_validate(row.spec)
    # Hidden tests are only returned to the operator.
    return task.model_dump(mode="json") if is_privileged(authorization) else task.public_view()


def _enqueue(
    req: SubmissionRequest,
    *,
    source: str = "api",
    github: dict[str, Any] | None = None,
) -> SubmissionCreated:
    settings = get_settings()
    if len(req.candidates) > settings.max_candidates:
        raise HTTPException(413, f"at most {settings.max_candidates} candidates per submission")
    for c in req.candidates:
        for path, src in c.files.items():
            if len(src.encode()) > settings.max_file_bytes:
                raise HTTPException(
                    413, f"{c.label}/{path} exceeds {settings.max_file_bytes} bytes"
                )
    with session_scope() as s:
        if req.task is not None:
            task = req.task
        else:
            row = s.get(TaskRow, req.task_id)
            if row is None:
                raise HTTPException(404, f"task {req.task_id!r} not found")
            task = Task.model_validate(row.spec)
        if req.stages:
            from codejudge.stages import STAGE_ORDER

            unknown = set(req.stages) - set(STAGE_ORDER)
            if unknown:
                raise HTTPException(422, f"unknown stage(s): {sorted(unknown)}")
        sub = SubmissionRow(
            task_id=task.id,
            source=source,
            task_spec=task.model_dump(mode="json"),
            request={
                "candidates": [c.model_dump(mode="json") for c in req.candidates],
                "stages": req.stages,
            },
            github=github,
        )
        s.add(sub)
        s.flush()
        created = SubmissionCreated(id=sub.id, status=sub.status, task_id=task.id)
    return created


def _maybe_inline(background: BackgroundTasks) -> None:
    """Demo mode only: let this process also act as a worker."""
    if get_settings().inline_worker:
        background.add_task(_inline_drain)


_inline_lock = threading.Lock()


def _inline_drain() -> None:
    from codejudge.worker import run_once

    with _inline_lock:
        run_once()


@app.post("/api/submissions", status_code=202, dependencies=[Auth])
def create_submission(req: SubmissionRequest, background: BackgroundTasks) -> SubmissionCreated:
    created = _enqueue(req)
    _maybe_inline(background)
    return created


@app.get("/api/submissions")
def list_submissions(
    task_id: str | None = None, limit: Annotated[int, Query(le=200)] = 50
) -> list[SubmissionSummary]:
    with session_scope() as s:
        q = select(SubmissionRow).order_by(SubmissionRow.created_at.desc()).limit(limit)
        if task_id:
            q = q.where(SubmissionRow.task_id == task_id)
        return [SubmissionSummary(**_summary(r)) for r in s.scalars(q).all()]


def _load_report(
    submission_id: str, authorization: str | None, view: str
) -> tuple[SubmissionRow, EvaluationReport | None]:
    with session_scope() as s:
        row = s.get(SubmissionRow, submission_id)
        if row is None:
            raise HTTPException(404, "submission not found")
    report = EvaluationReport.model_validate(row.report) if row.report else None
    if report is not None and (view == "public" or not is_privileged(authorization)):
        report = redact_hidden(report)
    return row, report


@app.get("/api/submissions/{submission_id}")
def get_submission(
    submission_id: str,
    view: Annotated[str, Query(pattern="^(full|public)$")] = "full",
    authorization: Annotated[str | None, Header()] = None,
) -> SubmissionDetail:
    row, report = _load_report(submission_id, authorization, view)
    return SubmissionDetail(**_summary(row), error=row.error, report=report)


@app.get("/api/submissions/{submission_id}/report.md", response_class=PlainTextResponse)
def get_report_markdown(
    submission_id: str,
    view: Annotated[str, Query(pattern="^(full|public)$")] = "full",
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    row, report = _load_report(submission_id, authorization, view)
    if report is None:
        raise HTTPException(409, f"submission is {row.status}")
    return render_markdown(report)


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


@app.post("/api/github/evaluate", status_code=202, dependencies=[Auth])
def github_evaluate(
    req: gh.GitHubEvaluateRequest, background: BackgroundTasks
) -> SubmissionCreated:
    with gh._client() as client:
        try:
            if req.candidates is None or req.task_id is None:
                cfg = gh.load_repo_config(client, req.repo, req.ref)
                task_id = req.task_id or cfg.task_id
                specs = req.candidates or cfg.candidates
            else:
                task_id, specs = req.task_id, req.candidates
            candidates = gh.candidates_from_repo(client, req.repo, req.ref, specs)
        except Exception as exc:
            raise HTTPException(502, f"could not read repository: {exc}") from exc
    created = _enqueue(
        SubmissionRequest(task_id=task_id, candidates=candidates),
        source="github",
        github={"repo": req.repo, "sha": req.ref, "pr_number": None},
    )
    _maybe_inline(background)
    return created


@app.post("/api/github/webhook", status_code=202)
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_github_event: Annotated[str | None, Header()] = None,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    secret = get_settings().github_webhook_secret
    body = await request.body()
    if not secret:
        raise HTTPException(503, "webhook secret not configured")
    if not gh.verify_signature(secret, body, x_hub_signature_256):
        raise HTTPException(401, "bad signature")
    if x_github_event == "ping":
        return {"ok": True}
    if x_github_event != "pull_request":
        return {"ignored": x_github_event}
    event = json.loads(body)
    if event.get("action") not in {"opened", "synchronize", "reopened"}:
        return {"ignored": event.get("action")}
    pr = event["pull_request"]
    repo = pr["head"]["repo"]["full_name"]
    sha = pr["head"]["sha"]
    with gh._client() as client:
        try:
            cfg = gh.load_repo_config(client, repo, sha)
            candidates = gh.candidates_from_repo(client, repo, sha, cfg.candidates)
        except Exception as exc:
            return {"ignored": f"no usable {gh.CONFIG_FILE}: {exc}"}
    created = _enqueue(
        SubmissionRequest(task_id=cfg.task_id, candidates=candidates, stages=cfg.stages),
        source="github",
        github={"repo": event["repository"]["full_name"], "sha": sha, "pr_number": pr["number"]},
    )
    _maybe_inline(background)
    return created.model_dump()


# Serve the built dashboard, if present (frontend/dist).
_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
