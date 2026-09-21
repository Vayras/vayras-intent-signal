from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Company, Contact, CrawlPage, Lead, ScanJob
from urllib.parse import urlparse

from app.pipeline.crawl import is_social_host, page_from_hit, reddit_watch_hits
from app.pipeline.keyword_filter import directory_hit, keyword_hit
from app.pipeline.outreach import draft_outreach
from app.pipeline.queries import generate_queries
from app.pipeline.rss import rss_hits
from app.pipeline.score import score_lead
from app.pipeline.memory import (
    banned_names,
    load_lessons,
    load_rules,
    maybe_refresh_rules,
    pack_as_json,
    remembered_reject,
    retrieve_pack,
)
from app.providers.ai import Classification, classify_text, resolve_company_name
from app.providers.email_check import EmailCheckProvider
from app.providers.enrichment import PublicWebEnrichment, search_official_site
from app.providers.search import SearchHit, get_search_provider, platform_from_url, searx_categories
from app.queue import connect_queue, enqueue_scan


def run_scan(db: Session, job: ScanJob) -> ScanJob:
    job.status = "running"
    job.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    memory = load_lessons(db)
    rules = load_rules(db)
    queries = generate_queries(avoid=banned_names(memory))
    first = not job.query_count
    job.query_count = (job.query_count or 0) + len(queries)
    job.finished_at = None
    db.commit()

    ready, _ = connect_queue()
    seed_hits = (list(reddit_watch_hits()) + rss_hits()) if first else []
    if ready:
        try:
            enqueue_scan(job.id, queries, seed_hits)
            db.commit()
            return job
        except Exception as exc:
            job.error = f"queue enqueue failed: {exc}"
            db.commit()

    search = get_search_provider()
    enricher = PublicWebEnrichment()
    email_check = EmailCheckProvider()

    seen_urls: set[str] = set()
    found = 0
    pages = 0
    hits = 0

    try:
        for hit in seed_hits:
            added, keyed, created = _ingest_hit(db, hit, seen_urls, enricher, email_check, memory, rules)
            pages += added
            hits += keyed
            found += created

        for query in queries:
            if pages >= settings.scan_max_pages:
                break
            for hit in search.search(
                query, limit=settings.scan_result_limit, categories=searx_categories(query)
            ):
                if pages >= settings.scan_max_pages:
                    break
                added, keyed, created = _ingest_hit(db, hit, seen_urls, enricher, email_check, memory, rules)
                pages += added
                hits += keyed
                found += created

        job.pages_seen = (job.pages_seen or 0) + pages
        job.keyword_hits = (job.keyword_hits or 0) + hits
        job.leads_found = (job.leads_found or 0) + found
        db.commit()
        maybe_refresh_rules(db)
        return job
    except Exception as exc:
        job.error = str(exc)
        job.pages_seen = (job.pages_seen or 0) + pages
        job.keyword_hits = (job.keyword_hits or 0) + hits
        job.leads_found = (job.leads_found or 0) + found
        db.commit()
        raise


def run_reddit_watch(db: Session) -> int:
    enricher = PublicWebEnrichment()
    email_check = EmailCheckProvider()
    memory = load_lessons(db)
    rules = load_rules(db)
    seen: set[str] = set()
    found = 0
    for hit in reddit_watch_hits():
        _added, _keyed, created = _ingest_hit(db, hit, seen, enricher, email_check, memory, rules)
        found += created
    return found


def prepare_page(hit: SearchHit):
    if hit.url.startswith("fixture://") and not settings.demo_mode:
        return None
    if not hit.url.startswith("fixture://"):
        time.sleep(settings.crawl_delay_seconds)
    page = page_from_hit(hit)
    if page is None or len(page.text) < 40:
        return None
    return page


