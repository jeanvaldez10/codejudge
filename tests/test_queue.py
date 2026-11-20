from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from codejudge.db import SubmissionRow, claim_next, requeue_stale, session_scope, utcnow


def _enqueue(n: int) -> None:
    with session_scope() as s:
        for _ in range(n):
            s.add(SubmissionRow(task_id="t", task_spec={}, request={"candidates": []}))


def test_each_submission_claimed_exactly_once():
    _enqueue(20)

    def worker(i: int) -> list[str]:
        got = []
        while True:
            with session_scope() as s:
                row = claim_next(s, f"w{i}")
                if row is None:
                    return got
                got.append(row.id)

    with ThreadPoolExecutor(4) as pool:
        claimed = [x for xs in pool.map(worker, range(4)) for x in xs]
    assert len(claimed) == 20 and len(set(claimed)) == 20


def test_stale_running_jobs_are_requeued():
    _enqueue(1)
    with session_scope() as s:
        row = claim_next(s, "dead-worker")
        assert row is not None
        row.started_at = utcnow() - timedelta(hours=2)
    with session_scope() as s:
        assert requeue_stale(s) == 1
        assert claim_next(s, "alive") is not None
