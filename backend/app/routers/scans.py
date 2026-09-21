from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ScanJob
from app.providers.ai import get_ai_provider
from app.providers.email_check import EmailCheckProvider
from app.providers.enrichment import PublicWebEnrichment
from app.providers.search import get_search_provider
from app.queue import connect_queue, connect_redis
from app.scheduler import live_scan
from app.schemas import ProviderStatus, ScanOut

router = APIRouter()


@router.post("/scans", response_model=ScanOut)
def start_scan(db: Session = Depends(get_db)):
    return live_scan(db, create=True)


@router.get("/scans", response_model=list[ScanOut])
def list_scans(db: Session = Depends(get_db)):
    return list(db.scalars(select(ScanJob).where(ScanJob.status.in_(("queued", "running"))).order_by(ScanJob.id.asc())))


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(scan_id: int, db: Session = Depends(get_db)):
    job = db.get(ScanJob, scan_id)
    if not job:
        from fastapi import HTTPException

        raise HTTPException(404, "Scan not found")
    return job


@router.get("/providers", response_model=list[ProviderStatus])
def providers():
    search = get_search_provider()
    ai = get_ai_provider()
    search_ok, search_detail = search.status()
    ai_ok, ai_detail = ai.status()
    redis_ok, redis_detail = connect_redis()
    pg_ok, pg_detail = connect_queue()
    return [
        ProviderStatus(name=search.name, kind="SearchProvider", active=search_ok, detail=search_detail),
        ProviderStatus(name=ai.name, kind="AIProvider", active=ai_ok, detail=ai_detail),
        ProviderStatus(
            name=PublicWebEnrichment.name,
            kind="EnrichmentProvider",
            active=True,
            detail="Public page text only. Paid enrichers can plug in later.",
        ),
        ProviderStatus(
            name=EmailCheckProvider.name,
            kind="EmailProvider",
            active=True,
            detail="DNS/MX then SMTP RCPT for emails found on public pages. Sending stays off.",
        ),
        ProviderStatus(name="Redis", kind="SearchQueue", active=redis_ok, detail=redis_detail),
        ProviderStatus(name="PostgreSQL", kind="IngestQueue", active=pg_ok, detail=pg_detail),
    ]
