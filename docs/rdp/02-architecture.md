# Architecture

As-built structure of version 0.1.0. Later milestones extend the seams listed at the end. They do not replace the pipeline.

## Runtime

```
task author / generator / PR
        │
        ▼
 CLI evaluate ──────────────► pipeline.evaluate ──► Docker or local sandbox
        │
 dashboard / REST API ──► PostgreSQL queue (submissions)
        │                      │
        │                      ▼
        │                 worker (one or more)
        │                      │
        └──────────────────────┴──► pipeline.evaluate
                                      │
                                      ▼
                               report JSON + Markdown
                               GitHub status + PR comment
```

`docker compose` runs Postgres 16, the API, and two worker replicas. Workers mount the host Docker socket and a shared scratch directory (`CODEJUDGE_WORK_DIR`) at the same absolute path, because sandbox bind mounts are resolved by the host daemon.

Default database with no configuration is SQLite (`sqlite:///./codejudge.db`). Production compose uses Postgres. Schema is created with `Base.metadata.create_all`. There are no migrations.

## Code layout

| Path | Responsibility |
|---|---|
| `src/codejudge/models.py` | Task, candidate, stage result, scorecard, report. Validation for paths and reserved filenames. |
| `src/codejudge/pipeline.py` | Per-candidate stage loop, thread pool across candidates, relative performance, finalize. |
| `src/codejudge/scoring.py` | Weights, gates, renormalization, rank. |
| `src/codejudge/stages/` | One module per stage. `Stage.execute` skips a stage when a required predecessor failed or errored. |
| `src/codejudge/sandbox/` | `Sandbox` interface. `docker` is the production boundary. `local` is opt-in. |
| `src/codejudge/harness/` | `_cj_run_tests.py` and `_cj_bench.py`, copied into the workspace and run inside the sandbox. |
| `src/codejudge/api/` | FastAPI. Validates and enqueues. GitHub fetch and callback. |
| `src/codejudge/worker.py` | Claim, run, write the report, post to GitHub. |
| `src/codejudge/db.py` | `tasks` and `submissions`. Claim is a conditional `UPDATE` from `queued` to `running`. |
| `src/codejudge/generation.py` | Prompt from `Task.public_view` only. Claude, directory, reference. |
| `src/codejudge/benchmark.py` | Resumable run directory, pass@k, bootstrap, leaderboard. |
| `src/codejudge/report.py` | Markdown and `redact_hidden`. |
| `sandbox/` | Runner image (pytest, coverage, ruff, mypy, bandit, semgrep) and offline Semgrep rules. |
| `frontend/` | React dashboard: submission list, compare table, stage drill-down, paste-in submit form. |
| `tasks/` | Nine tasks with visible tests, hidden tests, benchmarks, and reference solutions. |

## Request lifecycle

1. `PUT /api/tasks/{id}` stores the full spec, including hidden tests.
2. `POST /api/submissions` checks candidate count (`CODEJUDGE_MAX_CANDIDATES`, default 8) and file size (`CODEJUDGE_MAX_FILE_BYTES`, default 256 KiB), snapshots the task, and inserts a row with status `queued`.
3. A worker calls `claim_next`. The oldest queued id is updated to `running` only if it is still queued. Five attempts, then it moves on.
4. `process` loads the snapshot, runs `evaluate`, and writes `completed` plus the report, or `failed` plus a traceback.
5. If the row has GitHub metadata and the run completed, the worker posts a commit status and, when `pr_number` is set, a PR comment. The comment is the redacted report.
6. `GET /api/submissions/{id}` returns the full report to a privileged caller and `redact_hidden` otherwise. Privileged means the token is unset, or the bearer matches `CODEJUDGE_API_TOKEN`.

Stale recovery: a row in `running` whose `started_at` is older than 30 minutes is set back to `queued`. There is no heartbeat.

## Workspace

`materialize_workspace` writes, under a temp directory:

- every candidate file
- every task suite, visible and hidden, under `_cj_tests/`
- the harness scripts

The directory is deleted after the candidate finishes. The Docker backend mounts it read-only at `/workspace` and collects results from a separate output directory.

## Scoring data flow

Each stage returns a `StageResult`. `build_scorecard` reads those results into a `Scorecard`. `apply_relative_performance` then overwrites `performance_score` for the whole cohort: budgeted benchmarks contribute `min(1, budget/median)`, unbudgeted ones contribute `fastest/mine`, and the score is the geometric mean. `finalize` applies gates and the verdict. `rank` orders the cohort.

`EvaluationReport.weights` stores the nominal weight table, not the renormalized weights of a particular candidate.

## GitHub

- Webhook: HMAC-SHA256 with `CODEJUDGE_GITHUB_WEBHOOK_SECRET`. Events `opened`, `synchronize`, `reopened`. Config is `.codejudge.yml` on the PR head. Code is fetched from the head repository. The status and comment are posted to the base repository named on the event.
- A missing or invalid config returns `ignored` and posts nothing.
- Commit status is `success` when the best-ranked candidate's verdict is not `fail`. The Action's `fail-under` threshold is not applied on the webhook path.
- `POST /api/github/evaluate` is the same fetch path, token-protected, with no pull request number.

## Dashboard

`frontend/src/App.tsx` polls `/api/submissions` every 3 seconds. The submit form always writes `solution.py` and optional `test_solution.py`. The API client sends `Authorization` when `localStorage["codejudge.token"]` is set. There is no screen that sets that key. The submission GET does not pass `view=public`, so a stored token receives hidden-test messages.

## Seams the roadmap depends on

These stay stable so later work is additive.

| Seam | Why it must survive |
|---|---|
| `Task.language` | Already a field, fixed to `"python"`. A future language is a new literal plus a stage pack, not a second pipeline. |
| `Sandbox.run(workspace, command, limits)` | Docker today. A gVisor or Firecracker backend implements the same interface. |
| `Stage` with `name`, `requires`, `run` | New checks are new stages inserted into `STAGE_ORDER`. |
| Task spec snapshot on the submission row | Reproducibility. A later `task_version` column is added beside the snapshot, not instead of it. |
| `Generator` protocol (`name`, `generate(task, sample)`) | OpenAI, local models, and other vendors are new implementations. Hidden tests stay out of `public_view`. |
| Public vs privileged report | `redact_hidden` and `Task.public_view` are the only redaction points. Multi-tenant ACLs wrap these; they do not grow a third copy of the report. |
| Queue status set `queued → running → completed\|failed` | A lease column can be added. Status names stay, so the dashboard and API do not change meaning. |
