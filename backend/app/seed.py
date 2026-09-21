from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, Contact, CrawlPage, Lead
from app.pipeline.outreach import draft_outreach


def seed_if_empty(db: Session) -> None:
    count = db.scalar(select(func.count()).select_from(Lead)) or 0
    if count:
        return
    now = datetime.utcnow()
    samples = _samples(now)
    for item in samples:
        company = Company(**item["company"])
        db.add(company)
        db.flush()
        page = item.get("page")
        if page:
            db.add(CrawlPage(**page))
        lead = Lead(company=company, **item["lead"])
        db.add(lead)
        db.flush()
        lead.outreach_draft = draft_outreach(lead)
        for contact in item.get("contacts", []):
            db.add(Contact(company=company, lead=lead, **contact))
    db.commit()


def _samples(now: datetime) -> list[dict]:
    return [
        {
            "company": {
                "name": "Lumora Beauty",
                "domain": "lumorabeauty.in",
                "industry": "beauty",
                "country": "India",
                "city": "Mumbai",
                "website": "https://lumorabeauty.in",
                "instagram_url": "https://instagram.com/lumorabeauty",
            },
            "lead": {
                "intent_type": "LOOKING_FOR_CREATORS",
                "intent_strength": "high",
                "campaign_type": "product_launch",
                "geography": "India",
                "industry": "beauty",
                "urgency": "high",
                "source_url": "fixture://lumora-beauty",
                "source_platform": "reddit",
                "evidence": "We are looking for Indian beauty creators for our upcoming launch.",
                "summary": "Lumora Beauty is looking for Indian beauty creators for a serum launch.",
                "score": 100,
                "score_breakdown": json.dumps(
                    [
                        "Explicitly looking for influencers/creators  +40",
                        "Campaign timing mentioned  +20",
                        "Product launch  +15",
                        "Specific creator niche  +15",
                        "Specific geography  +10",
                    ]
                ),
                "status": "new",
                "discovered_at": now - timedelta(hours=3),
            },
            "page": {
                "url": "fixture://lumora-beauty",
                "domain": "reddit.com",
                "title": "Looking for Indian beauty creators — Lumora launch",
                "text": (
                    "Hi r/IndianSkincareAddicts — Meera Shah, Head of Marketing at Lumora Beauty. "
                    "We are looking for Indian beauty creators for our upcoming launch. "
                    "Need 15 mid-tier Mumbai and Bengaluru skincare voices in October. "
                    "Campaign brief: niacinamide serum, paid + gifting. "
                    "Contact meera.shah@lumorabeauty.in if you have a roster."
                ),
                "content_hash": "seed-lumora",
            },
            "contacts": [
                {
                    "name": "Meera Shah",
                    "job_title": "Head of Marketing",
                    "email": "meera.shah@lumorabeauty.in",
                    "email_status": "mx_ok",
                    "source_url": "fixture://lumora-beauty",
                }
            ],
        },
        {
            "company": {
                "name": "FoldPay",
                "domain": "foldpay.app",
                "industry": "fintech",
                "country": "India",
                "city": "Bengaluru",
                "website": "https://foldpay.app",
            },
            "lead": {
                "intent_type": "NEEDS_UGC",
                "intent_strength": "high",
                "campaign_type": "ugc",
                "geography": "Bengaluru",
                "industry": "fintech",
                "urgency": "medium",
                "source_url": "fixture://foldpay-ugc",
                "source_platform": "forum",
                "evidence": "Need UGC creators for an upcoming campaign around our UPI rewards app.",
                "summary": "FoldPay needs UGC creators for a UPI rewards campaign.",
                "score": 90,
                "score_breakdown": json.dumps(
                    [
                        "Explicitly looking for influencers/creators  +40",
                        "Campaign timing mentioned  +20",
                        "Specific creator niche  +15",
                        "Specific geography  +10",
                        "Previous creator activity  +10",
                    ]
                ),
                "status": "new",
                "discovered_at": now - timedelta(hours=8),
            },
            "page": {
                "url": "fixture://foldpay-ugc",
                "domain": "indiamicro.in",
                "title": "FoldPay looking for UGC",
                "text": (
                    "FoldPay is here with a short brief. Need UGC creators for an upcoming campaign "
                    "around our UPI rewards app. We already work with a few fintech reviewers and want "
                    "raw phone-screen walkthroughs. Arjun Mehta, Marketing Lead — arjun@foldpay.app"
                ),
                "content_hash": "seed-foldpay",
            },
        },
        {
            "company": {
                "name": "Nimbus Foods",
                "domain": "nimbusfoods.co",
                "industry": "food",
                "country": "India",
                "city": "Delhi",
                "website": "https://nimbusfoods.co",
            },
            "lead": {
                "intent_type": "NEEDS_INFLUENCER_AGENCY",
                "intent_strength": "high",
                "campaign_type": "creator_campaign",
                "geography": "Delhi",
                "industry": "food",
                "urgency": "high",
                "source_url": "fixture://nimbus-agency",
                "source_platform": "x",
                "evidence": "Does anyone know a good influencer marketing agency for a snacks brand in Delhi?",
                "summary": "Nimbus Foods is asking for an influencer marketing agency.",
                "score": 95,
                "score_breakdown": json.dumps(
                    [
                        "Explicitly looking for an agency  +40",
                        "Campaign timing mentioned  +20",
                        "Specific creator niche  +15",
                        "Specific geography  +10",
                    ]
                ),
                "status": "reviewing",
                "discovered_at": now - timedelta(days=1),
            },
            "page": {
                "url": "fixture://nimbus-agency",
                "domain": "x.com",
                "title": "Agency rec for snacks brand",
                "text": (
                    "Kabir Anand, Founder at Nimbus Foods. Does anyone know a good influencer "
                    "marketing agency for a snacks brand in Delhi? We need 30 food creators this month. "
                    "kabir@nimbusfoods.co"
                ),
                "content_hash": "seed-nimbus",
            },
        },
        {
            "company": {
                "name": "Kala Thread",
                "domain": "kalathread.com",
                "industry": "fashion",
                "country": "India",
                "city": "Jaipur",
                "website": "https://kalathread.com",
            },
            "lead": {
                "intent_type": "BRAND_AMBASSADOR",
                "intent_strength": "medium",
                "campaign_type": "brand_ambassador",
                "geography": "Jaipur",
                "industry": "fashion",
                "urgency": "low",
                "source_url": "fixture://kala-ambassadors",
                "source_platform": "company_site",
                "evidence": "Looking for brand ambassadors who can wear our handloom jackets through winter.",
                "summary": "Kala Thread is recruiting brand ambassadors for handloom jackets.",
                "score": 65,
                "score_breakdown": json.dumps(
                    [
                        "Explicitly looking for influencers/creators  +40",
                        "Specific creator niche  +15",
                        "Specific geography  +10",
                    ]
                ),
                "status": "new",
                "discovered_at": now - timedelta(days=2),
            },
            "page": {
                "url": "fixture://kala-ambassadors",
                "domain": "kalathread.com",
                "title": "Ambassador programme",
                "text": (
                    "Kala Thread is looking for brand ambassadors who can wear our handloom jackets "
                    "through winter. Apply via creators@kalathread.com. Brand Manager: Rhea Kapoor."
                ),
                "content_hash": "seed-kala",
            },
        },
        {
            "company": {
                "name": "Veda Wellness",
                "domain": "vedawellness.in",
                "industry": "wellness",
                "country": "India",
                "city": "Pune",
                "website": "https://vedawellness.in",
            },
            "lead": {
                "intent_type": "HIRING_INFLUENCER_MARKETING",
                "intent_strength": "medium",
                "campaign_type": "hiring",
                "geography": "Pune",
                "industry": "wellness",
                "urgency": "medium",
                "source_url": "fixture://veda-hiring",
                "source_platform": "job_board",
                "evidence": "Hiring someone to manage influencer marketing for our Ayurveda drops.",
                "summary": "Veda Wellness is hiring an influencer marketing manager.",
                "score": 75,
                "score_breakdown": json.dumps(
                    [
                        "Marketing hiring  +10",
                        "Specific creator niche  +15",
                        "Specific geography  +10",
                        "Campaign timing mentioned  +20",
                        "Previous creator activity  +10",
                    ]
                ),
                "status": "new",
                "discovered_at": now - timedelta(days=3),
            },
            "page": {
                "url": "fixture://veda-hiring",
                "domain": "wellfound.com",
                "title": "Influencer Marketing Manager — Veda Wellness",
                "text": (
                    "Veda Wellness is hiring someone to manage influencer marketing for our Ayurveda drops. "
                    "Role sits with the CMO in Pune. We already work with a few wellness creators and want "
                    "the programme in-house by Q4. Apply: talent@vedawellness.in"
                ),
                "content_hash": "seed-veda",
            },
        },
        {
            "company": {
                "name": "Orbit Desk",
                "domain": "orbitdesk.com",
                "industry": "saas",
                "country": "India",
                "city": "Bengaluru",
                "website": "https://orbitdesk.com",
            },
            "lead": {
                "intent_type": "PRODUCT_LAUNCH",
                "intent_strength": "high",
                "campaign_type": "product_launch",
                "geography": "India",
                "industry": "saas",
                "urgency": "high",
                "source_url": "fixture://orbit-launch",
                "source_platform": "news",
                "evidence": "Looking for creators to promote our app during the India launch next week.",
                "summary": "Orbit Desk wants creators for an India app launch.",
                "score": 100,
                "score_breakdown": json.dumps(
                    [
                        "Explicitly looking for influencers/creators  +40",
                        "Campaign timing mentioned  +20",
                        "Product launch  +15",
                        "Specific creator niche  +15",
                        "Specific geography  +10",
                    ]
                ),
                "status": "qualified",
                "discovered_at": now - timedelta(hours=20),
            },
            "page": {
                "url": "fixture://orbit-launch",
                "domain": "inc42.com",
                "title": "Orbit Desk seeks creators for India launch",
                "text": (
                    "Orbit Desk is looking for creators to promote our app during the India launch next week. "
                    "Need LinkedIn and YouTube SaaS voices. Priya Nair, CMO — priya.nair@orbitdesk.com"
                ),
                "content_hash": "seed-orbit",
            },
        },
        {
            "company": {
                "name": "Saffron Loom",
                "domain": "saffronloom.in",
                "industry": "jewellery",
                "country": "India",
                "city": "Jaipur",
                "website": "https://saffronloom.in",
            },
            "lead": {
                "intent_type": "LOOKING_FOR_INFLUENCERS",
                "intent_strength": "high",
                "campaign_type": "creator_campaign",
                "geography": "Jaipur",
                "industry": "jewellery",
                "urgency": "medium",
                "source_url": "fixture://saffron-loom",
                "source_platform": "forum",
                "evidence": "Need Indian jewellery influencers who can shoot bridal sets in Jaipur this month.",
                "summary": "Saffron Loom needs jewellery influencers for bridal sets.",
                "score": 85,
                "score_breakdown": json.dumps(
                    [
                        "Explicitly looking for influencers/creators  +40",
                        "Campaign timing mentioned  +20",
                        "Specific creator niche  +15",
                        "Specific geography  +10",
                    ]
                ),
                "status": "new",
                "discovered_at": now - timedelta(hours=30),
            },
            "page": {
                "url": "fixture://saffron-loom",
                "domain": "wedmegood.com",
                "title": "Bridal jewellery creators wanted",
                "text": (
                    "Saffron Loom here. Need Indian jewellery influencers who can shoot bridal sets "
                    "in Jaipur this month. Write to campaigns@saffronloom.in"
                ),
                "content_hash": "seed-saffron",
            },
        },
        {
            "company": {
                "name": "Pulp Daily",
                "domain": "pulpdaily.co",
                "industry": "food",
                "country": "India",
                "city": "Mumbai",
                "website": "https://pulpdaily.co",
            },
            "lead": {
                "intent_type": "ASKING_FOR_RECOMMENDATIONS",
                "intent_strength": "medium",
                "campaign_type": "creator_campaign",
                "geography": "Mumbai",
                "industry": "food",
                "urgency": "low",
                "source_url": "fixture://pulp-recommend",
                "source_platform": "reddit",
                "evidence": "Does anyone know micro food creators in Mumbai for a juice brand collab?",
                "summary": "Pulp Daily is asking for Mumbai food creator recommendations.",
                "score": 55,
                "score_breakdown": json.dumps(
                    [
                        "Explicitly looking for influencers/creators  +40",
                        "Specific creator niche  +15",
                    ]
                ),
                "status": "new",
                "discovered_at": now - timedelta(days=4),
            },
            "page": {
                "url": "fixture://pulp-recommend",
                "domain": "reddit.com",
                "title": "Micro food creators in Mumbai?",
                "text": (
                    "Pulp Daily — Does anyone know micro food creators in Mumbai for a juice brand collab? "
                    "Not looking for a huge agency, just names. hello@pulpdaily.co"
                ),
                "content_hash": "seed-pulp",
            },
        },
    ]
