"""Independent verification stages."""

from __future__ import annotations

from codejudge.stages.base import Stage, StageContext, materialize_workspace
from codejudge.stages.build import BuildStage
from codejudge.stages.integrity import IntegrityStage
from codejudge.stages.llm_review import LLMReviewStage, ReviewFn
from codejudge.stages.performance import PerformanceStage
from codejudge.stages.security import SecurityStage
from codejudge.stages.static import StaticAnalysisStage
from codejudge.stages.tests import CandidateTestsStage, TaskTestsStage

STAGE_ORDER = (
    "integrity",
    "build",
    "visible_tests",
    "hidden_tests",
    "candidate_tests",
    "static_analysis",
    "security",
    "performance",
    "llm_review",  # last: it consumes every deterministic result as evidence
)


def default_stages(
    selected: list[str] | None = None, review_fn: ReviewFn | None = None
) -> list[Stage]:
    all_stages: dict[str, Stage] = {
        "integrity": IntegrityStage(),
        "build": BuildStage(),
        "visible_tests": TaskTestsStage(hidden=False),
        "hidden_tests": TaskTestsStage(hidden=True),
        "candidate_tests": CandidateTestsStage(),
        "static_analysis": StaticAnalysisStage(),
        "security": SecurityStage(),
        "performance": PerformanceStage(),
        "llm_review": LLMReviewStage(review_fn),
    }
    if selected:
        unknown = set(selected) - all_stages.keys()
        if unknown:
            raise ValueError(f"unknown stage(s): {sorted(unknown)}")
        # integrity and build are prerequisites for everything else.
        keep = {"integrity", "build", *selected}
    else:
        keep = set(all_stages)
    return [all_stages[n] for n in STAGE_ORDER if n in keep]


__all__ = [
    "STAGE_ORDER",
    "Stage",
    "StageContext",
    "default_stages",
    "materialize_workspace",
]
