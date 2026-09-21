from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Company, Contact, Lead, ScanJob
from app.pipeline.outreach import draft_outreach
from app.pipeline.run import discover_contacts_for_lead
from urllib.parse import urlparse

from app.providers.ai import is_agency_seller, is_india_target, is_target_brand
from app.pipeline.memory import record_feedback, record_quality
from app.pipeline.taxonomy import (
    CAMPAIGN_TYPES,
    COUNTRIES,
    FEEDBACK_LABELS,
    INDUSTRIES,
    INTENT_TYPES,
    LEAD_STATUSES,
    PLATFORMS,
    QUALITY_LABELS,
)
from app.providers.search import platform_from_url
from app.schemas import FeedbackIn, LeadOut, LeadQualityIn, LeadStatusIn, MetaOut, StatsOut

router = APIRouter()


def serialize_lead(lead: Lead) -> LeadOut:
    breakdown = []
    if lead.score_breakdown:
        try:
            breakdown = json.loads(lead.score_breakdown)
        except json.JSONDecodeError:
            breakdown = [lead.score_breakdown]
    return LeadOut(
        id=lead.id,
        company=lead.company,
        intent_type=lead.intent_type,
        intent_strength=lead.intent_strength,
        campaign_type=lead.campaign_type,
        geography=lead.geography,
        industry=lead.industry,
        urgency=lead.urgency,
        source_url=lead.source_url,
        source_platform=platform_from_url(lead.source_url) if lead.source_url.startswith("http") else lead.source_platform,
        evidence=lead.evidence,
        summary=lead.summary,
        score=lead.score,
        score_breakdown=breakdown,
        status=lead.status,
        outreach_draft=lead.outreach_draft,
        quality=getattr(lead, "quality", None) or "unset",
        reviewed_at=getattr(lead, "reviewed_at", None),
        discovered_at=lead.discovered_at,
        contacts=lead.contacts,
        confidence=getattr(lead, "confidence", 0) or 0,
        reasoning=getattr(lead, "reasoning", "") or "",
        critique=getattr(lead, "critique", "") or "",
        similar_cases=_similar(lead),
    )


def _similar(lead: Lead) -> list[dict]:
    raw = getattr(lead, "similar_cases", "") or "[]"
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _hide_agency_lead(lead: Lead) -> bool:
    name = lead.company.name if lead.company else ""
    hay = f"{lead.evidence} {lead.summary}"
    if is_agency_seller(hay, name, lead.source_url):
        return True
    website = lead.company.website if lead.company else None
    if website and lead.source_url.startswith("http"):
        src = urlparse(lead.source_url).netloc.lower().removeprefix("www.")
        site = urlparse(website).netloc.lower().removeprefix("www.")
        # ponytail: own homepage as the source is almost always an agency pitch
        if src and src == site and is_agency_seller(hay, name, lead.source_url):
            return True
    return False


def _is_brand_lead(lead: Lead) -> bool:
    name = lead.company.name if lead.company else ""
    industry = lead.industry or (lead.company.industry if lead.company else "") or ""
    return is_target_brand(f"{lead.evidence} {lead.summary}", name, industry, lead.source_url)


def _is_india_lead(lead: Lead) -> bool:
    name = lead.company.name if lead.company else ""
    geo = lead.geography or (lead.company.country if lead.company else "") or ""
    return is_india_target(f"{lead.evidence} {lead.summary}", lead.source_url, geo, name)


@router.get("/leads", response_model=list[LeadOut])
def list_leads(
    intent_type: str | None = None,
    country: str | None = None,
    industry: str | None = None,
    intent_strength: str | None = None,
    campaign_type: str | None = None,
    source: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    live_only: bool = False,
    quality: str | None = None,
    buyer: str | None = None,
    q: str | None = Query(default=None, description="Search company or evidence"),
    db: Session = Depends(get_db),
):
    stmt = select(Lead).options(selectinload(Lead.company), selectinload(Lead.contacts)).order_by(Lead.discovered_at.desc())
    if intent_type:
        stmt = stmt.where(Lead.intent_type == intent_type)
    if intent_strength:
        stmt = stmt.where(Lead.intent_strength == intent_strength)
    if campaign_type:
        stmt = stmt.where(Lead.campaign_type == campaign_type)
    if source:
        if source == "reddit":
            stmt = stmt.where((Lead.source_platform == "reddit") | Lead.source_url.contains("reddit.com"))
        else:
            stmt = stmt.where(Lead.source_platform == source)
    if status:
        stmt = stmt.where(Lead.status == status)
    else:
        stmt = stmt.where(Lead.status != "dismissed")
    if industry:
        stmt = stmt.where(Lead.industry == industry)
    if country:
        stmt = stmt.join(Company, isouter=True)
        stmt = stmt.where((Company.country == country) | (Lead.geography == country) | Lead.geography.contains(country))
    if since:
        stmt = stmt.where(Lead.discovered_at >= since)
    if live_only:
        stmt = stmt.where(~Lead.source_url.startswith("fixture://"))
    if quality:
        stmt = stmt.where(Lead.quality == quality)
    leads = [
        lead
        for lead in db.scalars(stmt).unique()
        if not _hide_agency_lead(lead)
        and _is_india_lead(lead)
        and (buyer != "brands" or _is_brand_lead(lead))
    ]
    if q:
        needle = q.lower()
        leads = [
            lead
            for lead in leads
            if needle in lead.evidence.lower()
            or needle in lead.summary.lower()
            or (lead.company and needle in lead.company.name.lower())
        ]
    return [serialize_lead(lead) for lead in leads]


