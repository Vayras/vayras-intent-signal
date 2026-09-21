from app.models import Contact, Lead
from app.pipeline.taxonomy import INTENT_LABELS


def draft_outreach(lead: Lead, contact: Contact | None = None) -> str:
    company = lead.company.name if lead.company else "there"
    name = (contact.name.split()[0] if contact and contact.name else None) or "there"
    intent = INTENT_LABELS.get(lead.intent_type, lead.intent_type.replace("_", " ").title())
    geo = lead.geography or "India"
    campaign = (lead.campaign_type or "creator campaign").replace("_", " ")
    evidence = lead.evidence.strip().strip('"')
    return (
        f"Subject: {intent} — can we help {company}?\n\n"
        f"Hi {name},\n\n"
        f"I saw your public note about needing help with {intent.lower()} "
        f"({campaign} in {geo}):\n\n"
        f"\"{evidence}\"\n\n"
        f"We run influencer and UGC campaigns for {lead.industry or 'consumer'} brands "
        f"and can shortlist creators this week if the brief is still open.\n\n"
        f"Worth a 15-minute call?\n\n"
        f"—\n"
        f"Draft only. Sending stays off until a human approves."
    )