def _ingest_hit(
    db: Session,
    hit: SearchHit,
    seen_urls: set[str],
    enricher,
    email_check,
    memory=None,
    rules=None,
    page=None,
    classification=None,
) -> tuple[int, int, int]:
    if hit.url in seen_urls:
        return 0, 0, 0
    if hit.url.startswith("fixture://") and not settings.demo_mode:
        return 0, 0, 0
    seen_urls.add(hit.url)
    page = page or prepare_page(hit)
    if page is None:
        return 0, 0, 0
    seen_hash = db.scalar(
        select(CrawlPage.id).where(CrawlPage.content_hash == page.content_hash, CrawlPage.url != page.url)
    )
    _upsert_page(db, page)
    if seen_hash:
        return 1, 0, 0
    listed = directory_hit(page.url, page.text)
    if not keyword_hit(page.text) and not listed:
        return 1, 0, 0
    memory = memory or []
    rules = rules or []
    if remembered_reject(page.text, "", page.url, memory):
        return 1, 1, 0
    classification = classification or classify_text(page.text, page.url, memory, rules)
    if listed:
        classification = _promote_directory(classification, page)
    if not classification.is_lead or not classification.evidence:
        return 1, 1, 0
    if _duplicate_lead(db, page.url, classification.evidence):
        return 1, 1, 0
    score, breakdown = score_lead(page.text, classification)
    pack = retrieve_pack(page.text, memory, rules)
    company = _upsert_company(db, classification, page)
    platform = platform_from_url(page.url) if page.url.startswith("http") else (page.platform or hit.platform)
    lead = Lead(
        company=company,
        intent_type=classification.intent_type,
        intent_strength=classification.intent_strength,
        campaign_type=classification.campaign_type or None,
        geography=classification.geography or None,
        industry=classification.industry or (company.industry if company else None),
        urgency=classification.urgency or None,
        source_url=page.url,
        source_platform=platform,
        evidence=classification.evidence,
        summary=_summary(classification, company),
        score=score,
        score_breakdown=json.dumps(breakdown),
        status="new",
        confidence=int(round((classification.confidence or 0) * 100)),
        reasoning=classification.reasoning or "",
        critique=classification.critique or "",
        similar_cases=json.dumps(pack_as_json(pack)),
    )
    db.add(lead)
    db.flush()
    lead.outreach_draft = draft_outreach(lead)
    db.commit()
    discover_contacts_for_lead(db, lead)
    db.refresh(lead)
    lead.summary = _summary(classification, lead.company)
    lead.outreach_draft = draft_outreach(lead)
    db.commit()
    return 1, 1, 1


def _promote_directory(prior: Classification, page) -> Classification:
    from app.providers.ai import WEAK_BRAND_NAMES

    name = (prior.company or "").strip() or resolve_company_name(page.text, page.url)
    if not name or name in WEAK_BRAND_NAMES:
        return prior
    hay = page.text.lower()
    industry = prior.industry or ("beauty" if any(word in hay for word in ("beauty", "skincare", "makeup", "cosmetics")) else "d2c")
    evidence = prior.evidence or page.title or page.text[:240]
    if prior.is_lead and evidence:
        return prior
    return Classification(
        is_lead=True,
        intent_type=prior.intent_type or "CREATOR_CAMPAIGN",
        intent_strength=prior.intent_strength or "low",
        campaign_type=prior.campaign_type or "always_on",
        geography=prior.geography or "India",
        urgency=prior.urgency or "low",
        company=name,
        industry=industry,
        evidence=evidence,
        provider=f"{prior.provider}+directory",
        confidence=max(prior.confidence or 0, 0.55),
        reasoning=prior.reasoning or "Indian beauty/D2C or LinkedIn company that can use influencer marketing.",
        critique=prior.critique,
    )


def discover_contacts_for_lead(db: Session, lead: Lead) -> list[Contact]:
    page = db.scalar(select(CrawlPage).where(CrawlPage.url == lead.source_url))
    text = page.text if page else lead.evidence
    company = lead.company
    result = PublicWebEnrichment().enrich(
        text=text,
        source_url=lead.source_url,
        company_name=company.name if company else None,
        website=company.website if company else None,
        domain=company.domain if company else None,
    )
    if company:
        _apply_company_facts(company, result.facts)
    elif result.facts.name or result.facts.website or result.facts.domain:
        company = Company(
            name=(result.facts.name or (lead.summary.split(" is ")[0] if lead.summary else "Unknown company"))[:200],
            domain=result.facts.domain,
            website=result.facts.website,
            linkedin_url=result.facts.linkedin_url,
            instagram_url=result.facts.instagram_url,
            city=result.facts.city,
            country="India",
            industry=result.facts.industry or lead.industry,
        )
        db.add(company)
        db.flush()
        lead.company = company

    email_check = EmailCheckProvider()
    created: list[Contact] = []
    existing = {contact.email for contact in lead.contacts if contact.email}
    existing_names = {(contact.name or "", contact.job_title or "") for contact in lead.contacts}
    for found_contact in result.contacts:
        if found_contact.email and found_contact.email in existing:
            continue
        if not found_contact.email and (found_contact.name or "", found_contact.job_title or "") in existing_names:
            continue
        contact = Contact(
            company=company,
            lead=lead,
            name=found_contact.name,
            job_title=found_contact.job_title,
            email=found_contact.email,
            email_status=email_check.check(found_contact.email),
            source_url=found_contact.source_url,
        )
        db.add(contact)
        created.append(contact)
    db.commit()
    db.refresh(lead)
    return created


