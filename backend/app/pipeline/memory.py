"""Reflective RAG. Past judgements + rules retrieved before classify."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Feedback, Lead, RagMemory, Rule
from app.pipeline.taxonomy import DEFAULT_RULES, FEEDBACK_LABELS

# ponytail: bag-of-words recall; pgvector if paraphrases start leaking through
_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {
    "the",
    "and",
    "for",
    "are",
    "our",
    "you",
    "your",
    "this",
    "that",
    "with",
    "from",
    "looking",
    "need",
    "want",
    "seeking",
    "influencer",
    "influencers",
    "creator",
    "creators",
    "ugc",
    "brand",
    "please",
    "anyone",
    "india",
    "indian",
    "marketing",
    "campaign",
    "http",
    "https",
    "www",
    "com",
    "html",
}
_WEAK = {"unknown company", "unknown", "groups", "brand", "brands"}
_LABEL_QUALITY = {
    "correct_lead": "genuine",
    "false_positive": "false_positive",
    "duplicate": "false_positive",
}


@dataclass(frozen=True)
class Lesson:
    verdict: str
    company: str
    evidence: str
    source_url: str
    label: str
    memory_type: str = "case"


@dataclass
class MemoryPack:
    keep: list[Lesson] = field(default_factory=list)
    reject: list[Lesson] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)

    def all_lessons(self) -> list[Lesson]:
        return [*self.keep, *self.reject]


def tokens(text: str) -> frozenset[str]:
    return frozenset(word for word in _WORD.findall(text.lower()) if word not in _STOP)


def recall(needle: frozenset[str], hay: frozenset[str]) -> float:
    if not needle:
        return 0.0
    return len(needle & hay) / len(needle)


def usable_company(name: str) -> bool:
    clean = (name or "").strip()
    return len(clean) >= 4 and clean.lower() not in _WEAK


def load_lessons(db: Session) -> list[Lesson]:
    out: list[Lesson] = []
    rows = db.scalars(
        select(Lead)
        .options(selectinload(Lead.company))
        .where(
            or_(
                Lead.status.in_(("dismissed", "rejected")),
                Lead.quality.in_(("false_positive", "genuine", "shortlist")),
            )
        )
    ).unique()
    for lead in rows:
        verdict = "reject" if lead.status in {"dismissed", "rejected"} or lead.quality == "false_positive" else "keep"
        out.append(
            Lesson(
                verdict=verdict,
                company=(lead.company.name if lead.company else "") or "",
                evidence=lead.evidence or "",
                source_url=lead.source_url or "",
                label=lead.status if lead.status in {"dismissed", "rejected"} else lead.quality,
                memory_type="positive_case" if verdict == "keep" else "negative_case",
            )
        )
    for row in db.scalars(select(RagMemory)):
        verdict = "keep" if row.human_label in {"true", "keep", "correct_lead", "genuine"} else "reject"
        if row.memory_type == "positive_case":
            verdict = "keep"
        if row.memory_type in {"negative_case", "correction"}:
            verdict = "reject"
        out.append(
            Lesson(
                verdict=verdict,
                company="",
                evidence=row.text,
                source_url="",
                label=row.memory_type,
                memory_type=row.memory_type,
            )
        )
    return out


def load_rules(db: Session) -> list[str]:
    seed_rules(db)
    return [row.rule_text for row in db.scalars(select(Rule).order_by(Rule.id.asc())).all()]


def seed_rules(db: Session) -> None:
    if db.scalar(select(Rule.id).limit(1)):
        return
    for text in DEFAULT_RULES:
        db.add(Rule(rule_text=text, rule_type="classifier", source="seed", confidence=90))
    db.commit()


def banned_names(lessons: list[Lesson]) -> list[str]:
    return sorted({lesson.company for lesson in lessons if lesson.verdict == "reject" and usable_company(lesson.company)})


def retrieve(text: str, lessons: list[Lesson], k: int = 4) -> list[Lesson]:
    hay = tokens(text)
    ranked = sorted(
        ((recall(tokens(f"{lesson.company} {lesson.evidence}"), hay), lesson) for lesson in lessons),
        key=lambda item: item[0],
        reverse=True,
    )
    return [lesson for score, lesson in ranked if score >= 0.12][:k]


def retrieve_pack(text: str, lessons: list[Lesson], rules: list[str] | None = None, k: int = 5) -> MemoryPack:
    keep = retrieve(text, [item for item in lessons if item.verdict == "keep"], k)
    reject = retrieve(text, [item for item in lessons if item.verdict == "reject"], k)
    return MemoryPack(keep=keep, reject=reject, rules=(rules or [])[:8])


def remembered_reject(text: str, company: str, source_url: str, lessons: list[Lesson]) -> Lesson | None:
    hay = tokens(f"{company} {text}")
    lowered = text.lower()
    company_l = (company or "").strip().lower()
    for lesson in lessons:
        if lesson.verdict != "reject":
            continue
        if source_url and lesson.source_url and source_url.rstrip("/") == lesson.source_url.rstrip("/"):
            return lesson
        name = lesson.company.strip()
        if usable_company(name) and re.search(rf"\b{re.escape(name)}\b", text, re.I):
            return lesson
        if usable_company(company) and company_l == name.lower():
            return lesson
        ev = (lesson.evidence or "").strip()
        if len(ev) >= 40 and ev.lower() in lowered:
            return lesson
        ev_tokens = tokens(f"{name} {ev}")
        if len(ev_tokens) >= 5 and recall(ev_tokens, hay) >= 0.7:
            return lesson
    return None


def prompt_block(pack: MemoryPack | list[Lesson]) -> str:
    if isinstance(pack, list):
        pack = MemoryPack(keep=[item for item in pack if item.verdict == "keep"], reject=[item for item in pack if item.verdict == "reject"])
    chunks: list[str] = []
    if pack.keep:
        chunks.append("SIMILAR CONFIRMED LEADS:")
        chunks.extend(_lines(pack.keep))
    if pack.reject:
        chunks.append("SIMILAR FALSE POSITIVES / CORRECTIONS — do not repeat these mistakes:")
        chunks.extend(_lines(pack.reject))
    if pack.rules:
        chunks.append("CLASSIFICATION RULES:")
        chunks.extend(f"- {rule}" for rule in pack.rules)
    return ("\n".join(chunks) + "\n") if chunks else ""


def pack_as_json(pack: MemoryPack) -> list[dict]:
    out = []
    for lesson in pack.keep:
        out.append({"verdict": "keep", "company": lesson.company, "evidence": lesson.evidence[:180], "label": lesson.label})
    for lesson in pack.reject:
        out.append({"verdict": "reject", "company": lesson.company, "evidence": lesson.evidence[:180], "label": lesson.label})
    return out


def record_feedback(db: Session, lead: Lead, label: str, reason: str = "") -> Lead:
    if label not in FEEDBACK_LABELS:
        raise ValueError(f"label must be one of {FEEDBACK_LABELS}")
    db.add(Feedback(lead_id=lead.id, human_label=label, reason=reason or ""))
    company = (lead.company.name if lead.company else "") or ""
    text = " ".join(part for part in [company, lead.evidence, reason] if part)
    memory_type = "positive_case" if label == "correct_lead" else ("correction" if label.startswith("wrong_") else "negative_case")
    db.add(
        RagMemory(
            memory_type=memory_type,
            text=text[:2000],
            source_type=lead.source_platform or "",
            intent_type=lead.intent_type or "",
            industry=lead.industry or "",
            human_label="true" if label == "correct_lead" else "false",
            lead_id=lead.id,
        )
    )
    quality = _LABEL_QUALITY.get(label)
    if quality:
        lead.quality = quality
        lead.reviewed_at = __now()
    if label == "correct_lead" and lead.status == "new":
        lead.status = "qualified"
    if label == "false_positive" and lead.status in {"new", "reviewing"}:
        lead.status = "rejected"
    if label == "duplicate":
        lead.status = "dismissed"
        lead.quality = "false_positive"
        lead.reviewed_at = __now()
    db.commit()
    db.refresh(lead)
    return lead


def record_quality(db: Session, lead: Lead, quality: str) -> None:
    """Keep the old quality buttons as RAG writes too."""
    label = "correct_lead" if quality in {"genuine", "shortlist"} else ("false_positive" if quality == "false_positive" else "")
    if not label:
        return
    if any(row.human_label == label and row.lead_id == lead.id for row in db.scalars(select(Feedback).where(Feedback.lead_id == lead.id))):
        return
    db.add(Feedback(lead_id=lead.id, human_label=label, reason=quality))
    db.add(
        RagMemory(
            memory_type="positive_case" if label == "correct_lead" else "negative_case",
            text=f"{(lead.company.name if lead.company else '')} {lead.evidence}"[:2000],
            source_type=lead.source_platform or "",
            intent_type=lead.intent_type or "",
            industry=lead.industry or "",
            human_label="true" if label == "correct_lead" else "false",
            lead_id=lead.id,
        )
    )


def maybe_refresh_rules(db: Session) -> int:
    """Summarize recurring false positives into rules. MuseSpark if present, else skip."""
    from app.providers.ai import muse_provider

    fps = list(db.scalars(select(Lead).where(Lead.quality == "false_positive").limit(40)))
    if len(fps) < 8:
        return 0
    generated = db.scalar(select(Rule).where(Rule.source == "summarizer").limit(1))
    if generated:
        return 0
    muse = muse_provider()
    if muse is None:
        return 0
    examples = "\n".join(f"- {(lead.evidence or '')[:180]}" for lead in fps[:20])
    parsed = muse.complete_json(
        (
            "These were marked false positives. List up to 5 concise classification rules "
            "that would have rejected them. No preamble.\n"
            f"{examples}"
        ),
        "RuleList",
        {
            "type": "object",
            "properties": {"rules": {"type": "array", "items": {"type": "string"}}},
            "required": ["rules"],
        },
    )
    added = 0
    for text in (parsed or {}).get("rules") or []:
        if isinstance(text, str) and text.strip():
            db.add(Rule(rule_text=text.strip()[:400], rule_type="classifier", source="summarizer", confidence=70))
            added += 1
    if added:
        db.commit()
    return added


def _lines(lessons: list[Lesson]) -> list[str]:
    lines = []
    for lesson in lessons:
        who = lesson.company or "unnamed"
        quote = " ".join((lesson.evidence or "").split())[:180]
        lines.append(f"- {lesson.verdict.upper()} ({lesson.label}): {who} — {quote}")
    return lines


def __now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)
