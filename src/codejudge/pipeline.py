"""Orchestrates stages for every candidate and assembles the report."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from codejudge.models import (
    Candidate,
    CandidateReport,
    EvaluationReport,
    Scorecard,
    StageResult,
    Task,
    Verdict,
)
from codejudge.sandbox import Sandbox
from codejudge.scoring import WEIGHTS, apply_relative_performance, build_scorecard, finalize, rank
from codejudge.stages import Stage, StageContext, default_stages, materialize_workspace
from codejudge.stages.llm_review import ReviewFn

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, StageResult], None]


def evaluate_candidate(
    task: Task,
    candidate: Candidate,
    sandbox: Sandbox,
    stages: list[Stage],
    progress: ProgressFn | None = None,
) -> CandidateReport:
    results: dict[str, StageResult] = {}
    with materialize_workspace(task, candidate) as ws:
        ctx = StageContext(
            task=task, candidate=candidate, sandbox=sandbox, workspace=ws, results=results
        )
        for stage in stages:
            result = stage.execute(ctx)
            results[result.stage] = result
            log.info("%s / %s: %s %s", candidate.label, result.stage, result.status, result.summary)
            if progress:
                progress(candidate.label, result)
    return CandidateReport(
        label=candidate.label,
        model=candidate.model,
        verdict=Verdict.failed,  # set by finalize()
        scorecard=build_scorecard(results),
        stages=list(results.values()),
    )


def evaluate(
    task: Task,
    candidates: list[Candidate],
    sandbox: Sandbox,
    *,
    selected_stages: list[str] | None = None,
    review_fn: ReviewFn | None = None,
    parallelism: int = 2,
    progress: ProgressFn | None = None,
) -> EvaluationReport:
    sandbox.check()

    def one(c: Candidate) -> CandidateReport:
        # Fresh stage objects per candidate: stages are cheap and this keeps
        # them free of shared mutable state across threads.
        stages = default_stages(selected_stages, review_fn)
        try:
            return evaluate_candidate(task, c, sandbox, stages, progress)
        except Exception as exc:  # workspace setup failure etc.
            log.exception("candidate %s crashed", c.label)
            return CandidateReport(
                label=c.label,
                model=c.model,
                verdict=Verdict.failed,
                gates_failed=["evaluation_error"],
                scorecard=Scorecard(),
                stages=[],
            ).model_copy(update={"gates_failed": [f"evaluation_error: {exc}"]})

    with ThreadPoolExecutor(max_workers=max(1, parallelism)) as pool:
        reports = list(pool.map(one, candidates))

    apply_relative_performance(reports)
    for r in reports:
        if not any(g.startswith("evaluation_error") for g in r.gates_failed):
            finalize(r)

    notes = [
        "LLM review is advisory and capped at "
        f"{WEIGHTS['llm_quality']:.0%} of the overall score; it cannot override failed gates.",
        "Performance without a time budget is scored relative to the fastest "
        "candidate in this evaluation and is not comparable across submissions.",
    ]
    if any(
        s.stage == "llm_review" and s.status.value == "skipped" for r in reports for s in r.stages
    ):
        notes.append("LLM review was skipped; its weight was redistributed.")
    return EvaluationReport(
        task_id=task.id,
        task_title=task.title,
        candidates=reports,
        ranking=rank(reports),
        weights=dict(WEIGHTS),
        notes=notes,
    )