def _apply_company_facts(company: Company, facts) -> None:
    if facts.name and (not company.name or company.name.startswith("Unknown")):
        company.name = facts.name
    company.website = company.website or facts.website
    company.domain = company.domain or facts.domain
    company.linkedin_url = company.linkedin_url or facts.linkedin_url
    company.instagram_url = company.instagram_url or facts.instagram_url
    company.city = company.city or facts.city
    if getattr(facts, "industry", None) and not company.industry:
        company.industry = facts.industry


def _upsert_page(db: Session, page) -> CrawlPage:
    existing = db.scalar(select(CrawlPage).where(CrawlPage.url == page.url))
    if existing:
        existing.title = page.title
        existing.text = page.text
        existing.content_hash = page.content_hash
        existing.domain = page.domain
        return existing
    row = CrawlPage(
        url=page.url,
        domain=page.domain,
        title=page.title,
        text=page.text,
        content_hash=page.content_hash,
    )
    db.add(row)
    return row


def backfill_unnamed_leads(db: Session, limit: int = 40) -> int:
    leads = list(db.scalars(select(Lead).order_by(Lead.id.desc()).limit(limit)))
    n = 0
    for lead in leads:
        named = bool(lead.company and not lead.company.name.startswith("Unknown"))
        if named and lead.contacts:
            continue
        page = db.scalar(select(CrawlPage).where(CrawlPage.url == lead.source_url))
        text = page.text if page else (lead.evidence or "")
        if not named:
            name = resolve_company_name(text, lead.source_url)
            if name:
                existing = db.scalar(select(Company).where(Company.name == name))
                if lead.company:
                    lead.company.name = name
                elif existing:
                    lead.company = existing
                else:
                    company = Company(name=name, country="India")
                    db.add(company)
                    db.flush()
                    lead.company = company
        discover_contacts_for_lead(db, lead)
        if lead.company:
            lead.summary = _summary_from_lead(lead)
            lead.outreach_draft = draft_outreach(lead)
        n += 1
    db.commit()
    return n


def _upsert_company(db: Session, classification, page) -> Company | None:
    name = (classification.company or "").strip() or resolve_company_name(page.text, page.url)
    if not name:
        return None
    existing = db.scalar(select(Company).where(Company.name == name))
    website = None
    domain = None
    if page.url.startswith("http") and not is_social_host(page.domain):
        parsed = urlparse(page.url)
        website = f"{parsed.scheme}://{parsed.netloc}"
        domain = parsed.netloc
    official = search_official_site(name)
    if official:
        website = official
        domain = urlparse(official).netloc
    if existing:
        if classification.industry and not existing.industry:
            existing.industry = classification.industry
        existing.website = existing.website or website
        existing.domain = existing.domain or domain
        return existing
    company = Company(
        name=name,
        domain=domain,
        industry=classification.industry or None,
        country="India",
        website=website,
    )
    db.add(company)
    db.flush()
    return company


def _duplicate_lead(db: Session, url: str, evidence: str) -> bool:
    existing = db.scalar(select(Lead).where(Lead.source_url == url))
    if existing:
        return True
    return db.scalar(select(Lead).where(Lead.evidence == evidence)) is not None


def _summary(classification, company: Company | None) -> str:
    who = company.name if company else (classification.company or "A brand")
    need = classification.intent_type.replace("_", " ").lower()
    geo = classification.geography or "India"
    return f"{who} is {need} in {geo}."


def _summary_from_lead(lead: Lead) -> str:
    who = lead.company.name if lead.company else "A brand"
    need = lead.intent_type.replace("_", " ").lower()
    geo = lead.geography or "India"
    return f"{who} is {need} in {geo}."


_ = SearchHit
