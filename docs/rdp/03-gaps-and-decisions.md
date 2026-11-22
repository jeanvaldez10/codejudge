# Gaps, contradictions, and decisions

Each item is something a reader of the README cannot settle from the README alone, or a place where the code does something the README does not say. The recommendation is the proposed spec. It is not implemented.

## Decisions that change verdicts

### D1. Gate cap is 0 or 49 depending on the gate

README says every gated candidate is capped at 49. `scoring.finalize` sets overall to **0** when the gate is `build` or `integrity`, and caps at **49** for `security` and `functional_correctness`.

Recommendation: keep the code. A candidate that does not build, or that tampers with the harness, has no partial credit. A candidate that builds and fails the security or correctness gate keeps a capped score so near-misses stay ordered under the passes. Update the README when implementation is approved. Add a test that pins both caps; `tests/test_scoring.py` does not cover them today.

### D2. A stage `error` can still produce verdict `pass`

`integrity` gates only on status `failed`. A crash in the integrity stage is `error` and is not a gate. `security` and `static_analysis` set status `error` when the tool crashes, and `build_scorecard` then drops the signal. `finalize` treats only `warning` and `failed` as warnings. Status `error` falls through to `pass` when no other gate fired.

The README's "fail closed" sentence describes the stage result (it must not say "clean"). It does not say what the verdict is.

Recommendation: add verdict `incomplete` for a candidate whose integrity, build, security, or test stage ended in `error`. `incomplete` ranks with `fail` (after every pass). Overall stays unset rather than 0, so an outage is not stored as a measured zero. Leaderboard pass@k excludes `incomplete` samples from both the solved count and the attempt count, so an operator outage does not punish the generator and does not count as a success. Static-analysis `error` alone is `incomplete` too, because a missing linter result is not a measured static score and the current code can still mark the candidate `pass`.

### D3. Rank prefers a clean pass over a higher warned score

`rank` orders by verdict, then score. The README's example table happens to match both orderings, so the rule is invisible. `test_rank_puts_failures_last` checks fail versus warned, not pass versus warned.

Recommendation: keep verdict-first ranking and state it in the requirements (already written that way in [01-requirements.md](01-requirements.md)). A warning must cost rank position, otherwise the warning status is decorative.

### D4. Report weights are the nominal table

When the LLM stage is skipped, the score is renormalized, and the report note says so. `EvaluationReport.weights` is still the original table, including the 0.10 LLM weight.

Recommendation: store both `weights` (nominal, unchanged) and `effective_weights` per candidate (the renormalized map actually used). The dashboard and Markdown report show the effective map when it differs.

## Decisions that change confidentiality

### D5. Hidden tests sit on disk while candidate code runs

`materialize_workspace` writes every suite, hidden included, under `_cj_tests/` before any stage. The candidate module and the candidate's own tests run in that tree. Integrity scans `solution_files()` only. A `test_*.py` file is executed by `candidate_tests` and is not scanned. Its stdout is stored on that stage and `redact_hidden` does not strip it. A candidate test can read `_cj_tests/` and print a hidden suite into a report that the public view still shows.

The README's known limitation is the shared interpreter. The file layout is a separate, stronger leak.

Recommendation for M1:

- Materialize only the suites that the current command needs. Hidden suites are absent during `visible_tests`, `candidate_tests`, static analysis, security, and any benchmark that does not need them.
- Run `inspect_source` on candidate test files with the same rules as solution files.
- After the run, if candidate-test logs or messages contain a line from a hidden suite, replace that text with a redaction marker and raise an integrity finding.

The separate-process test harness stays on the later roadmap (R3). M1 must not assume it exists.

### D6. Privileged access when no token is set

`is_privileged` is true when `CODEJUDGE_API_TOKEN` is empty. `GET /api/tasks/{id}` then returns hidden suites to any caller. Compose defaults the token to empty. The README says hidden suites are returned only to token holders, which is accurate only after a token is configured.

`GET /api/submissions` is unauthenticated even when a token is set. It returns labels, status, and ranking, not source and not hidden failures.

Recommendation: if the token is unset, task GET returns `public_view` and submission GET defaults to the redacted report. A new setting `CODEJUDGE_ALLOW_OPEN_ACCESS=1` restores today's open behavior for local demos. Compose does not set that flag. The submission list may stay open; it does not contain hidden material.

### D7. Dashboard asks for the full report

`api.submission` omits `view=public`. Combined with a token in `localStorage`, the stage drill-down renders hidden failure messages. There is no UI to set or clear the token, and the form always uploads `solution.py` even when `task.module` is something else. Every shipped task uses `solution`, so the library works and a custom task does not.

