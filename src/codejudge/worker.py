"""Evaluation worker: claims queued submissions and runs them in the sandbox.

The API process never executes candidate code; it only enqueues. Run one or
more workers on hosts that have Docker access::

    codejudge worker
"""

from __future__ import annotations

import logging
import os
import socket
import time
import traceback

from codejudge.config import get_settings
from codejudge.db import SubmissionRow, claim_next, requeue_stale, session_scope, utcnow
from codejudge.models import Candidate, Task
from codejudge.pipeline import evaluate
from codejudge.sandbox import Sandbox, get_sandbox
from codejudge.stages.llm_review import ReviewFn

log = logging.getLogger(__name__)


def process(row_id: str, sandbox: Sandbox, review_fn: ReviewFn | None = None) -> None:
    with session_scope() as s:
        row = s.get(SubmissionRow, row_id)
        assert row is not None
        task = Task.model_validate(row.task_spec)
        candidates = [Candidate.model_validate(c) for c in row.request["candidates"]]
        stages = row.request.get("stages")
    try:
        report = evaluate(task, candidates, sandbox, selected_stages=stages, review_fn=review_fn)
        status, payload, error = "completed", report.model_dump(mode="json"), None
    except Exception as exc:
        log.exception("submission %s failed", row_id)
        status, payload = "failed", None
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"
    with session_scope() as s:
        row = s.get(SubmissionRow, row_id)
        assert row is not None
        row.status, row.report, row.error, row.finished_at = status, payload, error, utcnow()
        github = row.github
    if github and status == "completed" and payload is not None:
        from codejudge.api.github import post_results

        try:
            post_results(github, payload, row_id)
        except Exception:
            log.exception("failed to post GitHub results for %s", row_id)


def run_once(sandbox: Sandbox | None = None, review_fn: ReviewFn | None = None) -> int:
    """Drain the queue; returns the number of submissions processed."""
    sandbox = sandbox or get_sandbox()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    n = 0
    with session_scope() as s:
        if requeued := requeue_stale(s):
            log.warning("requeued %d stale submission(s)", requeued)
    while True:
        with session_scope() as s:
            row = claim_next(s, worker_id)
            row_id = row.id if row else None
        if row_id is None:
            return n
        log.info("processing submission %s", row_id)
        process(row_id, sandbox, review_fn)
        n += 1


def run_forever(once: bool = False) -> None:
    settings = get_settings()
    sandbox = get_sandbox(settings)
    sandbox.check()
    log.info("worker started (sandbox=%s)", sandbox.name)
    while True:
        run_once(sandbox)
        if once:
            return
        time.sleep(settings.worker_poll_seconds)
