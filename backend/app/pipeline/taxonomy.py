from __future__ import annotations

import re

INTENT_TYPES = [
    "LOOKING_FOR_INFLUENCERS",
    "LOOKING_FOR_CREATORS",
    "NEEDS_UGC",
    "NEEDS_INFLUENCER_AGENCY",
    "HIRING_INFLUENCER_MARKETING",
    "CREATOR_CAMPAIGN",
    "PRODUCT_LAUNCH",
    "BRAND_AMBASSADOR",
    "ASKING_FOR_RECOMMENDATIONS",
]

INTENT_LABELS = {
    "LOOKING_FOR_INFLUENCERS": "Looking for influencers",
    "LOOKING_FOR_CREATORS": "Looking for creators",
    "NEEDS_UGC": "Needs UGC creators",
    "NEEDS_INFLUENCER_AGENCY": "Needs an influencer marketing agency",
    "HIRING_INFLUENCER_MARKETING": "Hiring influencer marketing",
    "CREATOR_CAMPAIGN": "Creator campaign",
    "PRODUCT_LAUNCH": "Product launch",
    "BRAND_AMBASSADOR": "Brand ambassadors",
    "ASKING_FOR_RECOMMENDATIONS": "Asking for recommendations",
}

CAMPAIGN_TYPES = [
    "product_launch",
    "creator_campaign",
    "brand_ambassador",
    "ugc",
    "always_on",
    "hiring",
]

LEAD_STATUSES = ["new", "reviewing", "qualified", "contacted", "rejected", "dismissed"]
QUALITY_LABELS = ["unset", "genuine", "shortlist", "false_positive", "no_contact"]
FEEDBACK_LABELS = [
    "correct_lead",
    "false_positive",
    "wrong_intent_type",
    "wrong_company",
    "wrong_urgency",
    "duplicate",
]
DEFAULT_RULES = [
    "Reject historical campaign recaps and case studies unless there is a new or ongoing request.",
    "Reject generic educational content (how-to, 'brands are looking for influencers in 2026').",
    "Reject creator-side posts looking for brand deals or sponsorships.",
    "Treat a job listing for Influencer Marketing Manager as medium intent, not an agency brief.",
    "Treat an explicit request for an influencer/creator agency as high intent.",
    "Agency promoting its own services is not a lead.",
]

KEYWORD_TERMS = [
    "looking for",
    "need",
    "seeking",
    "wanted",
    "recommend",
    "hire",
    "hiring",
    "campaign",
    "creators",
    "influencers",
    "ugc",
    "ambassador",
    "collaboration",
]

INDUSTRIES = ["beauty", "fashion", "d2c", "fintech", "food", "wellness", "saas", "jewellery"]
COUNTRIES = ["India"]
PLATFORMS = ["reddit", "forum", "job_board", "news", "company_site", "x", "linkedin", "instagram", "facebook", "youtube", "tiktok"]

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("NEEDS_INFLUENCER_AGENCY", re.compile(r"influencer marketing agency|creator agency|recommend.{0,40}agency", re.I)),
    ("HIRING_INFLUENCER_MARKETING", re.compile(r"hiring.{0,40}influencer|influencer marketing manager|head of influencer", re.I)),
    ("NEEDS_UGC", re.compile(r"\bugc\b|user[- ]generated", re.I)),
    ("BRAND_AMBASSADOR", re.compile(r"brand ambassadors?", re.I)),
    ("ASKING_FOR_RECOMMENDATIONS", re.compile(r"does anyone know|recommend|any good .{0,30}(agency|influencer|creator)", re.I)),
    ("PRODUCT_LAUNCH", re.compile(r"product launch|for our launch|upcoming launch", re.I)),
    ("LOOKING_FOR_INFLUENCERS", re.compile(r"looking for .{0,40}influencers|need .{0,40}influencers", re.I)),
    ("LOOKING_FOR_CREATORS", re.compile(r"looking for .{0,40}creators|need .{0,40}creators", re.I)),
    ("CREATOR_CAMPAIGN", re.compile(r"creator campaign|influencer campaign", re.I)),
]


def classify_intent_type(text: str) -> str:
    for intent, pattern in _RULES:
        if pattern.search(text):
            return intent
    if re.search(r"\binfluencers?\b", text, re.I):
        return "LOOKING_FOR_INFLUENCERS"
    if re.search(r"\bcreators?\b", text, re.I):
        return "LOOKING_FOR_CREATORS"
    return "CREATOR_CAMPAIGN"
