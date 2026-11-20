# CodeJudge

**An evaluation engine for AI-generated code.** Give it a programming task and
one or more candidate implementations (from different models, prompts or
agents). It runs each candidate through independent verification stages
inside resource-limited, network-less containers, and produces a structured,
comparable report.

An LLM is **not** the judge here. Deterministic evidence (tests, static
analysis, security scanning, runtime measurements) decides the verdict. An
LLM rubric review adds a capped, advisory signal on top.

```
| Evaluation criterion            | Model A | Model B | Model C            |
|---------------------------------|---------|---------|--------------------|
| Verdict                         | pass    | fail    | pass_with_warnings |
| Overall score                   | 98.4    | 49.0    | 60.7               |
| Functional correctness          | 100%    | 100%    | 80%                |
| Edge-case handling              | 100%    | 58%     | 58%                |
| Integration                     | 100%    | 100%    | 50%                |
| Own-test coverage               | 100%    | 79%     | n/a                |
| Static quality                  | 100%    | 67%     | 24%                |
| Security checks                 | Pass    | Fail    | Pass               |
| Execution time (geomean median) | 3.79 ms | 2.62 ms | n/a (timed out)    |
| Gates failed                    | —       | security| —                  |
```
<sub>Real output from `examples/interval-merge` on the Docker sandbox. Model B is the
fastest and passes every correctness test, but parses input with `eval()`, so
the security gate fails it. Model C mutates its input, misses touching
intervals and is quadratic, so its benchmark times out.</sub>

## Verification stages

| # | Stage | What it checks | Where it runs |
|---|---|---|---|
| 1 | `integrity` | AST scan for harness tampering: importing pytest internals, `os._exit`, frame inspection, patching builtins / `sys.modules`, probing evaluator paths, prompt injection aimed at the LLM reviewer | host (parse only, never executes) |
| 2 | `build` | Every file compiles; the required module imports | sandbox |
| 3 | `visible_tests` | Task-author pytest suites shown to generators | sandbox |
| 4 | `hidden_tests` | Held-out suites (correctness / edge cases / integration), never shown to candidates or the LLM, redacted in public reports | sandbox |
| 5 | `candidate_tests` | The generator's own tests: pass rate and line+branch coverage of its own solution | sandbox |
| 6 | `static_analysis` | Ruff (lint, bug-prone patterns, McCabe complexity), mypy, annotation coverage | sandbox |
| 7 | `security` | Bandit + Semgrep with offline rules (eval/exec, shell injection, unsafe deserialisation, SQL string building, weak crypto, hard-coded secrets, TLS verification off) | sandbox |
| 8 | `performance` | Median / p95 / peak memory per benchmark, each in its own container and time limit; inputs deep-copied per run so in-place mutation can't skew timings | sandbox |
| 9 | `llm_review` | Claude scores a rubric (readability, maintainability, idioms, error handling, algorithmic reasoning) from the code plus the deterministic evidence | worker (no code execution) |

### Scoring and gates

* Weighted score: correctness 35%, edge cases 15%, integration 5%, own-test
  coverage 5%, static quality 10%, security 10%, performance 10%, LLM 10%.
  Weights of unavailable signals are redistributed.
* **Hard gates** override the weighted score: build failure, integrity
  violation, any high-severity security finding, or < 50% functional
  correctness → verdict `fail`. A gated candidate's score is capped at 49, so
  it can never outrank a passing one.
* Performance with a `time_budget_ms` is scored against the budget; without
  one it is scored relative to the fastest candidate in the same run.
* The LLM never sees hidden tests, can't change a gate, and is told to treat
  the code as untrusted data. Prompt-injection text in the code is flagged by
  the integrity stage too.

## Isolation model

The API server never executes submitted code. It validates and enqueues; a
**worker** claims jobs and runs each command in a fresh container:

* `--network none`, `--read-only` root FS, workspace mounted read-only
* one writable output dir for results, a `noexec` tmpfs for scratch
* `--cap-drop ALL`, `no-new-privileges`, non-root UID 10001
* cgroup memory limit with no swap, CPU quota, PID limit, file-size and fd ulimits
* wall-clock timeout enforced from outside (`docker kill`)

These are checked by `tests/test_docker_sandbox.py`, which submits network
access, writes to the workspace and system dirs, a 1 GiB allocation, a fork
bomb and an infinite loop, and checks that each one is contained.

The scanners **fail closed**. If Semgrep, Bandit, Ruff or mypy crash, the
stage reports `error`. It never reports a clean result. A test run that
crashes or exits early (e.g. an obfuscated `os._exit`) scores 0, never "no
failures".

Candidates can't ship `conftest.py`, `sitecustomize.py`, pytest/mypy/ruff
config files or paths outside the workspace.

