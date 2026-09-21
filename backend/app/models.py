from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    instagram_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    leads: Mapped[list["Lead"]] = relationship(back_populates="company")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="company")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    intent_type: Mapped[str] = mapped_column(String(64), index=True)
    intent_strength: Mapped[str] = mapped_column(String(16), index=True)
    campaign_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geography: Mapped[str | None] = mapped_column(String(80), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_url: Mapped[str] = mapped_column(String(800))
    source_platform: Mapped[str] = mapped_column(String(64), index=True)
    evidence: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(String(400))
    score: Mapped[int] = mapped_column(Integer, default=0)
    score_breakdown: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    outreach_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality: Mapped[str] = mapped_column(String(32), default="unset", index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    critique: Mapped[str] = mapped_column(Text, default="")
    similar_cases: Mapped[str] = mapped_column(Text, default="[]")

    company: Mapped[Company | None] = relationship(back_populates="leads")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="lead")
    feedback: Mapped[list["Feedback"]] = relationship(back_populates="lead")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_status: Mapped[str] = mapped_column(String(32), default="unverified")
    source_url: Mapped[str] = mapped_column(String(800))
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company: Mapped[Company | None] = relationship(back_populates="contacts")
    lead: Mapped[Lead | None] = relationship(back_populates="contacts")


class CrawlPage(Base):
    __tablename__ = "crawl_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(800), unique=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(String(400), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    human_label: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lead: Mapped[Lead] = relationship(back_populates="feedback")


class RagMemory(Base):
    """Decision memory. ponytail: bag-of-words retrieve; pgvector if paraphrases leak."""

    __tablename__ = "rag_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(64), default="")
    intent_type: Mapped[str] = mapped_column(String(64), default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    human_label: Mapped[str] = mapped_column(String(16), default="")
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_text: Mapped[str] = mapped_column(Text)
    rule_type: Mapped[str] = mapped_column(String(32), default="classifier")
    source: Mapped[str] = mapped_column(String(64), default="seed")
    confidence: Mapped[int] = mapped_column(Integer, default=80)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    pages_seen: Mapped[int] = mapped_column(Integer, default=0)
    keyword_hits: Mapped[int] = mapped_column(Integer, default=0)
    leads_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
