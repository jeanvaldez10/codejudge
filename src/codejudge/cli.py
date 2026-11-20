"""Command line interface.

    codejudge evaluate examples/interval-merge \
        -c "Model A=examples/interval-merge/candidates/model_a" \
        -c "Model B=examples/interval-merge/candidates/model_b" --format md
    codejudge serve      # REST API
    codejudge worker     # job runner (executes sandboxed evaluations)
"""

from __future__ import annotations

import argparse
import logging
import sys

from codejudge.models import StageResult


def _evaluate(args: argparse.Namespace) -> int:
    from codejudge.loader import load_candidate, load_task
    from codejudge.pipeline import evaluate
    from codejudge.report import redact_hidden, render_markdown
    from codejudge.sandbox import get_sandbox

    task = load_task(args.task)
    candidates = [load_candidate(c) for c in args.candidate]

    def progress(label: str, r: StageResult) -> None:
        print(f"  [{label}] {r.stage:<16} {r.status.value:<8} {r.summary}", file=sys.stderr)

    report = evaluate(
        task,
        candidates,
        get_sandbox(),
        selected_stages=args.stages.split(",") if args.stages else None,
        parallelism=args.parallel,
        progress=progress,
    )
    if args.public:
        report = redact_hidden(report)
    out = render_markdown(report) if args.format == "md" else report.model_dump_json(indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out)
    else:
        print(out)
    if args.fail_under is not None:
        best = max((c.scorecard.overall for c in report.candidates), default=0.0)
        return 0 if best >= args.fail_under else 1
    return 0


def _push_task(args: argparse.Namespace) -> int:
    import os

    import httpx

    from codejudge.loader import load_task

    task = load_task(args.task)
    headers = {}
    if token := os.environ.get("CODEJUDGE_API_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    r = httpx.put(
        f"{args.api.rstrip('/')}/api/tasks/{task.id}",
        json=task.model_dump(mode="json"),
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    print(f"registered task {task.id!r}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("codejudge.api.app:app", host=args.host, port=args.port)
    return 0


def _worker(args: argparse.Namespace) -> int:
    from codejudge.worker import run_forever

    run_forever(once=args.once)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(prog="codejudge")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("evaluate", help="evaluate candidates against a task locally")
    e.add_argument("task", help="task.yaml / task.json, or a directory containing task.yaml")
    e.add_argument("-c", "--candidate", action="append", required=True, help="LABEL=PATH[@MODEL]")
    e.add_argument("--format", choices=["md", "json"], default="md")
    e.add_argument("--stages", help="comma-separated subset of stages")
    e.add_argument("--parallel", type=int, default=2)
    e.add_argument("--public", action="store_true", help="redact hidden-test details")
    e.add_argument("-o", "--output")
    e.add_argument("--fail-under", type=float, help="exit 1 if best overall score is below this")
    e.set_defaults(fn=_evaluate)

    t = sub.add_parser("push-task", help="register/update a task on a CodeJudge server")
    t.add_argument("task")
    t.add_argument("--api", default="http://127.0.0.1:8000")
    t.set_defaults(fn=_push_task)

    s = sub.add_parser("serve", help="run the REST API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=_serve)

    w = sub.add_parser("worker", help="run the evaluation worker")
    w.add_argument("--once", action="store_true", help="process the queue once and exit")
    w.set_defaults(fn=_worker)

    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
