# Requirements

Source of truth for behavior that the code, the README, and the tests already agree on. Where they disagree, [03-gaps-and-decisions.md](03-gaps-and-decisions.md) wins until a decision is approved and then this document is updated.

## Purpose

Give an operator a structured, comparable verdict on one or more candidate solutions to a programming task. The verdict is evidence from tools that run the code, not a model's opinion of the code.

Two jobs fall out of that:

1. **Compare candidates** for a single task (models, prompts, or agents) and rank them.
2. **Compare generators** across the task library with pass@k, mean scores, and bootstrap confidence intervals.

## Actors

| Actor | What they can do |
|---|---|
| Task author | Writes the prompt, visible tests, hidden tests, benchmarks, limits, and a reference solution. Hidden tests are the hold-out set. |
| Generator | Produces candidate files from the public task only. Built-in generators are Claude (`anthropic:<model>[:<effort>]`), a directory of collected solutions (`dir:<name>=<path>`), and `reference`. |
| Operator | Registers tasks, submits candidates, reads full reports, runs the worker, and configures tokens. |
| Candidate author / pull request | Submits code through the API, the CLI, the dashboard, or a GitHub pull request that contains `.codejudge.yml`. |
| Reviewer model | Scores a fixed rubric from the public task, the candidate source, and a redacted evidence summary. It is not an actor with authority over the verdict. |

There is no user, team, or organization model. One optional bearer token (`CODEJUDGE_API_TOKEN`) protects mutating routes and the privileged view of hidden material.

## Evaluation contract

A submission names exactly one of `task` or `task_id`, and one or more candidates with unique labels. Each candidate is a map of relative `.py` paths to source and must be able to provide `<module>.py` (default `solution.py`). Files named `test_*.py` are the candidate's own tests. Reserved names (`conftest.py`, pytest/mypy/ruff config, `sitecustomize.py`, anything starting with `_cj_`) are rejected.

Stages run in this order. A selected subset still runs `integrity` and `build` first, because later stages depend on them.

| Stage | Pass condition | Effect on the verdict |
|---|---|---|
| `integrity` | AST scan of solution files finds no high or critical tamper/injection finding | Failure is a hard gate. Score becomes 0. |
| `build` | `<module>.py` is present, every solution file compiles, the module imports | Any non-pass is a hard gate. Score becomes 0. |
| `visible_tests` | Task-author suites with `hidden: false` | Feeds functional correctness, edge cases, and integration. A crashed run scores 0, not "no failures". |
| `hidden_tests` | Held-out suites | Same scoring. Names and failure text are removed in the public report. |
| `candidate_tests` | Generator-written tests, plus line and branch coverage of its own solution | Coverage counts only for tests that pass. Missing tests drop this signal and its weight is redistributed. |
| `static_analysis` | Ruff, mypy, annotation coverage | Score only. Not a gate. A tool crash is stage status `error` and the signal is dropped. |
| `security` | Bandit and offline Semgrep | High or critical finding is a hard gate. Low and medium findings reduce `security_score` and yield a warning. A scanner crash is stage status `error` and must not look like a clean scan. |
| `performance` | One container per benchmark | A budget miss is a warning, not a gate. No budget means the score is relative to the fastest candidate in the same run. A timeout contributes 0 and suppresses the headline geomean. |
| `llm_review` | Rubric integers 1–5, mapped onto 0–100 | Advisory. Skipped when no credentials. Cannot override a gate. |

### Score

Nominal weights:

| Signal | Weight |
|---|---|
| Functional correctness | 0.35 |
| Edge-case handling | 0.15 |
| Integration | 0.05 |
| Own-test coverage | 0.05 |
| Static quality | 0.10 |
| Security score | 0.10 |
| Performance score | 0.10 |
| LLM quality | 0.10 |

Signals that did not run are left out and the remaining weights are renormalized. Build or integrity failure forces overall to 0. Any other gate caps overall at 49, so a gated candidate cannot outrank a passing one.

Functional correctness is the pass rate of tests in category `correctness`. Edge-case and integration rates are separate. A task with no `correctness` suites falls back to the pass rate of all task tests for the functional-correctness signal.

### Verdict and rank

- `fail` when any gate fired.
- `pass_with_warnings` when no gate fired and any non-LLM stage is `warning` or `failed` (a benchmark over budget, a partial test run at or above 50%, low-severity security findings, weak static score).
- `pass` otherwise.

Rank is verdict first (`pass`, then `pass_with_warnings`, then `fail`), then overall score, then functional correctness. A clean pass at 60 outranks a warned pass at 95.

### Leaderboard

A sample is solved only when every visible and hidden test passed and no gate failed. Generation errors count as unsolved with score 0. pass@1 and pass@k use the unbiased estimator. Confidence intervals are a bootstrap over tasks. A pairwise gap is significant only when its interval excludes zero. Samples of one task are evaluated together so relative performance is measured on the same machine at the same time.

## Isolation contract

The API process does not execute candidate code. The worker does, inside a fresh container:

- `--network none`, read-only root, workspace mounted read-only
- one writable output directory, a `noexec` tmpfs for scratch
- capabilities dropped, `no-new-privileges`, uid 10001
- memory limit with no swap, CPU quota, PID limit, file-size and fd ulimits
- wall clock enforced from outside the container (`docker kill`)

Scanners fail closed at the stage: a crash is `error`, never an empty clean result. The `local` sandbox is rlimits only and refuses to start unless `CODEJUDGE_ALLOW_LOCAL_SANDBOX=1`.

Candidate code and the tests that call it share an interpreter. The integrity stage blocks the common tamper patterns. A stricter per-call process boundary is a later roadmap item, not a current guarantee.

## Task contract

A task is YAML (or the JSON body of `PUT /api/tasks/{id}`). Required: `id`, `title`, `description`. Language is Python only. Benchmarks either call `entrypoint` or define `bench(module)` in trusted setup code. The setup runs in the sandbox, not on the host. Hidden suites are part of the stored spec. A submission stores a snapshot of the spec, so a later task edit does not change a past result.

Reference solutions in `tasks/` must pass their own hidden tests. `tests/test_task_library.py` enforces that.

## Interfaces that must keep working

- CLI: `evaluate`, `generate`, `bench`, `leaderboard`, `push-task`, `serve`, `worker`
- API: task upsert/list/get, submission create/list/get, Markdown report, `POST /api/github/evaluate`, `POST /api/github/webhook`
- GitHub Action inputs: `task`, `candidates`, `fail-under`, `stages`, `anthropic-api-key`
- Dashboard served by the API at `/` when `frontend/dist` exists

## Explicit non-goals for the current release

- Languages other than Python
- Accounts, teams, or per-task access control beyond the single operator token
- The LLM as a source of correctness
- A security boundary on the `local` sandbox
- Running candidate code inside the API process (except the documented `CODEJUDGE_INLINE_WORKER` demo mode)
