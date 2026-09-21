"""Redis live queue + Postgres durable jobs. 1000 search and 1000 ingest in flight."""

from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, create_engine, func, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings

SEARCH_KEY = "radar:search"
INGEST_KEY = "radar:ingest"
BATCH = 1000


class QueueBase(DeclarativeBase):
    pass


class SearchJob(QueueBase):
    __tablename__ = "search_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(Integer, index=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IngestJob(QueueBase):
    __tablename__ = "ingest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(Integer, index=True)
    url: Mapped[str] = mapped_column(String(800))
    title: Mapped[str] = mapped_column(String(400), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


_queue_engine = None
_QueueSession = None
_redis = None
_mem = {SEARCH_KEY: deque(), INGEST_KEY: deque()}
_mem_lock = threading.Lock()
_started = False
_memory_cache: tuple[float, list, list] = (0.0, [], [])


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def connect_queue() -> tuple[bool, str]:
    global _queue_engine, _QueueSession
    if _QueueSession is not None:
        return True, settings.queue_database_url
    try:
        engine = create_engine(settings.queue_database_url, pool_size=32, max_overflow=64, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        QueueBase.metadata.create_all(bind=engine)
        _queue_engine = engine
        _QueueSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        return True, settings.queue_database_url
    except Exception as exc:
        return False, str(exc)


def connect_redis() -> tuple[bool, str]:
    global _redis
    if _redis is not None:
        return True, settings.redis_url
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        client.ping()
        _redis = client
        return True, settings.redis_url
    except Exception as exc:
        return False, str(exc)


def queue_session() -> Session:
    if _QueueSession is None:
        ok, detail = connect_queue()
        if not ok:
            raise RuntimeError(detail)
    return _QueueSession()


def redis_ok() -> bool:
    ok, _ = connect_redis()
    return ok


def _push(key: str, ids: list[int]) -> None:
    if not ids:
        return
    if redis_ok():
        _redis.lpush(key, *[str(i) for i in ids])
        return
    with _mem_lock:
        _mem[key].extendleft(ids)


def _pop(key: str) -> int | None:
    if redis_ok():
        item = _redis.rpop(key)
        return int(item) if item else None
    with _mem_lock:
        return _mem[key].pop() if _mem[key] else None


def _ready_len(key: str) -> int:
    if redis_ok():
        return int(_redis.llen(key) or 0)
    with _mem_lock:
        return len(_mem[key])


def enqueue_scan(scan_id: int, queries: list[str], hits) -> int:
    connect_queue()
    connect_redis()
    db = queue_session()
    try:
        search_rows = [SearchJob(scan_id=scan_id, query=query, status="queued") for query in queries]
        db.add_all(search_rows)
        ingest_rows = [
            IngestJob(
                scan_id=scan_id,
                url=hit.url,
                title=hit.title or "",
                snippet=hit.snippet or "",
                platform=hit.platform or "",
                status="queued",
            )
            for hit in hits
        ]
        db.add_all(ingest_rows)
        db.commit()
        for row in search_rows:
            db.refresh(row)
        for row in ingest_rows:
            db.refresh(row)
        search_ids = [row.id for row in search_rows[:BATCH]]
        ingest_ids = [row.id for row in ingest_rows[:BATCH]]
        if search_ids:
            db.execute(update(SearchJob).where(SearchJob.id.in_(search_ids)).values(status="dispatched"))
        if ingest_ids:
            db.execute(update(IngestJob).where(IngestJob.id.in_(ingest_ids)).values(status="dispatched"))
        db.commit()
        _push(SEARCH_KEY, search_ids)
        _push(INGEST_KEY, ingest_ids)
        return len(search_rows) + len(ingest_rows)
    finally:
        db.close()


def refill(kind: str) -> int:
    key = SEARCH_KEY if kind == "search" else INGEST_KEY
    table = SearchJob if kind == "search" else IngestJob
    need = BATCH - _ready_len(key)
    if need <= 0:
        return 0
    db = queue_session()
    try:
        dialect = db.bind.dialect.name if db.bind is not None else ""
        if dialect == "postgresql":
            ids = list(
                db.execute(
                    text(
                        f"SELECT id FROM {table.__tablename__} WHERE status='queued' "
                        f"ORDER BY id FOR UPDATE SKIP LOCKED LIMIT :n"
                    ),
                    {"n": need},
                ).scalars()
            )
        else:
            ids = list(db.scalars(select(table.id).where(table.status == "queued").order_by(table.id).limit(need)))
        if not ids:
            return 0
        db.execute(update(table).where(table.id.in_(ids)).values(status="dispatched"))
        db.commit()
        _push(key, ids)
        return len(ids)
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()


def _mark(table, job_id: int, status: str, error: str | None = None) -> None:
    db = queue_session()
    try:
        db.execute(update(table).where(table.id == job_id).values(status=status, error=error))
        db.commit()
    finally:
        db.close()


def queue_busy() -> bool:
    try:
        db = queue_session()
        try:
            search = db.scalar(
                select(func.count()).select_from(SearchJob).where(SearchJob.status.in_(("queued", "dispatched", "running")))
            ) or 0
            ingest = db.scalar(
                select(func.count()).select_from(IngestJob).where(IngestJob.status.in_(("queued", "dispatched", "running")))
            ) or 0
            return int(search + ingest) > 0
        finally:
            db.close()
    except Exception:
        return False


def clear_pending() -> None:
    connect_queue()
    connect_redis()
    try:
        db = queue_session()
        try:
            db.execute(update(SearchJob).where(SearchJob.status.in_(("queued", "dispatched", "running"))).values(status="failed", error="superseded"))
            db.execute(update(IngestJob).where(IngestJob.status.in_(("queued", "dispatched", "running"))).values(status="failed", error="superseded"))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass
    if _redis is not None:
        try:
            _redis.delete(SEARCH_KEY, INGEST_KEY)
        except Exception:
            pass
    from app.db import SessionLocal
    from app.models import ScanJob

    sqlite = SessionLocal()
    try:
        live = sqlite.scalar(select(ScanJob).where(ScanJob.status.in_(("queued", "running"))).order_by(ScanJob.id.asc()))
        for job in sqlite.scalars(select(ScanJob).where(ScanJob.status.in_(("queued", "running")))):
            if live and job.id == live.id:
                job.status = "running"
                job.finished_at = None
                continue
            job.status = "done"
            job.error = job.error or "superseded — one continuous scan"
            job.finished_at = _now()
        sqlite.commit()
    except Exception:
        sqlite.rollback()
    finally:
        sqlite.close()


def open_left(scan_id: int) -> int:
    db = queue_session()
    try:
        search = db.scalar(select(func.count()).select_from(SearchJob).where(SearchJob.scan_id == scan_id, SearchJob.status.in_(("queued", "dispatched", "running")))) or 0
        ingest = db.scalar(select(func.count()).select_from(IngestJob).where(IngestJob.scan_id == scan_id, IngestJob.status.in_(("queued", "dispatched", "running")))) or 0
        return int(search + ingest)
    finally:
        db.close()


def _bump_scan(scan_id: int, pages: int = 0, hits: int = 0, leads: int = 0) -> None:
    from app.db import SessionLocal
    from app.models import ScanJob

    db = SessionLocal()
    try:
        job = db.get(ScanJob, scan_id)
        if not job:
            return
        job.pages_seen = (job.pages_seen or 0) + pages
        job.keyword_hits = (job.keyword_hits or 0) + hits
        job.leads_found = (job.leads_found or 0) + leads
        # perpetual scan stays running; leftovers from old jobs can still close
        db.commit()
    finally:
        db.close()


def _run_search(job_id: int) -> None:
    from app.providers.search import get_search_provider, searx_categories

    db = queue_session()
    try:
        row = db.get(SearchJob, job_id)
        if not row or row.status == "done":
            return
        row.status = "running"
        db.commit()
        query, scan_id = row.query, row.scan_id
    finally:
        db.close()
    try:
        time.sleep(settings.search_delay_seconds)
        search = get_search_provider()
        hits = search.search(query, limit=settings.scan_result_limit, categories=searx_categories(query))
        if hits:
            enqueue_ingest(scan_id, hits)
        _mark(SearchJob, job_id, "done")
    except Exception as exc:
        _mark(SearchJob, job_id, "failed", str(exc)[:400])
    _bump_scan(scan_id)


def enqueue_ingest(scan_id: int, hits) -> None:
    db = queue_session()
    try:
        rows = []
        for hit in hits:
            row = IngestJob(
                scan_id=scan_id,
                url=hit.url,
                title=getattr(hit, "title", "") or "",
                snippet=getattr(hit, "snippet", "") or "",
                platform=getattr(hit, "platform", "") or "",
                status="queued",
            )
            db.add(row)
            rows.append(row)
        db.commit()
        ids = []
        for row in rows:
            db.refresh(row)
            ids.append(row.id)
        take = ids[: max(0, BATCH - _ready_len(INGEST_KEY))]
        if take:
            db.execute(update(IngestJob).where(IngestJob.id.in_(take)).values(status="dispatched"))
            db.commit()
            _push(INGEST_KEY, take)
    finally:
        db.close()


def _run_ingest(job_id: int) -> None:
    from app.db import SessionLocal
    from app.pipeline.keyword_filter import directory_hit, keyword_hit
    from app.pipeline.run import _ingest_hit, prepare_page
    from app.providers.ai import classify_text
    from app.providers.email_check import EmailCheckProvider
    from app.providers.enrichment import PublicWebEnrichment
    from app.providers.search import SearchHit

    qdb = queue_session()
    try:
        row = qdb.get(IngestJob, job_id)
        if not row or row.status == "done":
            return
        row.status = "running"
        qdb.commit()
        hit = SearchHit(url=row.url, title=row.title, snippet=row.snippet, platform=row.platform)
        scan_id = row.scan_id
    finally:
        qdb.close()
    page = prepare_page(hit)
    if page is None:
        _mark(IngestJob, job_id, "done")
        _bump_scan(scan_id)
        return
    warm = SessionLocal()
    try:
        lessons, rules = _cached_memory(warm)
    finally:
        warm.close()
    classification = None
    if page and (keyword_hit(page.text) or directory_hit(page.url, page.text)):
        classification = classify_text(page.text, page.url, lessons, rules)
    db = SessionLocal()
    try:
        added, keyed, created = _ingest_hit(
            db,
            hit,
            set(),
            PublicWebEnrichment(),
            EmailCheckProvider(),
            lessons,
            rules,
            page=page,
            classification=classification,
        )
        _mark(IngestJob, job_id, "done")
        _bump_scan(scan_id, pages=added, hits=keyed, leads=created)
    except Exception as exc:
        _mark(IngestJob, job_id, "failed", str(exc)[:400])
        _bump_scan(scan_id)
    finally:
        db.close()


def _search_loop() -> None:
    # ponytail: 64 OS threads; asyncio would need async SearXNG across the board
    workers = min(settings.search_concurrency, 2)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="search") as pool:
        inflight: set = set()
        while True:
            try:
                refill("search")
            except Exception:
                time.sleep(1)
                continue
            while len(inflight) < workers:
                job_id = _pop(SEARCH_KEY)
                if job_id is None:
                    break
                inflight.add(pool.submit(_run_search, job_id))
            if not inflight:
                time.sleep(0.25)
                continue
            done, inflight = wait(inflight, return_when=FIRST_COMPLETED)
            for item in done:
                try:
                    item.result()
                except Exception:
                    pass


def _ingest_loop() -> None:
    # ponytail: crawl/Playwright dies at 1000 in-flight; 32 workers, 1000-job Redis backlog
    workers = min(settings.ingest_concurrency, 4)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ingest") as pool:
        inflight: set = set()
        while True:
            try:
                refill("ingest")
            except Exception:
                time.sleep(1)
                continue
            while len(inflight) < workers:
                job_id = _pop(INGEST_KEY)
                if job_id is None:
                    break
                inflight.add(pool.submit(_run_ingest, job_id))
            if not inflight:
                time.sleep(0.25)
                continue
            done, inflight = wait(inflight, return_when=FIRST_COMPLETED)
            for item in done:
                try:
                    item.result()
                except Exception:
                    pass


def start_queue_workers() -> None:
    global _started
    if _started:
        return
    connect_queue()
    connect_redis()
    threading.Thread(target=_search_loop, daemon=True, name="search-queue").start()
    threading.Thread(target=_ingest_loop, daemon=True, name="ingest-queue").start()
    _started = True


def _cached_memory(db):
    global _memory_cache
    from app.pipeline.memory import load_lessons, load_rules

    age, lessons, rules = _memory_cache
    if time.time() - age < 60:
        return lessons, rules
    lessons, rules = load_lessons(db), load_rules(db)
    _memory_cache = (time.time(), lessons, rules)
    return lessons, rules