@router.get("/leads/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.scalar(
        select(Lead).options(selectinload(Lead.company), selectinload(Lead.contacts)).where(Lead.id == lead_id)
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    return serialize_lead(lead)


@router.delete("/leads/{lead_id}")
def dismiss_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.status = "dismissed"
    record_quality(db, lead, "false_positive")
    db.commit()
    return {"ok": True}


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: int, body: LeadStatusIn, db: Session = Depends(get_db)):
    if body.status not in LEAD_STATUSES:
        raise HTTPException(400, f"status must be one of {LEAD_STATUSES}")
    lead = db.scalar(
        select(Lead).options(selectinload(Lead.company), selectinload(Lead.contacts)).where(Lead.id == lead_id)
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.status = body.status
    db.commit()
    db.refresh(lead)
    return serialize_lead(lead)


@router.patch("/leads/{lead_id}/quality", response_model=LeadOut)
def update_quality(lead_id: int, body: LeadQualityIn, db: Session = Depends(get_db)):
    if body.quality not in QUALITY_LABELS:
        raise HTTPException(400, f"quality must be one of {QUALITY_LABELS}")
    lead = db.scalar(
        select(Lead).options(selectinload(Lead.company), selectinload(Lead.contacts)).where(Lead.id == lead_id)
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.quality = body.quality
    lead.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if body.quality == "false_positive" and lead.status == "new":
        lead.status = "rejected"
    if body.quality in {"genuine", "shortlist"} and lead.status == "new":
        lead.status = "qualified"
    record_quality(db, lead, body.quality)
    db.commit()
    db.refresh(lead)
    return serialize_lead(lead)


@router.post("/leads/{lead_id}/feedback", response_model=LeadOut)
def leave_feedback(lead_id: int, body: FeedbackIn, db: Session = Depends(get_db)):
    lead = db.scalar(
        select(Lead).options(selectinload(Lead.company), selectinload(Lead.contacts)).where(Lead.id == lead_id)
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    try:
        record_feedback(db, lead, body.label, body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.refresh(lead)
    return serialize_lead(lead)


@router.post("/leads/{lead_id}/contacts", response_model=LeadOut)
def find_contacts(lead_id: int, db: Session = Depends(get_db)):
    lead = db.scalar(
        select(Lead).options(selectinload(Lead.company), selectinload(Lead.contacts)).where(Lead.id == lead_id)
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    discover_contacts_for_lead(db, lead)
    db.refresh(lead)
    return serialize_lead(lead)


@router.post("/leads/{lead_id}/outreach", response_model=LeadOut)
def make_outreach(lead_id: int, db: Session = Depends(get_db)):
    lead = db.scalar(
        select(Lead).options(selectinload(Lead.company), selectinload(Lead.contacts)).where(Lead.id == lead_id)
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    contact = lead.contacts[0] if lead.contacts else None
    lead.outreach_draft = draft_outreach(lead, contact)
    db.commit()
    db.refresh(lead)
    return serialize_lead(lead)


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)):
    last_scan = db.scalar(select(ScanJob).order_by(ScanJob.created_at.desc()))
    leads = db.scalar(select(func.count()).select_from(Lead)) or 0
    reviewed = db.scalar(select(func.count()).select_from(Lead).where(Lead.quality != "unset")) or 0
    genuine = db.scalar(select(func.count()).select_from(Lead).where(Lead.quality == "genuine")) or 0
    false_positive = db.scalar(select(func.count()).select_from(Lead).where(Lead.quality == "false_positive")) or 0
    with_email = (
        db.scalar(select(func.count(func.distinct(Contact.lead_id))).where(Contact.email.is_not(None))) or 0
    )
    return StatsOut(
        leads=leads,
        high_intent=db.scalar(select(func.count()).select_from(Lead).where(Lead.intent_strength == "high")) or 0,
        new_leads=db.scalar(select(func.count()).select_from(Lead).where(Lead.status == "new")) or 0,
        companies=db.scalar(select(func.count()).select_from(Company)) or 0,
        contacts=db.scalar(select(func.count()).select_from(Contact)) or 0,
        last_scan_at=last_scan.finished_at if last_scan else None,
        reviewed=reviewed,
        genuine=genuine,
        shortlist=db.scalar(select(func.count()).select_from(Lead).where(Lead.quality == "shortlist")) or 0,
        false_positive=false_positive,
        no_contact=db.scalar(select(func.count()).select_from(Lead).where(Lead.quality == "no_contact")) or 0,
        with_email=with_email,
        genuine_rate=round(100 * genuine / reviewed) if reviewed else 0,
        false_positive_rate=round(100 * false_positive / reviewed) if reviewed else 0,
        contact_rate=round(100 * with_email / leads) if leads else 0,
    )


@router.get("/meta", response_model=MetaOut)
def meta():
    return MetaOut(
        intent_types=INTENT_TYPES,
        strengths=["high", "medium", "low"],
        campaign_types=CAMPAIGN_TYPES,
        statuses=LEAD_STATUSES,
        platforms=PLATFORMS,
        industries=INDUSTRIES,
        countries=COUNTRIES,
        qualities=QUALITY_LABELS,
        feedback_labels=FEEDBACK_LABELS,
    )
