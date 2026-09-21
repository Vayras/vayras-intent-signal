from __future__ import annotations

import re

from app.providers.ai import Classification


def score_lead(text: str, classification: Classification) -> tuple[int, list[str]]:
    """Transparent additive score. A prioritization aid, not proof they will buy."""
    points = 0
    reasons: list[str] = []
    lower = text.lower()

    if classification.intent_type in {"LOOKING_FOR_INFLUENCERS", "LOOKING_FOR_CREATORS", "NEEDS_UGC"} or re.search(
        r"\b(looking for|need|wanted)\b.{0,40}\b(influencers?|creators?|ugc)\b", lower
    ):
        points += 40
        reasons.append("Explicitly looking for influencers/creators  +40")
    if classification.intent_type == "NEEDS_INFLUENCER_AGENCY" or "agency" in lower:
        points += 40
        reasons.append("Explicitly looking for an agency  +40")
    if re.search(r"\b(this month|next (?:week|month)|upcoming|q[1-4]|launching soon)\b", lower):
        points += 20
        reasons.append("Campaign timing mentioned  +20")
    if classification.campaign_type == "product_launch" or "launch" in lower:
        points += 15
        reasons.append("Product launch  +15")
    if re.search(r"\b(beauty|skincare|fashion|fintech|food|wellness|saas|jewellery|jewelry|d2c)\b", lower):
        points += 15
        reasons.append("Specific creator niche  +15")
    if classification.geography:
        points += 10
        reasons.append("Specific geography  +10")
    if classification.intent_type == "HIRING_INFLUENCER_MARKETING" or re.search(r"\bhiring\b", lower):
        points += 10
        reasons.append("Marketing hiring  +10")
    if re.search(r"\b(already work with|previous campaign|last launch|our creators)\b", lower):
        points += 10
        reasons.append("Previous creator activity  +10")
    if re.search(r"\b(budget|inr|₹|rs\.?)\s*\d", lower):
        points += 15
        reasons.append("Budget mentioned  +15")
    if re.search(r"\b(deadline|by friday|this week|before)\b", lower):
        points += 10
        reasons.append("Deadline mentioned  +10")

    if re.search(r"\b(recap|case study|wrapped up|we worked with|completed campaign|last year)\b", lower):
        points -= 40
        reasons.append("Historical campaign recap  -40")
    if re.search(r"\b(how brands|guide to|tips for|in 20\d\d)\b", lower) and not re.search(r"\b(looking for|need|wanted)\b", lower):
        points -= 30
        reasons.append("Generic educational article  -30")
    if re.search(r"\b(i(?:'m| am) a creator|seeking brand deals|want to collaborate with brands)\b", lower):
        points -= 40
        reasons.append("Creator looking for brand deals  -40")
    if re.search(r"\b(we help brands|our influencer network|hire through us)\b", lower):
        points -= 30
        reasons.append("Agency promoting its own services  -30")
    if not classification.company:
        points -= 20
        reasons.append("No identifiable buyer  -20")

    return max(min(points, 100), 0), reasons
