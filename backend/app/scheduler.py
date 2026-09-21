"""In-process scheduler. Scan + Reddit watch + one-shot backfill on boot."""

from __future__ import annotations

import threading
import time

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import ScanJob
from app.pipeline.run import backfill_unnamed_leads, run_reddit_watch, run_scan
from app.queue import clear_pending, queue_busy, start_queue_workers

_started = False


def start_scheduler() -> None:
    global _started
    if _started:
        return
    _started = True
    start_queue_workers()
    clear_pending()
    threading.Thread(target=_boot_backfill, daemon=True, name="lead-backfill").start()
    threading.Thread(target=_scan_loop, daemon=True, name="intent-scan").start()
    if settings.reddit_watch_minutes > 0:
        threading.Thread(target=_reddit_loop, args=(settings.reddit_watch_minutes,), daemon=True, name="reddit-watch").start()


def _boot_backfill() -> None:
    db = SessionLocal()
    try:
        backfill_unnamed_leads(db)
    except Exception:
        pass
    finally:
        db.close()


def live_scan(db, create: bool = False) -> ScanJob | None:
    _reap(db)
    job = db.scalar(select(ScanJob).where(ScanJob.status.in_(("queued", "running"))).order_by(ScanJob.id.asc()))
    if job:
        job.status = "running"
        job.finished_at = None
        db.commit()
        return job
    if not create:
        return None
    job = ScanJob(status="running", started_at=_now())
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


def _reap(db) -> None:
    rows = list(db.scalars(select(ScanJob).where(ScanJob.status.in_(("queued", "running"))).order_by(ScanJob.id.asc())))
    if not rows:
        return
    keep = rows[0]
    now = _now()
    for job in rows[1:]:
        job.status = "done"
        job.finished_at = now
        job.error = job.error or "superseded — one continuous scan"
    db.commit()
    keep.status = "running"
    keep.finished_at = None
    db.commit()


def _scan_loop() -> None:
    time.sleep(5)
    while True:
        db = SessionLocal()
        try:
            job = live_scan(db, create=True)
            if job and not queue_busy():
                run_scan(db, job)
        except Exception:
            pass
        finally:
            db.close()
        time.sleep(3)


def _reddit_loop(minutes: int) -> None:
    time.sleep(8)
    while True:
        db = SessionLocal()
        try:
            run_reddit_watch(db)
        except Exception:
            pass
        finally:
            db.close()
        time.sleep(max(minutes, 1) * 60)
