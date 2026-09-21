from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import settings
from app.pipeline.crawl import Document, fetch_document, is_social_host, parse_document
from app.providers.ai import ChatAIProvider, WEAK_BRAND_NAMES, extract_handles, get_ai_provider, muse_provider
from app.providers.search import get_search_provider, searx_categories

ROLE_PATTERNS = [
    (r"\b(founder(?:\s+and\s+ceo)?|co-?founder)\b", "Founder"),
    (r"\b(ceo|chief executive)\b", "CEO"),
    (r"\b(cmo|chief marketing officer)\b", "CMO"),
    (r"\b(head of marketing)\b", "Head of Marketing"),
    (r"\b(influencer marketing manager)\b", "Influencer Marketing Manager"),
    (r"\b(creator partnerships manager)\b", "Creator Partnerships Manager"),
    (r"\b(brand manager)\b", "Brand Manager"),
    (r"\b(social media manager)\b", "Social Media Manager"),
    (r"\b(marketing lead)\b", "Marketing Lead"),
]

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
CITY_RE = re.compile(
    r"\b(Mumbai|Delhi|New Delhi|Bengaluru|Bangalore|Hyderabad|Pune|Chennai|Kolkata|Jaipur|Gurgaon|Gurugram|Noida)\b"
)


@dataclass
class FoundContact:
    name: str | None
    job_title: str | None
    email: str | None
    source_url: str


@dataclass
class CompanyFacts:
    name: str | None = None
    website: str | None = None
    domain: str | None = None
    linkedin_url: str | None = None
    instagram_url: str | None = None
    city: str | None = None
    industry: str | None = None


@dataclass
class EnrichmentResult:
    contacts: list[FoundContact]
    facts: CompanyFacts
    pages_searched: list[str]


class EnrichmentProvider:
    name = "EnrichmentProvider"

    def discover(self, text: str, source_url: str) -> list[FoundContact]:
        raise NotImplementedError


class PublicWebEnrichment(EnrichmentProvider):
    """Public pages only. Never invent a mailbox. Never log in."""

    name = "PublicWeb"

    def discover(self, text: str, source_url: str) -> list[FoundContact]:
        return _contacts_from_text(text, source_url)

    def enrich(
        self,
        text: str,
        source_url: str,
        company_name: str | None = None,
        website: str | None = None,
        domain: str | None = None,
    ) -> EnrichmentResult:
        contacts = _contacts_from_text(text, source_url)
        facts = CompanyFacts(website=website, domain=domain)
        pages: list[str] = []
        muse = muse_provider()
        extra = muse.extract_entities(text) if muse else {}
        handles = extract_handles(text, source_url)
        if not company_name and extra.get("company"):
            company_name = extra["company"]
        if not company_name and handles:
            company_name = _company_from_handle(text, handles)
        facts.name = company_name
        facts.industry = extra.get("industry") or None
        facts.city = extra.get("city") or None

        site = website or _website_from_domain(domain) or _website_from_emails(contacts)
        weak_name = not facts.name or facts.name in WEAK_BRAND_NAMES or facts.name.startswith("Unknown")
        if muse and (weak_name or not site):
            grounded = muse.resolve_public_facts(text, source_url, facts.name or "")
            facts.name = facts.name or (grounded.get("company") or None)
            facts.industry = facts.industry or (grounded.get("industry") or None)
            facts.city = facts.city or (grounded.get("city") or None)
            if not site and grounded.get("website", "").startswith("http"):
                site = grounded["website"]
        if not site and (facts.name or handles):
            site = search_official_site(facts.name or handles[0])
        if site:
            facts.website = facts.website or site
            facts.domain = facts.domain or urlparse(site).netloc

        if site and not is_social_host(urlparse(site).netloc):
            home = fetch_document(site)
            if home:
                pages.append(home.url)
                _merge_facts(facts, home)
                contacts.extend(_contacts_from_document(home))
                for link in home.contact_links:
                    time.sleep(settings.crawl_delay_seconds)
                    inner = fetch_document(link)
                    if not inner:
                        continue
                    pages.append(inner.url)
                    _merge_facts(facts, inner)
                    contacts.extend(_contacts_from_document(inner))

        if facts.name and not any(item.email for item in contacts):
            for extra_url in search_contact_pages(facts.name):
                time.sleep(settings.crawl_delay_seconds)
                extra_doc = fetch_document(extra_url)
                if not extra_doc:
                    continue
                pages.append(extra_doc.url)
                _merge_facts(facts, extra_doc)
                contacts.extend(_contacts_from_document(extra_doc))

        if facts.name:
            contacts.extend(search_people(facts.name))

        contacts.extend(
            FoundContact(
                name=person.get("name") or None,
                job_title=person.get("job_title") or None,
                email=None,
                source_url=source_url,
            )
            for person in extra.get("people") or []
            if person.get("name") and person["name"].lower() in text.lower()
        )

        return EnrichmentResult(contacts=_dedupe_contacts(contacts), facts=facts, pages_searched=pages)


def parse_public_html(url: str, html: str) -> Document:
    return parse_document(url, html)


def _contacts_from_document(doc: Document) -> list[FoundContact]:
    contacts = _contacts_from_text(doc.text, doc.url)
    known = {item.email for item in contacts if item.email}
    role = _first_role(doc.text)
    for email in doc.emails:
        if email in known:
            continue
        contacts.append(FoundContact(name=None, job_title=role, email=email, source_url=doc.url))
    return contacts


