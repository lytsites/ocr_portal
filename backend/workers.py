from __future__ import annotations

import os
import signal
import time
from multiprocessing import Process

from db import (
    claim_next_job,
    init_db,
    mark_doc_finished_for_metrics,
    mark_doc_processing_start,
    requeue_processing_jobs,
    set_job_status,
    update_document_fields,
)
from processor import process_document
from settings import WORKER_COUNT, WORKER_IDLE_SLEEP_SEC


def worker_loop(worker_id: str) -> None:
    while True:
        job = claim_next_job(worker_id)
        if not job:
            time.sleep(float(WORKER_IDLE_SLEEP_SEC))
            continue
        doc_id = str(job["doc_id"])
        try:
            mark_doc_processing_start(doc_id)
            process_document(doc_id)
            set_job_status(doc_id, status="done")
            mark_doc_finished_for_metrics(doc_id, include_pages=True)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            update_document_fields(
                doc_id,
                status="error",
                stage="failed",
                processing_status="error",
                processing_finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                processing_error=err,
            )
            set_job_status(doc_id, status="error", error=err)
            mark_doc_finished_for_metrics(doc_id, include_pages=False)


def run_workers() -> None:
    init_db()
    requeue_processing_jobs()

    count = max(1, int(WORKER_COUNT))
    if count == 1:
        worker_loop("worker-1")
        return

    children: list[Process] = []
    for i in range(count):
        wid = f"worker-{i + 1}"
        p = Process(target=worker_loop, args=(wid,), daemon=False)
        p.start()
        children.append(p)
        print(f"started {wid} pid={p.pid}", flush=True)

    def _shutdown(_sig, _frame) -> None:
        for c in children:
            if c.is_alive():
                c.terminate()
        for c in children:
            c.join(timeout=5)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        alive = [c for c in children if c.is_alive()]
        if len(alive) != len(children):
            for c in children:
                if c.is_alive():
                    continue
                idx = children.index(c)
                wid = f"worker-{idx + 1}"
                np = Process(target=worker_loop, args=(wid,), daemon=False)
                np.start()
                children[idx] = np
                print(f"restarted {wid} pid={np.pid}", flush=True)
        time.sleep(1.0)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    run_workers()
