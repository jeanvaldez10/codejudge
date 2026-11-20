"""Performance benchmarking inside the sandbox.

Absolute scores use each benchmark's ``time_budget_ms``. Benchmarks without a
budget are scored *relative to the fastest candidate* by the scoring module
after all candidates finish, since raw milliseconds are only meaningful
side by side on the same hardware.
"""

from __future__ import annotations

import json
import math

from codejudge.models import BenchmarkResult, StageResult, StageStatus
from codejudge.stages.base import Stage, StageContext


class PerformanceStage(Stage):
    name = "performance"
    requires = ("build",)

    def run(self, ctx: StageContext) -> StageResult:
        task = ctx.task
        if not task.benchmarks or not task.entrypoint:
            return StageResult(
                stage=self.name, status=StageStatus.skipped, summary="task defines no benchmarks"
            )
        results: list[BenchmarkResult] = []
        logs: list[str] = []
        # One sandbox run per benchmark: each gets the full time limit, and a
        # pathological case cannot starve the others.
        for i, b in enumerate(task.benchmarks):
            cfg = ctx.write_config(
                f"bench{i}",
                {
                    "module": task.module,
                    "entrypoint": task.entrypoint,
                    "benchmarks": [b.model_dump()],
                },
            )
            res = ctx.run(["{python}", "_cj_bench.py", cfg])
            raw = json.loads(res.outputs.get("bench.json", '{"benchmarks": []}'))["benchmarks"]
            r = next((x for x in raw if x.get("name") == b.name), None)
            if r is None:
                why = "timed out" if res.timed_out else res.describe_failure()
                results.append(
                    BenchmarkResult(
                        name=b.name,
                        ok=False,
                        budget_ms=b.time_budget_ms,
                        error=f"not completed: {why}",
                    )
                )
                logs.append(res.stderr[-1000:])
                continue
            br = BenchmarkResult.model_validate(
                {k: v for k, v in r.items() if k in BenchmarkResult.model_fields}
            )
            br.budget_ms = b.time_budget_ms
            if br.ok and b.time_budget_ms is not None and br.median_ms is not None:
                br.within_budget = br.median_ms <= b.time_budget_ms
            results.append(br)

        budget_scores = [
            100.0 * min(1.0, r.budget_ms / r.median_ms) if r.ok and r.median_ms else 0.0
            for r in results
            if r.budget_ms is not None
        ]
        failed = [r for r in results if not r.ok]
        over = [r for r in results if r.within_budget is False]
        medians = [r.median_ms for r in results if r.ok and r.median_ms]
        geo = (
            math.exp(sum(math.log(max(m, 1e-6)) for m in medians) / len(medians))
            if medians
            else None
        )
        status = (
            StageStatus.failed if failed else StageStatus.warning if over else StageStatus.passed
        )
        return StageResult(
            stage=self.name,
            status=status,
            # Provisional; relative scoring may replace it (see scoring.py).
            score=round(sum(budget_scores) / len(budget_scores), 2)
            if budget_scores and not failed
            else (0.0 if failed else None),
            summary=(
                f"{len(failed)} benchmark(s) failed: {failed[0].error}"
                if failed
                else f"{len(over)} benchmark(s) over budget"
                if over
                else f"geomean median {geo:.2f} ms over {len(medians)} benchmark(s)"
                if geo is not None
                else "no timings"
            ),
            # Only report a headline time when every benchmark completed;
            # a geomean over the survivors would flatter a candidate that timed out.
            metrics={
                "geomean_median_ms": round(geo, 4) if geo and not failed else None,
                "completed": len(results) - len(failed),
                "total": len(results),
            },
            benchmarks=results,
            logs="\n".join(logs)[-3000:],
        )
