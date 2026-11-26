"""Benchmark runs: generate candidates for a task library with several
generators, evaluate them, and aggregate a leaderboard.

Run directory layout::

    <run>/manifest.json
    <run>/candidates/<task>/<generator>/<sample>/{*.py, meta.json}
    <run>/results/<task>.json        # EvaluationReport for every sample of the task

Every step is resumable: existing samples and results are kept unless
``force`` is set, so an interrupted or partially failed run can be finished
without paying for generation twice.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from codejudge.generation import GenerationResult, Generator, to_candidate, write_sample
from codejudge.loader import load_candidate, load_task
from codejudge.models import Candidate, CandidateReport, EvaluationReport, StageStatus, Verdict
from codejudge.pipeline import evaluate
from codejudge.sandbox import Sandbox

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class Manifest(BaseModel):
    created_at: str
    tasks: dict[str, str] = Field(description="task id -> task directory")
    generators: list[str]
    samples: int = Field(ge=1)
    stages: list[str] | None = None


def _manifest_path(run: Path) -> Path:
    return run / "manifest.json"


def load_manifest(run: Path) -> Manifest:
    return Manifest.model_validate_json(_manifest_path(run).read_text(encoding="utf-8"))


def _sample_dir(run: Path, task_id: str, generator: str, sample: int) -> Path:
    return run / "candidates" / task_id / generator / str(sample)


def label(generator: str, sample: int) -> str:
    return f"{generator}#{sample}"


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_run(
    run: Path,
    task_dirs: Sequence[Path],
    generators: Sequence[Generator],
    samples: int,
    *,
    parallel: int = 4,
    force: bool = False,
    stages: list[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> Manifest:
    run.mkdir(parents=True, exist_ok=True)
    tasks = {d.name: load_task(d) for d in task_dirs}
    for tid, task in tasks.items():
        if task.id != tid:
            raise ValueError(f"task directory {tid!r} declares id {task.id!r}")
    names = [g.name for g in generators]
    if len(set(names)) != len(names):
        raise ValueError(f"generator names must be unique: {names}")

    manifest = Manifest(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        tasks={tid: str(d) for tid, d in zip(tasks, task_dirs, strict=True)},
        generators=names,
        samples=samples,
        stages=stages,
    )
    if _manifest_path(run).exists() and not force:
        # Extending an existing run: merge rather than overwrite.
        old = load_manifest(run)
        manifest.created_at = old.created_at
        manifest.tasks = {**old.tasks, **manifest.tasks}
        manifest.generators = list(dict.fromkeys([*old.generators, *names]))
        manifest.samples = max(old.samples, samples)
        manifest.stages = stages if stages is not None else old.stages
    _manifest_path(run).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    jobs = [
        (task, gen, k)
        for task in tasks.values()
        for gen in generators
        for k in range(1, samples + 1)
        if force or not (_sample_dir(run, task.id, gen.name, k) / "meta.json").exists()
    ]

    def one(job: tuple[Any, Generator, int]) -> None:
        task, gen, k = job
        result: GenerationResult = gen.generate(task, k)
        write_sample(_sample_dir(run, task.id, gen.name, k), result)
        if progress:
            status = "ok" if result.error is None else f"error: {result.error[:120]}"
            progress(f"generated {task.id} / {label(gen.name, k)}: {status}")

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        list(pool.map(one, jobs))
    return manifest


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def load_samples(
    run: Path, task_id: str, manifest: Manifest
) -> tuple[list[Candidate], dict[str, str]]:
    """Candidates for a task, plus {label: error} for samples that can't be evaluated."""
    candidates: list[Candidate] = []
    errors: dict[str, str] = {}
    for gen in manifest.generators:
        for k in range(1, manifest.samples + 1):
            lbl = label(gen, k)
            d = _sample_dir(run, task_id, gen, k)
            meta_path = d / "meta.json"
            if not meta_path.exists():
                errors[lbl] = "not generated"
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("error"):
                errors[lbl] = meta["error"]
                continue
            files = load_candidate(f"x={d}").files
            result = to_candidate(lbl, gen, GenerationResult(files=files))
            if isinstance(result, str):
                errors[lbl] = result
            else:
                candidates.append(result)
    return candidates, errors


