"""Local commands. Intended for cron on your machine, not a cloud worker.

    cd backend && .venv/bin/python -m app.cli scan
"""

from __future__ import annotations

import argparse

from app.db import Base, SessionLocal, engine, ensure_schema
from app.models import ScanJob
from app.pipeline.run import run_scan


def cmd_scan() -> int:
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        job = ScanJob(status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        run_scan(db, job)
        print(
            f"{job.status} queries={job.query_count} pages={job.pages_seen} "
            f"hits={job.keyword_hits} leads={job.leads_found}"
        )
        if job.error:
            print(job.error)
            return 1
        return 0
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Intent Radar local CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="Run one discovery pass")
    args = parser.parse_args()
    if args.command == "scan":
        raise SystemExit(cmd_scan())


if __name__ == "__main__":
    main()
