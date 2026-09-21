from datetime import datetime

from pydantic import BaseModel, Field


class ContactOut(BaseModel):
    id: int
    name: str | None
    job_title: str | None
    email: str | None
    email_status: str
    source_url: str
    discovered_at: datetime

    model_config = {"from_attributes": True}


class CompanyOut(BaseModel):
    id: int
    name: str
    domain: str | None
    industry: str | None
    country: str | None
    city: str | None
    website: str | None
    linkedin_url: str | None
    instagram_url: str | None

    model_config = {"from_attributes": True}


class LeadOut(BaseModel):
    id: int
    company: CompanyOut | None
    intent_type: str
    intent_strength: str
    campaign_type: str | None
    geography: str | None
    industry: str | None
    urgency: str | None
    source_url: str
    source_platform: str
    evidence: str
    summary: str
    score: int
    score_breakdown: list[str] = Field(default_factory=list)
    status: str
    outreach_draft: str | None
    quality: str = "unset"
    reviewed_at: datetime | None = None
    discovered_at: datetime
    contacts: list[ContactOut] = Field(default_factory=list)
    confidence: int = 0
    reasoning: str = ""
    critique: str = ""
    similar_cases: list[dict] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class LeadStatusIn(BaseModel):
    status: str


class LeadQualityIn(BaseModel):
    quality: str


class FeedbackIn(BaseModel):
    label: str
    reason: str = ""


class ScanOut(BaseModel):
    id: int
    status: str
    query_count: int
    pages_seen: int
    keyword_hits: int
    leads_found: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class StatsOut(BaseModel):
    leads: int
    high_intent: int
    new_leads: int
    companies: int
    contacts: int
    last_scan_at: datetime | None
    reviewed: int = 0
    genuine: int = 0
    shortlist: int = 0
    false_positive: int = 0
    no_contact: int = 0
    with_email: int = 0
    genuine_rate: int = 0
    false_positive_rate: int = 0
    contact_rate: int = 0


class ProviderStatus(BaseModel):
    name: str
    kind: str
    active: bool
    detail: str


class MetaOut(BaseModel):
    intent_types: list[str]
    strengths: list[str]
    campaign_types: list[str]
    statuses: list[str]
    platforms: list[str]
    industries: list[str]
    countries: list[str]
    qualities: list[str]
    feedback_labels: list[str] = Field(default_factory=list)