def evaluate_run(
    run: Path,
    sandbox: Sandbox,
    *,
    parallel: int = 2,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> None:
    manifest = load_manifest(run)
    (run / "results").mkdir(exist_ok=True)
    for task_id, task_dir in manifest.tasks.items():
        out = run / "results" / f"{task_id}.json"
        if out.exists() and not force:
            continue
        task = load_task(task_dir)
        candidates, errors = load_samples(run, task_id, manifest)
        if progress:
            progress(
                f"evaluating {task_id}: {len(candidates)} candidate(s), {len(errors)} unusable"
            )
        if candidates:
            # All samples of a task are evaluated together so relative
            # performance is measured on the same machine at the same time.
            report = evaluate(
                task, candidates, sandbox, selected_stages=manifest.stages, parallelism=parallel
            )
        else:
            report = EvaluationReport(
                task_id=task.id, task_title=task.title, candidates=[], ranking=[], weights={}
            )
        payload = report.model_dump(mode="json")
        payload["generation_errors"] = errors
        out.write_text(json.dumps(payload, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator (Chen et al., 2021): the probability that at
    least one of k samples drawn without replacement from n is correct."""
    if k > n:
        raise ValueError("k cannot exceed n")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def solved(rep: CandidateReport) -> bool:
    """Strict success: every task test passed (visible and hidden) and no gate failed."""
    if rep.verdict == Verdict.incomplete or rep.gates_failed:
        return False
    test_stages = [s for s in rep.stages if s.stage in ("visible_tests", "hidden_tests")]
    ran = [s for s in test_stages if s.status != StageStatus.skipped]
    return bool(ran) and all(s.status == StageStatus.passed for s in ran)


class TaskCell(BaseModel):
    solved: int
    samples: int
    mean_score: float | None = None


class GeneratorStats(BaseModel):
    generator: str
    tasks: int
    samples_per_task: int
    generation_errors: int
    pass_at_1: float | None
    pass_at_1_ci: tuple[float, float] | None
    pass_at_k: dict[int, float]
    mean_score: float | None
    mean_score_ci: tuple[float, float] | None
    functional_correctness: float | None
    edge_case_handling: float | None
    test_coverage: float | None
    static_quality: float | None
    performance_score: float | None
    security_failure_rate: float
    integrity_violations: int
    output_tokens: int | None


class Pairwise(BaseModel):
    a: str
    b: str
    score_diff: float
    score_diff_ci: tuple[float, float]
    prob_a_better: float
    significant: bool


class Leaderboard(BaseModel):
    run: str
    tasks: list[str]
    samples_per_task: int
    generators: list[GeneratorStats]
    pairwise: list[Pairwise]
    per_task: dict[str, dict[str, TaskCell]]
    notes: list[str]


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _defined(xs: Sequence[float | None]) -> list[float]:
    return [x for x in xs if x is not None]


def _mean_opt(xs: Sequence[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(_mean(vals), 2) if vals else None


def _percentile(sorted_xs: Sequence[float], q: float) -> float:
    idx = min(len(sorted_xs) - 1, max(0, round(q * (len(sorted_xs) - 1))))
    return sorted_xs[idx]


def _round_pair(pair: tuple[float, float], digits: int = 2) -> tuple[float, float]:
    return (round(pair[0], digits), round(pair[1], digits))


def _bootstrap_indices(n_tasks: int, n_boot: int, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    return [[rng.randrange(n_tasks) for _ in range(n_tasks)] for _ in range(n_boot)]


def _ci(values: Sequence[float | None], boots: list[list[int]]) -> tuple[float, float]:
    present = _defined(values)
    if len(present) < 2:
        v = present[0] if present else 0.0
        return (v, v)
    means: list[float] = []
    for idx in boots:
        sample = _defined([values[i] for i in idx])
        if sample:
            means.append(_mean(sample))
    if len(means) < 2:
        v = means[0] if means else 0.0
        return (v, v)
    means.sort()
    return (round(_percentile(means, 0.025), 4), round(_percentile(means, 0.975), 4))


def build_leaderboard(run: Path, *, n_boot: int = 2000, seed: int = 0) -> Leaderboard:
    manifest = load_manifest(run)
    n = manifest.samples
    task_ids = sorted(manifest.tasks)
    reports: dict[str, dict[str, CandidateReport]] = {}
    gen_errors: dict[str, dict[str, str]] = {}
    for tid in task_ids:
        path = run / "results" / f"{tid}.json"
        if not path.exists():
            raise FileNotFoundError(f"no results for task {tid!r}; run `codejudge bench` first")
        data = json.loads(path.read_text(encoding="utf-8"))
        gen_errors[tid] = data.pop("generation_errors", {})
        report = EvaluationReport.model_validate(data)
        reports[tid] = {c.label: c for c in report.candidates}

    tokens: dict[str, int] = {}
    for gen in manifest.generators:
        for tid in task_ids:
            for k in range(1, n + 1):
                meta = _sample_dir(run, tid, gen, k) / "meta.json"
                if meta.exists():
                    out_tok = json.loads(meta.read_text()).get("usage", {}).get("output_tokens")
                    if isinstance(out_tok, int):
                        tokens[gen] = tokens.get(gen, 0) + out_tok

    boots = _bootstrap_indices(len(task_ids), n_boot, seed)
    stats: list[GeneratorStats] = []
    per_task: dict[str, dict[str, TaskCell]] = {tid: {} for tid in task_ids}
    task_scores: dict[str, list[float | None]] = {}
    for gen in manifest.generators:
        solve_frac: list[float | None] = []
        scores: list[float | None] = []
        pak: dict[int, list[float | None]] = {k: [] for k in sorted({1, n})}
        evaluated: list[CandidateReport] = []
        errors = 0
        for tid in task_ids:
            sample_reps = [reports[tid].get(label(gen, k)) for k in range(1, n + 1)]
            errors += sum(r is None for r in sample_reps)
            # Generation errors stay in the attempt count with score 0.
            # An incomplete evaluation is an operator outage: drop it from both
            # the solved count and the attempt count, and do not store it as 0.
            counted = [
                r for r in sample_reps if r is None or r.verdict != Verdict.incomplete
            ]
            evaluated += [r for r in sample_reps if r is not None]
            if not counted:
                solve_frac.append(None)
                scores.append(None)
                for k in pak:
                    pak[k].append(None)
                per_task[tid][gen] = TaskCell(solved=0, samples=0, mean_score=None)
                continue
            c = sum(1 for r in counted if r is not None and solved(r))
            sample_scores = [
                0.0 if r is None else float(r.scorecard.overall or 0.0) for r in counted
            ]
            solve_frac.append(c / len(counted))
            scores.append(_mean(sample_scores))
            for k in pak:
                pak[k].append(pass_at_k(len(counted), c, k) if len(counted) >= k else None)
            per_task[tid][gen] = TaskCell(
                solved=c, samples=len(counted), mean_score=round(_mean(sample_scores), 2)
            )
        task_scores[gen] = scores
        measured = [r for r in evaluated if r.verdict != Verdict.incomplete]
        sc = [r.scorecard for r in measured]
        defined_solve = _defined(solve_frac)
        defined_scores = _defined(scores)
        pak_means: dict[int, float] = {}
        for k, vals in pak.items():
            defined = _defined(vals)
            if defined:
                pak_means[k] = round(_mean(defined), 4)
        stats.append(
            GeneratorStats(
                generator=gen,
                tasks=len(task_ids),
                samples_per_task=n,
                generation_errors=errors,
                pass_at_1=round(_mean(defined_solve), 4) if defined_solve else None,
                pass_at_1_ci=_ci(solve_frac, boots) if defined_solve else None,
                pass_at_k=pak_means,
                mean_score=round(_mean(defined_scores), 2) if defined_scores else None,
                mean_score_ci=_round_pair(_ci(scores, boots)) if defined_scores else None,
                functional_correctness=_mean_opt([s.functional_correctness for s in sc]),
                edge_case_handling=_mean_opt([s.edge_case_handling for s in sc]),
                test_coverage=_mean_opt([s.test_coverage for s in sc]),
                static_quality=_mean_opt([s.static_quality for s in sc]),
                performance_score=_mean_opt([s.performance_score for s in sc]),
                security_failure_rate=round(
                    _mean([1.0 if s.security == "fail" else 0.0 for s in sc]), 4
                ),
                integrity_violations=sum("integrity" in r.gates_failed for r in measured),
                output_tokens=tokens.get(gen),
            )
        )
    stats.sort(
        key=lambda g: (
            -(g.pass_at_1 if g.pass_at_1 is not None else -1.0),
            -(g.mean_score if g.mean_score is not None else -1.0),
            g.generator,
        )
    )

    pairwise: list[Pairwise] = []
    for i, a in enumerate(stats):
        for b in stats[i + 1 :]:
            xa, xb = task_scores[a.generator], task_scores[b.generator]
            diffs = [
                None if p is None or q is None else p - q
                for p, q in zip(xa, xb, strict=True)
            ]
            present = _defined(diffs)
            if not present:
                continue
            # Paired bootstrap over tasks: both generators see the same
            # resampled tasks, which cancels out task difficulty.
            if len(diffs) > 1:
                boot_means = [
                    _mean(sample)
                    for idx in boots
                    if (sample := _defined([diffs[j] for j in idx]))
                ]
                boot = sorted(boot_means) if boot_means else present
            else:
                boot = present
            lo, hi = _percentile(boot, 0.025), _percentile(boot, 0.975)
            better = sum(1.0 if d > 0 else 0.5 if d == 0 else 0.0 for d in boot) / len(boot)
            pairwise.append(
                Pairwise(
                    a=a.generator,
                    b=b.generator,
                    score_diff=round(_mean(present), 2),
                    score_diff_ci=(round(lo, 2), round(hi, 2)),
                    prob_a_better=round(better, 3),
                    significant=lo > 0 or hi < 0,
                )
            )

    notes = [
        "pass@1 counts a sample as solved only if every visible and hidden test passed "
        "and no gate (build, integrity, security, correctness) failed.",
        "Samples that failed to generate count as unsolved with a score of 0.",
        "An incomplete evaluation is left out of pass@k, both the solved count and the attempt count.",
        f"95% confidence intervals come from {n_boot} bootstrap resamples over tasks.",
    ]
    if len(task_ids) < 20:
        notes.append(
            f"Only {len(task_ids)} tasks: intervals are wide, so treat small gaps as noise "
            "unless the pairwise comparison marks them significant."
        )
    if any(gen_errors.values()):
        notes.append("Some samples could not be evaluated; see generation errors per generator.")
    return Leaderboard(
        run=str(run),
        tasks=task_ids,
        samples_per_task=n,
        generators=stats,
        pairwise=pairwise,
        per_task=per_task,
        notes=notes,
    )


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0f}%"


def render_leaderboard(lb: Leaderboard) -> str:
    n = lb.samples_per_task
    lines = [
        "# CodeJudge leaderboard",
        "",
        f"{len(lb.tasks)} tasks x {n} sample(s) per task per generator.",
        "",
    ]
    k_col = f" pass@{n} |" if n > 1 else ""
    lines.append(
        "| Rank | Generator | pass@1 (95% CI) |" + k_col + " Mean score (95% CI) | Correctness "
        "| Edge cases | Own-test coverage | Static quality | Security failures | Generation errors |"
    )
    lines.append("|" + "---|" * (10 + (1 if n > 1 else 0)))
    for i, g in enumerate(lb.generators, 1):
        if g.pass_at_1 is None or g.pass_at_1_ci is None:
            p1 = "n/a"
        else:
            lo, hi = g.pass_at_1_ci
            p1 = f"{g.pass_at_1 * 100:.0f}% ({lo * 100:.0f}-{hi * 100:.0f})"
        if g.mean_score is None or g.mean_score_ci is None:
            mean = "n/a"
        else:
            slo, shi = g.mean_score_ci
            mean = f"{g.mean_score:.1f} ({slo:.1f}-{shi:.1f})"
        if n > 1:
            rate = g.pass_at_k.get(n)
            k_val = " n/a |" if rate is None else f" {rate * 100:.0f}% |"
        else:
            k_val = ""
        lines.append(
            f"| {i} | **{g.generator}** | {p1} |"
            f"{k_val} {mean} | {_pct(g.functional_correctness)} "
            f"| {_pct(g.edge_case_handling)} | {_pct(g.test_coverage)} | {_pct(g.static_quality)} "
            f"| {g.security_failure_rate * 100:.0f}% | {g.generation_errors} |"
        )
    if lb.pairwise:
        lines += ["", "## Pairwise comparison (mean score)", ""]
        lines.append("| A | B | A - B (95% CI) | P(A better) | Significant |")
        lines.append("|---|---|---|---|---|")
        for p in lb.pairwise:
            lo, hi = p.score_diff_ci
            lines.append(
                f"| {p.a} | {p.b} | {p.score_diff:+.1f} ({lo:+.1f} to {hi:+.1f}) "
                f"| {p.prob_a_better:.0%} | {'yes' if p.significant else 'no'} |"
            )
    gens = [g.generator for g in lb.generators]
    lines += ["", "## Per task (solved / samples, mean score)", ""]
    lines.append("| Task | " + " | ".join(gens) + " |")
    lines.append("|" + "---|" * (len(gens) + 1))
    for tid in lb.tasks:
        cells = [lb.per_task[tid][g] for g in gens]
        lines.append(
            f"| {tid} | "
            + " | ".join(
                f"{c.solved}/{c.samples} · "
                + ("n/a" if c.mean_score is None else f"{c.mean_score:.0f}")
                for c in cells
            )
            + " |"
        )
    lines += ["", "## Notes", ""] + [f"- {x}" for x in lb.notes]
    return "\n".join(lines) + "\n"
