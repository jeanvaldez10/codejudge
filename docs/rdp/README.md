# CodeJudge requirements and design package

Status: **proposed**. This package records the product as it behaves in version 0.1.0, the decisions that are still open, and a milestone plan. It is not approval to change the code.

RDP here means the requirements and design package: what the product must do, how the current system is built, where the spec and the code disagree, and what to build later without blocking the roadmap.

| Document | What it settles |
|---|---|
| [01-requirements.md](01-requirements.md) | Business rules, actors, and the evaluation contract |
| [02-architecture.md](02-architecture.md) | As-built structure and the extension points later milestones must keep |
| [03-gaps-and-decisions.md](03-gaps-and-decisions.md) | Contradictions, missing rules, and the recommended resolution for each |
| [04-roadmap.md](04-roadmap.md) | Milestones that wait for approval, and the later roadmap they must not block |

## Product in one paragraph

CodeJudge compares candidate implementations of a programming task. Deterministic stages (integrity, build, visible tests, hidden tests, the candidate's own tests, static analysis, security, performance) produce the verdict. An LLM rubric review is advisory, capped, and cannot override a failed gate. The API enqueues work. A worker runs each command in a fresh network-less container. A task library and a benchmark runner turn that into pass@k leaderboards for coding assistants.

## What is already true

The pipeline, scoring, Docker sandbox, queue, REST API, GitHub webhook, GitHub Action, dashboard, nine-task library, and benchmark statistics exist and are covered by tests. The next work is to close spec gaps and production hazards, not to rebuild the evaluator.

## Approval gate

Implementation starts only after these are accepted or replaced:

1. The recommended resolutions in [03-gaps-and-decisions.md](03-gaps-and-decisions.md), especially verdict behavior when a stage errors.
2. The milestone order in [04-roadmap.md](04-roadmap.md). M1 is the default first slice.
