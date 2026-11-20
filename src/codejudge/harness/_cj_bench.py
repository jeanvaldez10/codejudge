"""Benchmark the candidate entrypoint and write results to $CJ_OUT/bench.json.

Usage: python _cj_bench.py <config.json>
config: {"module": ..., "entrypoint": ..., "benchmarks": [{name, setup, repeat, warmup}]}

Benchmark ``setup`` code is authored by the task owner (trusted). Arguments
are deep-copied before every call so a candidate that mutates its input in
place cannot make later repetitions artificially cheap.
"""

import copy
import gc
import importlib
import json
import os
import statistics
import sys
import time
import tracemalloc

OUT = os.environ["CJ_OUT"]


def _write(results):
    tmp = os.path.join(OUT, "bench.json.tmp")
    with open(tmp, "w") as fh:
        json.dump({"benchmarks": results}, fh)
    os.replace(tmp, os.path.join(OUT, "bench.json"))


def main() -> int:
    with open(sys.argv[1]) as fh:
        config = json.load(fh)
    sys.path.insert(0, os.getcwd())
    results = []
    try:
        fn = getattr(importlib.import_module(config["module"]), config["entrypoint"])
    except Exception as exc:
        for b in config["benchmarks"]:
            results.append({"name": b["name"], "ok": False, "error": f"import failed: {exc!r}"})
        _write(results)
        return 0
    for b in config["benchmarks"]:
        record = {"name": b["name"], "ok": False}
        try:
            ns = {}
            exec(b["setup"], ns)  # trusted task-author code
            args = tuple(ns.get("args", ()))
            kwargs = dict(ns.get("kwargs", {}))
            for _ in range(b.get("warmup", 1)):
                fn(*copy.deepcopy(args), **copy.deepcopy(kwargs))
            times = []
            for _ in range(b.get("repeat", 5)):
                a, k = copy.deepcopy(args), copy.deepcopy(kwargs)
                gc.collect()
                gc.disable()
                t0 = time.perf_counter_ns()
                fn(*a, **k)
                t1 = time.perf_counter_ns()
                gc.enable()
                times.append((t1 - t0) / 1e6)
            a, k = copy.deepcopy(args), copy.deepcopy(kwargs)
            tracemalloc.start()
            fn(*a, **k)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            times.sort()
            p95_idx = min(len(times) - 1, max(0, round(0.95 * (len(times) - 1))))
            record.update(
                ok=True,
                median_ms=statistics.median(times),
                p95_ms=times[p95_idx],
                min_ms=times[0],
                peak_memory_kb=peak / 1024,
            )
        except BaseException as exc:
            gc.enable()
            record["error"] = f"{type(exc).__name__}: {exc}"[:2000]
        results.append(record)
        _write(results)  # incremental, so a timeout keeps finished benchmarks
    return 0


if __name__ == "__main__":
    sys.exit(main())