def _contacts_from_text(text: str, source_url: str) -> list[FoundContact]:
    decoded = re.sub(r"\s*(?:\[at\]|\(at\))\s*", "@", text, flags=re.I)
    decoded = re.sub(r"\s*(?:\[dot\]|\(dot\))\s*", ".", decoded, flags=re.I)
    emails = []
    seen: set[str] = set()
    for match in EMAIL_RE.finditer(decoded):
        email = match.group(0).lower()
        if email in seen or email.endswith((".png", ".jpg", ".gif")):
            continue
        if any(part in email for part in ("example.com", "sentry", "wixpress", "noreply")):
            continue
        seen.add(email)
        emails.append((email, match.start()))

    role = _first_role(decoded)
    contacts: list[FoundContact] = []
    for email, index in emails:
        window = decoded[max(0, index - 160) : index]
        contacts.append(
            FoundContact(
                name=_name_from_window(window),
                job_title=role,
                email=email,
                source_url=source_url,
            )
        )
    if not contacts and role:
        name = _standalone_name(decoded)
        if name:
            contacts.append(FoundContact(name=name, job_title=role, email=None, source_url=source_url))
    return contacts[:8]


def _first_role(text: str) -> str | None:
    for pattern, title in ROLE_PATTERNS:
        if re.search(pattern, text, re.I):
            return title
    return None


def _name_from_window(window: str) -> str | None:
    match = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*$", window.strip())
    if match:
        return match.group(1)
    match = re.search(r"([A-Z][a-z]+\s+[A-Z][a-z]+)", window)
    return match.group(1) if match else None


def _standalone_name(text: str) -> str | None:
    match = re.search(
        r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b(?:\s*[,—-]\s*(?:Founder|CEO|CMO|Head|Marketing))",
        text,
    )
    return match.group(1) if match else None


def _website_from_domain(domain: str | None) -> str | None:
    if not domain or is_social_host(domain):
        return None
    host = domain.lower()
    if host.startswith("www."):
        return f"https://{host}"
    return f"https://{host}"


def _website_from_emails(contacts: list[FoundContact]) -> str | None:
    for contact in contacts:
        if not contact.email:
            continue
        host = contact.email.rsplit("@", 1)[-1]
        if is_social_host(host) or host in {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com"}:
            continue
        return f"https://{host}"
    return None


def _company_from_handle(text: str, handles: list[str]) -> str:
    provider = get_ai_provider()
    if isinstance(provider, ChatAIProvider):
        name = provider.resolve_brand(text, handles)
        if name:
            return name
    return handles[0].replace("_", " ").replace(".", " ").title()


def search_official_site(company_name: str) -> str | None:
    search = get_search_provider()
    for query in (
        f'"{company_name}" official website India',
        f'"{company_name}" official site',
        f'"{company_name}" India brand',
    ):
        try:
            hits = search.search(query, limit=5, categories="general")
        except Exception:
            continue
        for hit in hits:
            host = urlparse(hit.url).netloc
            if hit.url.startswith("http") and not is_social_host(host):
                return f"{urlparse(hit.url).scheme}://{host}"
    return None


def search_contact_pages(company_name: str) -> list[str]:
    search = get_search_provider()
    seen: set[str] = set()
    out: list[str] = []
    for query in (
        f'"{company_name}" founder contact email India',
        f'"{company_name}" "contact us" -site:linkedin.com',
        f'"{company_name}" site:linkedin.com/company',
        f'"{company_name}" (founder OR CMO OR "head of marketing") site:linkedin.com/in India',
    ):
        try:
            hits = search.search(query, limit=4, categories=searx_categories(query))
        except Exception:
            continue
        for hit in hits:
            if not hit.url.startswith("http") or hit.url in seen:
                continue
            seen.add(hit.url)
            out.append(hit.url)
            if len(out) >= 5:
                return out
    return out


def search_people(company_name: str) -> list[FoundContact]:
    search = get_search_provider()
    people: list[FoundContact] = []
    try:
        hits = search.search(
            f'"{company_name}" (founder OR CMO OR "head of marketing" OR "influencer marketing") site:linkedin.com/in India',
            limit=8,
            categories="social media",
        )
    except Exception:
        return people
    for hit in hits:
        person = _person_from_linkedin(hit.url, hit.title)
        if person:
            people.append(person)
    return people


def _person_from_linkedin(url: str, title: str) -> FoundContact | None:
    if "linkedin.com/in" not in url.lower():
        return None
    cleaned = title.replace("| LinkedIn", "").replace("- LinkedIn", "").strip(" |-")
    parts = [part.strip() for part in cleaned.split(" - ") if part.strip()]
    if not parts:
        return None
    return FoundContact(
        name=parts[0][:120],
        job_title=(parts[1][:120] if len(parts) > 1 else None),
        email=None,
        source_url=url,
    )


def _merge_facts(facts: CompanyFacts, doc: Document) -> None:
    facts.website = facts.website or f"{urlparse(doc.url).scheme}://{urlparse(doc.url).netloc}"
    facts.domain = facts.domain or doc.domain
    facts.linkedin_url = facts.linkedin_url or doc.linkedin_url
    facts.instagram_url = facts.instagram_url or doc.instagram_url
    if not facts.city:
        match = CITY_RE.search(doc.text)
        if match:
            facts.city = match.group(1)


def _dedupe_contacts(contacts: list[FoundContact]) -> list[FoundContact]:
    out: list[FoundContact] = []
    seen: set[str] = set()
    for contact in contacts:
        key = contact.email or f"{contact.name}|{contact.job_title}|{contact.source_url}"
        if key in seen:
            continue
        seen.add(key)
        out.append(contact)
    return out[:8]