**Known limitation:** candidate code runs in the same interpreter as the
tests that exercise it, so a determined adversary could still inspect the
test at runtime. The integrity stage catches the common forms. A stricter
mode would run each call in a separate process and return values over a pipe.

A `local` backend (rlimits only, **not** a security boundary) exists for
development and CI machines without Docker. It refuses to start unless
`CODEJUDGE_ALLOW_LOCAL_SANDBOX=1` is set.

## Quick start

```bash
pip install -e ".[dev,llm]"
docker build -t codejudge-sandbox:latest sandbox/
```

Evaluate candidates from the command line:

```bash
codejudge evaluate examples/interval-merge \
  -c "Model A=examples/interval-merge/candidates/model_a@assistant-a" \
  -c "Model B=examples/interval-merge/candidates/model_b@assistant-b" \
  -c "Model C=examples/interval-merge/candidates/model_c@assistant-c" \
  --format md -o report.md
```

Run the service (API + worker + PostgreSQL):

```bash
docker compose up --build
```

```bash
codejudge push-task examples/interval-merge --api http://localhost:8000
```

To enable the LLM review stage, set `ANTHROPIC_API_KEY` for the worker. It
uses `claude-opus-5-5` by default (`CODEJUDGE_LLM_MODEL`,
`CODEJUDGE_LLM_EFFORT`). Without credentials the stage is skipped and its
weight is redistributed.

### REST API

| Method | Path | |
|---|---|---|
| `PUT` | `/api/tasks/{id}` | Create or update a task (hidden tests included) |
| `GET` | `/api/tasks`, `/api/tasks/{id}` | Hidden suites only returned to token holders |
| `POST` | `/api/submissions` | `{task_id or task, candidates: [{label, model, files}], stages?}` → `202` |
| `GET` | `/api/submissions/{id}?view=full\|public` | Status and structured report |
| `GET` | `/api/submissions/{id}/report.md` | Markdown report |
| `POST` | `/api/github/evaluate` | Evaluate files from `{repo, ref}` |
| `POST` | `/api/github/webhook` | Pull-request webhook (HMAC-verified) |

Set `CODEJUDGE_API_TOKEN` to require `Authorization: Bearer …` on mutating
endpoints. The interactive docs are at `/docs`.

### GitHub integration

* **Webhook:** point a repository's `pull_request` webhook at
  `/api/github/webhook` (secret in `CODEJUDGE_GITHUB_WEBHOOK_SECRET`) and add a
  `.codejudge.yml` (see `examples/.codejudge.yml`). CodeJudge evaluates the PR
  head, then posts a commit status and a PR comment with the redacted report.
* **GitHub Action:** run evaluations in CI with no server:

  ```yaml
  - uses: jeanvaldez10/codejudge@main
    with:
      task: tasks/interval-merge
      candidates: |
        Copilot=generated/copilot@copilot
        Claude=generated/claude@claude
      fail-under: 70
  ```

### Dashboard

```bash
cd frontend && npm ci && npm run build   # served by the API at /
npm run dev                              # or a dev server proxying to :8000
```

## Defining a task

```yaml
id: interval-merge
title: Merge overlapping intervals
description: |            # the prompt given to code generators
  Implement merge_intervals(...) in solution.py ...
module: solution          # file candidates must provide
entrypoint: merge_intervals   # callable used by benchmarks
limits: {timeout_seconds: 30, memory_mb: 512, cpus: 1}
tests:
  - {name: test_basic, file: tests/test_basic.py, category: correctness}
  - {name: test_hidden_edge_cases, file: tests/test_hidden_edge_cases.py, category: edge_case, hidden: true}
benchmarks:
  - name: 20k_random
    setup: |              # trusted code; binds `args` (and optionally `kwargs`)
      import random
      args = ([(p, p + 5) for p in random.Random(1).sample(range(10**6), 20_000)],)
    time_budget_ms: 50
rubric: [readability, maintainability, idiomatic_usage, error_handling, algorithmic_reasoning]
```

## Development

```bash
ruff check src tests && mypy
pytest -m "not docker"   # unit, API, queue, local-backend pipeline tests
pytest -m docker         # isolation tests (needs Docker and the sandbox image)
CODEJUDGE_TEST_DATABASE_URL=postgresql+psycopg://... pytest -m "not docker"
```

Layout:

```
src/codejudge/
  api/        FastAPI app + GitHub integration
  sandbox/    docker (production) and local (dev) backends
  harness/    scripts copied into the sandbox (pytest collector, benchmark runner)
  stages/     one module per verification stage
  scoring.py  scorecards, gates, relative performance, ranking
  pipeline.py orchestration;  worker.py  queue consumer;  db.py  persistence
sandbox/      runner image + offline Semgrep rules
frontend/     React dashboard
examples/     a task with visible/hidden suites, benchmarks and 3 candidates
```