Recommendation: default the dashboard to `view=public`. Add a token field that writes `localStorage["codejudge.token"]`. Submit `<module>.py` using the module name from the task payload (the task list endpoint must return `module`).

## Operational gaps

### D8. A long run can be claimed twice

`requeue_stale` returns anything `running` for 30 minutes to the queue. A submission with several candidates, several benchmarks, and a 600 second limit can still be running. The second worker also writes the row. The last write wins. There is no lease.

Recommendation: add `lease_expires_at`, refreshed by the worker between candidates. Requeue only when the lease has expired. Keep the 30 minute default as the lease length, not as a silent assumption that every job finishes sooner. This is M2. The status names stay `queued` and `running`.

### D9. Two different size limits

The API rejects files larger than `CODEJUDGE_MAX_FILE_BYTES`. The integrity stage flags 256 KiB with a hardcoded literal, including when the setting is raised. `codejudge evaluate` applies neither check before the run; only the integrity literal applies, and only at or above 256 KiB.

Recommendation: one limit, the setting, enforced in `Candidate` validation so CLI, API, and integrity share it.

### D10. Webhook success is not the Action's success

The Action fails the job when the best overall score is below `fail-under`. The webhook marks the commit successful whenever the best verdict is not `fail`, including a warned score of 50. A pull request with no usable `.codejudge.yml` is ignored and gets no status, so a required check never appears.

Recommendation: webhook status is `failure` when the best verdict is `fail` or when `fail-under` is set in `.codejudge.yml` and the best score is below it. A pull request event that does not contain a valid config posts a `success` status with description "codejudge not configured" only when the file is absent, and a `failure` when the file is present but invalid. `fail-under` is optional in the YAML. GitHub Check Runs, which can be required and can carry annotations, are roadmap R6, not M2.

### D11. Relative performance needs the whole cohort

Unbudgeted benchmarks are scored against the fastest candidate in that `evaluate` call. The API refuses more than 8 candidates. The CLI and `codejudge bench` do not. Splitting a benchmark cohort across API submissions changes scores.

Recommendation: keep the interactive cap at 8. Benchmark runs go through the CLI, which they already do. Document that API submissions are a cohort: relative scores are meaningful inside one submission and are not comparable across submissions. A later hosted benchmark service (roadmap R7) accepts a run directory rather than stretching `MAX_CANDIDATES`.

### D12. Functional correctness can double-count

If a task has no suite in category `correctness`, functional correctness becomes the pass rate of every task test, while edge-case and integration rates are also scored. The same results then take the 0.35 weight and their own weights. Every task in `tasks/` has a correctness suite, so the library does not hit this.

Recommendation: reject a task that has tests and none of category `correctness`, unless the author sets `scoring.functional_from: all` (new optional field, default unset). Until that field exists, task validation requires at least one correctness suite when any suite exists. This keeps today's library valid and makes the fallback explicit for future authors.

### D13. Schema changes will not reach existing databases

`create_all` does not alter tables. Any column added for D4, D8, or a later `owner_id` needs a migration path before it is safe to ship to a database that already has rows.

Recommendation: introduce a migration tool in M2, before the first column is added. SQLite remains the test and single-process default. More than one worker against SQLite is unsupported and the worker logs a warning when it sees a SQLite URL.

### D14. Worker Docker socket

The worker container mounts `/var/run/docker.sock`. That is host-root equivalent. It is how the worker starts sandbox containers. The README's threat model describes the sandbox, not this control plane.

Recommendation: document it as an operator hazard in the deployment section. Replacing the socket with a sandboxed runtime (gVisor, Firecracker, or a dedicated runner API) is roadmap R4. M2 does not redesign it.

## Missing information that is not a defect

These are unspecified because the product has no requirement for them yet. The roadmap names the item that would introduce the requirement. Do not invent behavior for them in M1 or M2.

| Topic | Deferred to |
|---|---|
| Languages other than Python | R1 |
| Accounts, teams, per-task ACLs | R2 |
| Per-call process isolation between tests and candidate code | R3 |
| Sandbox without the host Docker socket | R4 |
| Generators other than Anthropic, directory, and reference | R5 |
| GitHub Check Runs and inline annotations | R6 |
| Hosted multi-machine leaderboards | R7 |
| Retention and deletion of stored candidate source | R2, because deletion policy follows ownership |

## Recommended lock for the spec

Accept D1 through D7 as written. D8 through D14 are accepted as the M2 design, and are not part of the M1 code change. R1 through R7 stay unscheduled.
