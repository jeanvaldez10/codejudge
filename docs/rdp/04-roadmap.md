# Roadmap and milestones

No milestone below is started until the package is approved. M1 is the proposed first slice. Each milestone is shippable on its own. Later roadmap items are constraints on the design, not a commitment to build them.

## Milestone plan

### M1 — Spec lock and hidden-test containment

Goal: a reader of the requirements document and a reader of a report see the same rules, and a candidate cannot print a hidden suite into a public report.

In scope:

- Tests that pin D1 (overall 0 for build and integrity, cap 49 for security and correctness).
- Verdict `incomplete` per D2, including pass@k exclusion. Dashboard and Markdown render the new verdict.
- `effective_weights` on each candidate per D4.
- README updated to the locked rules: gate caps, verdict-first rank, subset-of-stages still runs integrity and build, relative scores apply only inside one cohort.
- Workspace layout and integrity scan per D5.
- Single file-size limit per D9.
- Task validation per D12: at least one `correctness` suite when the task has any tests.

Out of scope: auth defaults, leases, migrations, dashboard token UI, webhook `fail-under`, any new language or sandbox backend.

Exit: `pytest -m "not docker"` and the existing Docker isolation tests pass. A fixture candidate whose `test_*.py` reads `_cj_tests/` does not get hidden source into the public report, and the integrity stage fails it.

### M2 — Operator defaults

Goal: a default `docker compose up` does not publish hidden tests, and a crashed worker does not double-run a live job.

In scope:

- D6 open-access flag. Compose leaves the API token empty and does not set the flag, so hidden material stays redacted until an operator opts in.
- D7 dashboard: public view by default, token field, module-aware upload.
- D8 lease and refresh. Migration tool introduced before the column ships (D13). SQLite multi-worker warning.
- D10 webhook status rules and optional `fail-under` in `.codejudge.yml`.
- D14 written into the deployment section of the README: the Docker socket is host-root equivalent.

Out of scope: Check Runs, multi-tenant users, removing the Docker socket.

Exit: an unauthenticated `GET /api/tasks/{id}` against compose returns no hidden suite bodies. Two workers and a lease shorter than the job do not produce two completed writes. A pull request with a bad `.codejudge.yml` gets a failure status.

### M3 — Leaderboard in the product surface

Goal: the comparison the CLI already computes is visible without a terminal, still using one cohort per task.

In scope:

- Read-only leaderboard page over a run directory the operator points at (`CODEJUDGE_RUNS_DIR`), or over reports already stored if they were produced by `codejudge bench` uploading a JSON artifact through a new `POST /api/runs` that stores the manifest and per-task reports.
- The page shows pass@k, mean score, security-failure rate, and which pairwise gaps the bootstrap called significant.
- It does not recompute relative performance across runs.

Out of scope: scheduling generation, paying for model calls from the server, mixing samples from different machines into one relative-performance score.

Exit: the interval-merge example and a tiny synthetic run render the same numbers the CLI prints.

M3 waits until M1 is in, because `incomplete` must not be counted as a pass on that page.

## Later roadmap

These are not scheduled. M1–M3 must leave the seams in [02-architecture.md](02-architecture.md) intact so each item can land as an addition.

### R1. More languages

`Task.language` gains values one at a time. Each language brings a sandbox image, a build stage, a test harness, and scanner commands. Scoring weights, gates, redaction, and the queue stay language-agnostic. Python remains the default. No milestone may hardcode `solution.py` or `pytest` outside the Python stage pack. M1's dashboard change to use `task.module` is the first step of that rule.

### R2. Tenancy and retention

An `owner_id` column, nullable, appears with the M2 migration so existing rows stay valid. Hidden tests and full reports become readable by the owner and by the operator token. Public redaction stays the default for everyone else. Retention is a per-owner policy: delete submission source and reports after N days, keep the scorecard if the owner asks for a leaderboard. Until R2, the product is single-operator.

### R3. Process isolation for tests

The documented shared-interpreter limit. Each candidate call runs in a child process and returns a value over a pipe. The test file is not importable by the candidate. This replaces the AST denylist as the primary control; the denylist stays as a cheap pre-filter. D5 (hidden files not on disk) is the precondition, so R3 does not have to solve file layout at the same time.

### R4. Sandbox without the host Docker socket

A `Sandbox` implementation that does not mount `/var/run/docker.sock` into the worker: gVisor, Firecracker, or a small runner daemon with a narrow API. `DockerSandbox` remains for operators who already trust the socket. The isolation tests in `tests/test_docker_sandbox.py` become a suite the new backend must pass: no network, no writes to the workspace, memory limit, PID limit, timeout.

### R5. More generators

New `Generator` implementations. The prompt stays `build_prompt` / `Task.public_view`. Directory import stays the escape hatch for assistants that have no API. Generation remains a CLI and CI workflow step. The API server does not call model vendors on behalf of anonymous dashboard users.

### R6. GitHub Check Runs

Replace the commit-status-only callback with a check run that can be required in branch protection and that can annotate a line from a finding (`file` and `line` already exist on `Finding`). Webhook behavior from D10 stays: failure on a bad config, `fail-under` honored. The check run is a second transport, not a second verdict.

### R7. Hosted benchmark service

Upload a run directory (manifest, samples, per-task reports) and serve the M3 leaderboard for that run. Relative performance is whatever the producing machine stored. The service does not re-time samples from different hosts against each other. Generation stays outside the service so model credentials and spend stay with the operator.

## Sequence

```
approved spec
    │
    ▼
   M1  spec lock + hidden-test containment
    │
    ▼
   M2  operator defaults (auth, lease, migrations, webhook)
    │
    ▼
   M3  leaderboard page
    │
    ├── R1 languages
    ├── R2 tenancy and retention
    ├── R3 process-isolated tests
    ├── R4 socket-free sandbox
    ├── R5 generators
    ├── R6 check runs
    └── R7 hosted runs
```

R1–R7 can proceed in any order after M2, except R7 which wants M3's page. None of them are required for M1 to be useful.

## What approval means

Approving this package means D1–D7 are the spec and M1 is allowed to start. It does not start M2, M3, or any R item. Reply with the milestone to start, or with the decision ids to change before any code is touched.
