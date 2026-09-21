from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.pipeline.taxonomy import INTENT_TYPES, classify_intent_type

LEAD_SCHEMA = {
    "is_lead": False,
    "intent_type": "",
    "intent_strength": "low",
    "campaign_type": "",
    "geography": "",
    "urgency": "low",
    "company": "",
    "industry": "",
    "evidence": "",
    "confidence": "0.7",
    "reasoning_summary": "",
}


@dataclass
class Classification:
    is_lead: bool
    intent_type: str
    intent_strength: str
    campaign_type: str
    geography: str
    urgency: str
    company: str
    industry: str
    evidence: str
    provider: str
    confidence: float = 0.0
    reasoning: str = ""
    critique: str = ""

    def as_dict(self) -> dict:
        return {
            "is_lead": self.is_lead,
            "intent_type": self.intent_type,
            "intent_strength": self.intent_strength,
            "campaign_type": self.campaign_type,
            "geography": self.geography,
            "urgency": self.urgency,
            "company": self.company,
            "industry": self.industry,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "reasoning_summary": self.reasoning,
        }


class AIProvider:
    name = "AIProvider"

    def classify(self, text: str, source_url: str = "", lessons: list | None = None, rules: list[str] | None = None) -> Classification:
        raise NotImplementedError

    def status(self) -> tuple[bool, str]:
        raise NotImplementedError


class HeuristicAIProvider(AIProvider):
    """Transparent pattern classifier. Used when no chat model is configured."""

    name = "Heuristic"

    def classify(self, text: str, source_url: str = "", lessons: list | None = None, rules: list[str] | None = None) -> Classification:
        return heuristic_classify(text, source_url)

    def status(self) -> tuple[bool, str]:
        return True, "local pattern classifier (no model required)"


class OllamaAIProvider(AIProvider):
    name = "Ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._fallback = HeuristicAIProvider()

    def classify(self, text: str, source_url: str = "", lessons: list | None = None, rules: list[str] | None = None) -> Classification:
        prompt = _build_prompt(text, lessons, rules)
        try:
            with httpx.Client(timeout=45.0) as client:
                response = client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
                response.raise_for_status()
                raw = response.json().get("response", "")
            parsed = _parse_model_json(raw)
            evidence = (parsed.get("evidence") or "").strip()
            if evidence and evidence.lower() not in text.lower():
                # Classifier must quote the source, not invent a reason.
                snippet = _best_evidence(text)
                parsed["evidence"] = snippet or evidence
            result = _classification_from_dict(parsed, provider=self.name)
            if result.is_lead and result.intent_type not in INTENT_TYPES:
                result.intent_type = classify_intent_type(text)
            return result
        except Exception:
            fallback = self._fallback.classify(text, source_url)
            fallback.provider = f"{self.name}+{fallback.provider}"
            return fallback

    def status(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.get(f"{self.base_url}/api/tags")
            if response.status_code >= 400:
                return False, f"{self.base_url} ({response.status_code})"
            names = [item.get("name", "") for item in response.json().get("models", [])]
            return True, f"{self.model} via {self.base_url}; installed: {', '.join(names) or 'none'}"
        except Exception as exc:
            return False, str(exc)


class ChatAIProvider(AIProvider):
    """OpenAI-compatible chat/completions. Default: gpt-4o-mini."""

    name = "OpenAI"

    def __init__(self, api_key: str, model: str, base_url: str, name: str = "OpenAI"):
        self.api_key = api_key.strip()
        self.model = (model.strip() or "gpt-4o-mini").removeprefix("openai/")
        self.base_url = base_url.rstrip("/")
        self.name = name
        self._fallback = HeuristicAIProvider()

    def classify(self, text: str, source_url: str = "", lessons: list | None = None, rules: list[str] | None = None) -> Classification:
        parsed = self.complete_json(
            _build_prompt(text, lessons, rules),
            "LeadClassification",
            {
                "type": "object",
                "properties": {key: {"type": "boolean" if key == "is_lead" else "string"} for key in LEAD_SCHEMA},
                "required": list(LEAD_SCHEMA),
            },
        )
        if parsed is None:
            fallback = self._fallback.classify(text, source_url)
            fallback.provider = f"{self.name}+{fallback.provider}"
            return fallback
        evidence = (parsed.get("evidence") or "").strip()
        if evidence and evidence.lower() not in text.lower():
            parsed["evidence"] = _best_evidence(text) or evidence
        result = _classification_from_dict(parsed, provider=self.name)
        if result.is_lead and result.intent_type not in INTENT_TYPES:
            result.intent_type = classify_intent_type(text)
        return result

    def suggest_queries(self, avoid: list[str] | None = None) -> list[str]:
        ban = f" Never target these rejected names: {', '.join(avoid[:20])}." if avoid else ""
        parsed = self.complete_json(
            (
                "Write 24 SearXNG queries to find Indian D2C or large B2C brands currently asking "
                "for influencers, UGC, or creators. India only — never US, UK, EU, UAE, or SEA. "
                "Prefer Reddit, Instagram, Facebook, LinkedIn. "
                "Exclude agency pitches and marketplaces. Use quoted phrases, India, and site: filters."
                f"{ban}"
            ),
            "SearchQueries",
            {
                "type": "object",
                "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
                "required": ["queries"],
            },
        )
        return [item.strip() for item in (parsed or {}).get("queries") or [] if isinstance(item, str) and item.strip()][:24]

    def extract_company(self, text: str, url: str = "") -> str:
        parsed = self.complete_json(
            (
                "Extract the brand or company that is asking for influencers, creators, or UGC. "
                "Strip leading The/A/An. Use founder-of, quoted names, @handles, u/ names, or the email domain. "
                "Empty string if unnamed, or if this is an agency selling its own services. Do not invent.\n"
                f"URL: {url}\n\nTEXT:\n{text[:4000]}"
            ),
            "CompanyName",
            {"type": "object", "properties": {"company": {"type": "string"}}, "required": ["company"]},
        )
        return (parsed or {}).get("company", "").strip()

    def resolve_brand(self, text: str, handles: list[str]) -> str:
        if not handles:
            return self.extract_company(text)
        parsed = self.complete_json(
            (
                "Return the brand's public name if the text or handle makes it clear. "
                "Empty string if you would be guessing. Do not invent a legal entity.\n"
                f"HANDLES: {', '.join('@' + h for h in handles)}\n\nTEXT:\n{text[:3000]}"
            ),
            "BrandName",
            {"type": "object", "properties": {"company": {"type": "string"}}, "required": ["company"]},
        )
        return (parsed or {}).get("company", "").strip()

    def extract_entities(self, text: str) -> dict:
        parsed = self.complete_json(
            (
                "Extract only facts stated in the text. Empty strings if unknown. "
                "People must have a name that appears in the text. Do not invent emails.\n\n"
                f"TEXT:\n{text[:6000]}"
            ),
            "Entities",
            {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "industry": {"type": "string"},
                    "city": {"type": "string"},
                    "people": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "job_title": {"type": "string"},
                            },
                            "required": ["name", "job_title"],
                        },
                    },
                },
                "required": ["company", "industry", "city", "people"],
            },
        )
        return parsed or {}

    def resolve_public_facts(self, text: str, url: str = "", company: str = "") -> dict:
        """Official name + homepage from the post. Empty fields if unconfirmed."""
        parsed = self.complete_json(
            (
                "Identify this Indian brand from the public post. "
                "Return the official company name and homepage if you can confirm them. "
                "Empty strings if you cannot confirm. Do not invent emails or legal entities.\n"
                f"HINT: {company}\nURL: {url}\n\nPOST:\n{text[:3500]}"
            ),
            "PublicCompany",
            {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "website": {"type": "string"},
                    "city": {"type": "string"},
                    "industry": {"type": "string"},
                },
                "required": ["company", "website", "city", "industry"],
            },
        )
        return parsed or {}

    def complete_grounded_json(self, prompt: str, schema_name: str, schema: dict) -> dict | None:
        return self.complete_json(prompt, schema_name, schema)

    def complete_json(self, prompt: str, schema_name: str, schema: dict) -> dict | None:
        if not self.api_key:
            return None
        try:
            with httpx.Client(timeout=90.0, headers=self._headers()) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Return JSON only. Quote the source. Do not invent facts.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0,
                        "max_tokens": 800,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                raw = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return _parse_model_json(raw)
        except Exception:
            return None

    def status(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "OPENAI_API_KEY is not set"
        try:
            with httpx.Client(timeout=6.0, headers=self._headers()) as client:
                response = client.get(f"{self.base_url}/models")
            if response.status_code >= 400:
                return False, f"{self.base_url} ({response.status_code})"
            return True, f"{self.model} via {self.base_url}"
        except Exception as exc:
            return False, str(exc)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


def get_ai_provider() -> AIProvider:
    if settings.openai_api_key:
        return ChatAIProvider(
            settings.openai_api_key,
            settings.openai_model,
            settings.openai_url,
            name="OpenAI",
        )
    ollama = OllamaAIProvider(settings.ollama_url, settings.ollama_model)
    active, _ = ollama.status()
    return ollama if active else HeuristicAIProvider()


def muse_provider() -> ChatAIProvider | None:
    provider = get_ai_provider()
    return provider if isinstance(provider, ChatAIProvider) else None


def classify_text(text: str, source_url: str = "", lessons: list | None = None, rules: list[str] | None = None) -> Classification:
    """Noise filter → retrieve similar cases → classify → critic → confidence band."""
    from app.pipeline.memory import remembered_reject

    cheap = heuristic_classify(text, source_url)
    prior = remembered_reject(text, cheap.company, source_url, lessons or [])
    if prior:
        cheap.is_lead = False
        cheap.critique = f"Matches a past {prior.label} on {prior.company or 'similar text'}."
        cheap.provider = f"{cheap.provider}+memory"
        return cheap
    if _is_noise(text):
        return cheap
    provider = get_ai_provider()
    if isinstance(provider, HeuristicAIProvider):
        if not cheap.company:
            cheap.company = resolve_company_name(text, source_url)
        return _confidence_gate(_critic_pass(cheap, text), text, source_url)
    if not isinstance(provider, ChatAIProvider) and not cheap.is_lead:
        return _confidence_gate(_critic_pass(cheap, text), text, source_url)
    result = provider.classify(text, source_url, lessons, rules)
    if result.is_lead and is_agency_seller(text, result.company, source_url):
        result.is_lead = False
        result.critique = "Agency promoting its own services."
        result.provider = f"{result.provider}+agency-filter"
        return result
    if result.is_lead and not result.company and cheap.company:
        result.company = cheap.company
    if result.is_lead and not result.company:
        result.company = resolve_company_name(text, source_url, provider)
    if result.is_lead and not result.evidence:
        result.evidence = cheap.evidence or _best_evidence(text)
    if result.is_lead and remembered_reject(text, result.company, source_url, lessons or []):
        result.is_lead = False
        result.provider = f"{result.provider}+memory"
        result.critique = "Similar to a previously rejected case."
    return _confidence_gate(_critic_pass(result, text), text, source_url)


SKIP_HANDLES = {
    "instagram",
    "facebook",
    "youtube",
    "reddit",
    "twitter",
    "tiktok",
    "linkedin",
    "here",
    "everyone",
    "ugc",
    "gmail",
    "whatsapp",
    "telegram",
    "share",
    "explore",
}


def extract_handles(text: str, url: str = "") -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"(?<![A-Za-z0-9])@([A-Za-z0-9._]{2,30})", text):
        found.append(match.group(1).strip("._"))
    for match in re.finditer(r"\bu/([A-Za-z0-9._-]{2,30})", text):
        found.append(match.group(1).strip("._-"))
    for match in re.finditer(
        r"(?:instagram|facebook|x|reddit)\.com/(?:user/|u/)?([A-Za-z0-9._]{2,30})",
        f"{url} {text}",
        re.I,
    ):
        slug = match.group(1)
        if slug.lower() not in {"p", "reel", "reels", "stories", "explore", "share", "watch", "r", "u", "user", "comments"}:
            found.append(slug)
    out: list[str] = []
    seen: set[str] = set()
    for handle in found:
        key = handle.lower()
        if key in SKIP_HANDLES or key in seen:
            continue
        seen.add(key)
        out.append(handle)
    return out[:5]


def resolve_company_name(text: str, url: str = "", provider: AIProvider | None = None) -> str:
    provider = provider or get_ai_provider()
    if isinstance(provider, ChatAIProvider):
        name = _clean_brand(provider.extract_company(text, url))
        if name:
            return name
    name = _guess_company(text)
    if name:
        return name
    name = resolve_company_from_handles(text, url, provider)
    if name:
        return name
    return _company_from_email(text)


def resolve_company_from_handles(text: str, url: str = "", provider: AIProvider | None = None) -> str:
    handles = extract_handles(text, url)
    if not handles:
        return ""
    if isinstance(provider, ChatAIProvider):
        name = provider.resolve_brand(text, handles)
        if name and name.lower() not in {item.lower() for item in BAD_COMPANY}:
            return name
    handle = handles[0]
    if len(handle) < 4:
        return ""
    return handle.replace("_", " ").replace(".", " ").title()


# --- heuristic -------------------------------------------------------------

ASK_RE = re.compile(
    r"\b(looking for|look(?:ing)? to (?:hire|find)|need(?:s|ed)?|seeking|wanted|want(?:ed)?|hire|hiring|recommend|any(?:one|body) know)\b",
    re.I,
)
CREATOR_RE = re.compile(r"\b(influencers?|creators?|ugc|brand ambassadors?|creator partners?(?:hips)?)\b", re.I)
AGENCY_RE = re.compile(r"\b(influencer marketing agency|creator agency|ugc agency)\b", re.I)
HIRE_RE = re.compile(r"\b(hiring|job|role|open(?:ing)?)\b", re.I)
GENERIC_RE = re.compile(
    r"(is growing|works with influencers|our company works with|interested in creator marketing|thought leadership)",
    re.I,
)
LAUNCH_RE = re.compile(r"\b(launch|launching|upcoming campaign|this month|next (?:week|month)|q[1-4])\b", re.I)
URGENCY_RE = re.compile(r"\b(asap|urgent|this week|immediately|next week|launching (?:soon|next))\b", re.I)
COMPANY_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9&'.-]+(?:\s+[A-Z][A-Za-z0-9&'.-]+){0,3})\s+(?:is|are|we.?re|here)\b"
)
INDUSTRY_HINTS = {
    "beauty": "beauty",
    "skincare": "beauty",
    "makeup": "beauty",
    "fashion": "fashion",
    "apparel": "fashion",
    "jewellery": "jewellery",
    "jewelry": "jewellery",
    "fintech": "fintech",
    "payments": "fintech",
    "food": "food",
    "snack": "food",
    "wellness": "wellness",
    "ayurveda": "wellness",
    "saas": "saas",
    "app": "saas",
    "d2c": "d2c",
}


NOISE_RE = re.compile(
    r"(influencer marketplace|find\s*&\s*hire|hire top influencers|"
    r"creator growth platform|creator discovery|ultimate guide|"
    r"types of influencers|industry was estimated|promote your brand|"
    r"looking for paid ugc|creator looking for|we need creators like|"
    r"best (?:clipping|influencer marketing) (?:platform|agency)|"
    r"everything creators need to grow|we source nano|verified & onboarded|"
    r"playbook for indian brand ambassadors|most trusted influencer marketing|"
    r"creating real impact for brands|businesses looking for influencer|"
    r"simplify life for companies and agencies looking|"
    r"brand managers don't scroll|should choose based on the campaign|"
    r"top \d+ influencer|influencer marketing platforms you need)",
    re.I,
)
FIRST_PERSON_ASK = re.compile(
    r"\b(we(?:'re| are)? looking|we need|i(?:'m| am) looking|"
    r"ugc creators wanted|creators wanted|"
    r"looking for (?:indian )?(?:ugc |influencers?|creators?|influencer marketing)|"
    r"need (?:ugc |indian )?(?:creators?|influencers?)|"
    r"hello everyone we are looking)\b",
    re.I,
)
SELLING_CREATORS_RE = re.compile(
    r"does anyone need influencers|influencers with a good engagement|"
    r"are you looking for influencer marketing agency in",
    re.I,
)
AGENCY_SELLER_RE = re.compile(
    r"(best influencer marketing agency|top influencer marketing agency|"
    r"influencer marketing agency in (?:india|delhi|mumbai|bengaluru|bangalore)|"
    r"we are an? (?:influencer|creator|ugc) (?:marketing )?agency|"
    r"full[- ]service influencer marketing|"
    r"helping brands (?:connect|find|work) with (?:the right )?influencers|"
    r"connect(?:ing)? brands? with (?:the right )?influencers|"
    r"hire (?:our|an) influencer marketing agency|"
    r"our influencer marketing (?:agency|services)|"
    r"influencer marketing agency for hire)",
    re.I,
)
BAD_COMPANY = {
    "We",
    "I",
    "Looking",
    "Need",
    "Does",
    "Anyone",
    "The",
    "Our",
    "This",
    "Hi",
    "Hello",
    "India",
    "Indian",
    "Indians",
    "But",
    "Here",
    "What",
    "And",
    "Join",
    "Scale",
    "You",
    "Your",
    "How",
    "Why",
    "When",
    "Where",
    "Brand",
    "A",
    "An",
}


AGENCY_NAME_RE = re.compile(
    r"\b(agency|agencies|media|marketing platform|creator (?:network|studio|database)|talent)\b",
    re.I,
)
AGENCY_PITCH_RE = re.compile(
    r"brands (?:here )?need|for your brand|creator network|"
    r"we help brands|influencer marketing platform|"
    r"hire top influencers|agencies keep reaching|"
    r"digital marketing agency|social media agency|"
    r"premium d2c brands need|expanding its creator|"
    r"your brand|across fashion, beauty",
    re.I,
)
D2C_BRAND_RE = re.compile(
    r"\b(d2c|direct[- ]to[- ]consumer|my (?:brand|product|app|startup)|"
    r"our (?:brand|product|app|store|launch)|cosmetics brand|fashion brand)\b",
    re.I,
)
D2C_VERTICALS = {"beauty", "fashion", "food", "wellness", "jewellery", "d2c", "fintech"}
WEAK_BRAND_NAMES = {
    "Groups",
    "How",
    "This Point",
    "This Point We",
    "All Over India",
    "Region Settings",
    "Main Menu What",
    "IT. It",
    "Venusky",
    "Brands",
    "Brand",
}
OPINION_RE = re.compile(
    r"do we really need|shouldn't need|we do not need influencers|"
    r"government need influencers|whether you need influencers|"
    r"endless scroll|wasted hours scrolling",
    re.I,
)
LARGE_B2C = {
    "nykaa",
    "myntra",
    "flipkart",
    "amazon",
    "ajio",
    "meesho",
    "tata",
    "reliance",
    "unilever",
    "hul",
    "itc",
    "nestle",
    "loreal",
    "l'oreal",
    "mamaearth",
    "boat",
    "swiggy",
    "zomato",
    "zepto",
    "blinkit",
    "licious",
    "purplle",
    "firstcry",
    "sugar",
    "plum",
    "minimalist",
    "lakme",
}


def is_agency_seller(text: str, company_name: str = "", source_url: str = "") -> bool:
    """True when the page is an agency pitching, not a brand asking."""
    hay = f"{company_name} {text} {source_url}"
    if AGENCY_SELLER_RE.search(hay) or AGENCY_PITCH_RE.search(hay):
        return True
    if re.search(r"top \d+ .*influencer|influencer marketing platforms you need", hay, re.I):
        return True
    return bool(company_name and AGENCY_NAME_RE.search(company_name))


def is_target_brand(text: str, company_name: str = "", industry: str = "", source_url: str = "") -> bool:
    """D2C or large B2C brand asking — not an agency or thought piece."""
    if is_agency_seller(text, company_name, source_url) or OPINION_RE.search(text):
        return False
    name = (company_name or "").strip()
    lowered = name.lower()
    if any(brand == lowered or brand in lowered.split() for brand in LARGE_B2C):
        return True
    hay = f"{name} {text}"
    if D2C_BRAND_RE.search(hay):
        return True
    usable = bool(name) and name not in WEAK_BRAND_NAMES and name.split()[0] not in BAD_COMPANY
    industry_l = (industry or "").lower()
    if usable and industry_l in D2C_VERTICALS:
        return True
    if usable and "linkedin.com/company" in (source_url or "").lower():
        return True
    brand_ask = FIRST_PERSON_ASK.search(text) or re.search(
        r"\bwe (?:are )?.{0,24}looking for\b", text, re.I
    )
    if not brand_ask:
        return False
    if not usable:
        return False
    if (industry or "").lower() in D2C_VERTICALS:
        return True
    return bool(re.search(r"\b(brand|product|app|startup|store|launch)\b", text, re.I))


def _is_noise(text: str) -> bool:
    return bool(
        NOISE_RE.search(text)
        or SELLING_CREATORS_RE.search(text)
        or GENERIC_RE.search(text)
        or is_agency_seller(text)
    )


def heuristic_classify(text: str, source_url: str = "") -> Classification:
    compact = " ".join(text.split())
    ask = bool(ASK_RE.search(compact))
    creator = bool(CREATOR_RE.search(compact))
    agency = bool(AGENCY_RE.search(compact))
    generic = bool(GENERIC_RE.search(compact))
    is_lead = (
        ask
        and (creator or agency)
        and not _is_noise(compact)
        and bool(FIRST_PERSON_ASK.search(compact) or AGENCY_RE.search(compact))
    )

    if generic and not ask:
        is_lead = False

    intent_type = classify_intent_type(compact) if is_lead else ""
    if is_lead and not intent_type:
        intent_type = "LOOKING_FOR_CREATORS"

    strength = "low"
    if is_lead and ask and (creator or agency):
        strength = "high" if LAUNCH_RE.search(compact) or agency or URGENCY_RE.search(compact) else "medium"
        if re.search(r"\b(looking for|need|ugc creators wanted|does anyone know)\b", compact, re.I):
            strength = "high"

    urgency = "high" if URGENCY_RE.search(compact) else ("medium" if LAUNCH_RE.search(compact) else "low")
    campaign = "product_launch" if re.search(r"\b(launch|product launch)\b", compact, re.I) else ""
    if not campaign and re.search(r"\bcampaign\b", compact, re.I):
        campaign = "creator_campaign"
    if not campaign and re.search(r"\bambassador\b", compact, re.I):
        campaign = "brand_ambassador"
    if not campaign and HIRE_RE.search(compact) and "influencer" in compact.lower():
        campaign = "hiring"

    geography = _guess_geo(compact)
    company = resolve_company_name(compact, source_url)
    industry = _guess_industry(compact)
    evidence = _best_evidence(compact)

    if not is_lead:
        return Classification(
            is_lead=False,
            intent_type="",
            intent_strength="low",
            campaign_type="",
            geography=geography,
            urgency="low",
            company=company,
            industry=industry,
            evidence=evidence,
            provider="Heuristic",
        )

    return Classification(
        is_lead=True,
        intent_type=intent_type,
        intent_strength=strength,
        campaign_type=campaign or "creator_campaign",
        geography=geography,
        urgency=urgency,
        company=company,
        industry=industry,
        evidence=evidence,
        provider="Heuristic",
    )


INDIA_PLACES = (
    "India",
    "Indian",
    "Bharat",
    "Mumbai",
    "Delhi",
    "New Delhi",
    "Bengaluru",
    "Bangalore",
    "Hyderabad",
    "Pune",
    "Chennai",
    "Kolkata",
    "Jaipur",
    "Ahmedabad",
    "Surat",
    "Indore",
    "Kochi",
    "Gurgaon",
    "Gurugram",
    "Noida",
    "Lucknow",
    "Chandigarh",
    "Coimbatore",
    "Goa",
)
INDIA_SIGNAL_RE = re.compile(
    r"\b(india|indian|bharat|mumbai|delhi|bengaluru|bangalore|hyderabad|pune|"
    r"chennai|kolkata|jaipur|ahmedabad|surat|indore|kochi|gurgaon|gurugram|"
    r"noida|lucknow|chandigarh|coimbatore|goa|inr|rupees?)\b|₹|\+91\b|\.co\.in\b",
    re.I,
)
FOREIGN_MARKET_RE = re.compile(
    r"\b(united states|\bu\.?s\.?a\.?\b|\bu\.s\.\b|\buk\b|united kingdom|london|"
    r"new york|\bnyc\b|california|los angeles|canada|toronto|australia|sydney|"
    r"europe|\beu\b|germany|france|uae|dubai|singapore|indonesia|philippines|"
    r"nigeria|brazil|american|british)\b",
    re.I,
)


def is_india_target(text: str, url: str = "", geography: str = "", company: str = "") -> bool:
    """True only when the ask is for an India market."""
    hay = f"{text} {url} {geography} {company}"
    if re.search(r"\b(in|across) (the )?(us|usa|u\.s\.|uk|united states|united kingdom|uae|europe)\b", hay, re.I):
        return False
    if FOREIGN_MARKET_RE.search(hay) and not INDIA_SIGNAL_RE.search(hay):
        return False
    host = urlparse(url).netloc.lower() if url.startswith("http") else ""
    if host.endswith(".in") or ".co.in" in host:
        return True
    if re.search(r"reddit\.com/r/indian", url, re.I):
        return True
    return bool(INDIA_SIGNAL_RE.search(hay) or (geography and geography in INDIA_PLACES))


def _india_gate(result: Classification, text: str, url: str) -> Classification:
    if result.is_lead and not is_india_target(text, url, result.geography, result.company):
        result.is_lead = False
        result.critique = result.critique or "Not an India-market request."
        result.provider = f"{result.provider}+india-filter"
    return result


_HISTORICAL_RE = re.compile(
    r"\b(recap|case study|wrapped up|we worked with|completed campaign|last year|already ended|campaign recap)\b",
    re.I,
)
_CURRENT_ASK_RE = re.compile(r"\b(looking for|need|wanted|hiring|this month|upcoming|next week)\b", re.I)
_EDU_RE = re.compile(r"\b(how brands|guide to|tips for|in 20\d\d|what is influencer)\b", re.I)
_CREATOR_SIDE_RE = re.compile(
    r"\b(i(?:'m| am) a creator|seeking brand deals|want to collaborate with brands|looking for brand deals)\b",
    re.I,
)


def _critic_pass(result: Classification, text: str) -> Classification:
    """Second pass: strongest reason this classification could be wrong."""
    if result.confidence <= 0:
        result.confidence = _default_confidence(result)
    if not result.is_lead:
        return result
    reasons: list[str] = []
    if _HISTORICAL_RE.search(text) and not _CURRENT_ASK_RE.search(text):
        reasons.append("Looks like a completed campaign recap, not an active request.")
    if _EDU_RE.search(text) and not _CURRENT_ASK_RE.search(text):
        reasons.append("Educational article, not a buyer asking.")
    if _CREATOR_SIDE_RE.search(text):
        reasons.append("Creator looking for brand deals, not a brand asking.")
    if reasons:
        result.critique = reasons[0]
        result.is_lead = False
        result.confidence = min(result.confidence, 0.4)
        result.provider = f"{result.provider}+critic"
    elif not result.reasoning:
        result.reasoning = "Explicit creator/influencer request with no historical or educational tell."
    return result


def _default_confidence(result: Classification) -> float:
    if not result.is_lead:
        return 0.35
    return {"high": 0.88, "medium": 0.72, "low": 0.55}.get(result.intent_strength, 0.65)


def _confidence_gate(result: Classification, text: str, url: str) -> Classification:
    result = _india_gate(result, text, url)
    if result.confidence <= 0:
        result.confidence = _default_confidence(result)
    if result.is_lead and result.confidence < 0.60:
        result.is_lead = False
        result.critique = result.critique or "Confidence below 0.60 — archived."
        result.provider = f"{result.provider}+low-confidence"
    return result


def _parse_confidence(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number / 100 if number > 1 else max(0.0, min(number, 1.0))


def _guess_geo(text: str) -> str:
    for place in INDIA_PLACES:
        if re.search(rf"\b{re.escape(place)}\b", text, re.I):
            return "India" if place in {"Indian", "Bharat"} else place
    return ""


def _guess_industry(text: str) -> str:
    lower = text.lower()
    for needle, label in INDUSTRY_HINTS.items():
        if needle in lower:
            return label
    return ""


def _guess_company(text: str) -> str:
    quoted = re.search(r"[\"“]([A-Za-z0-9][^\"”]{1,50})[\"”]", text)
    if quoted:
        name = _clean_brand(quoted.group(1))
        if name:
            return name
    for pattern in (
        r"(?:i am |i'm |i’m )?(?:the )?(?:founder|co-?founder|ceo|owner|director)\s+of\s+[\"“']?([^\"”'\n,.]{2,50})",
        r"(?:my|our)\s+(?:brand|company|app|startup|product)\s+(?:is|called|named)?\s*[\"“']?([A-Za-z0-9][^\"”'\n,.]{1,50})",
        r"\b(?:at|from)\s+([A-Z][A-Za-z0-9&']+(?:\s+[A-Z][A-Za-z0-9&']+){0,2})\b",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            name = _clean_brand(match.group(1))
            if name:
                return name
    for match in COMPANY_RE.finditer(text):
        name = _clean_brand(match.group(1))
        if name:
            return name
    return ""


def _company_from_email(text: str) -> str:
    decoded = re.sub(r"\s*(?:\[at\]|\(at\))\s*", "@", text, flags=re.I)
    for email in re.findall(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", decoded, flags=re.I):
        host = email.rsplit("@", 1)[-1].lower()
        if host in {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"}:
            continue
        brand = host.split(".")[0]
        if brand in {"www", "mail", "email", "hello", "info", "support"}:
            continue
        name = _clean_brand(brand.replace("-", " ").title())
        if name:
            return name
    return ""


def _clean_brand(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" .,-'\"“”")
    name = re.sub(r"^(the|a|an)\s+", "", name, flags=re.I)
    if len(name) < 2 or len(name) > 48:
        return ""
    first = name.split()[0]
    if first in BAD_COMPANY or name in BAD_COMPANY:
        return ""
    if re.search(r"looking for|influencer|creator|anyone|please|promote", name, re.I):
        return ""
    if name == name.lower():
        name = name.title()
    return name


def _best_evidence(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    ranked: list[tuple[int, str]] = []
    for sentence in sentences:
        clean = sentence.strip().strip('"')
        if len(clean) < 20:
            continue
        score = 0
        if ASK_RE.search(clean):
            score += 3
        if CREATOR_RE.search(clean) or AGENCY_RE.search(clean):
            score += 3
        if GENERIC_RE.search(clean):
            score -= 2
        if score:
            ranked.append((score, clean[:280]))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked else text[:240].strip()


def _build_prompt(text: str, lessons: list | None = None, rules: list[str] | None = None) -> str:
    from app.pipeline.memory import prompt_block, retrieve_pack

    excerpt = text[:4000]
    memory = prompt_block(retrieve_pack(text, lessons or [], rules))
    return f"""You classify public text for an influencer-marketing agency.
Work through these checks, then return JSON only:
1. Is there any plausible influencer-marketing intent?
2. Is the intent current, or historical / a recap?
3. Is the writer representing a company or brand (not a creator seeking deals)?
4. Is there a concrete campaign or request?
5. Compare with the similar accepted and rejected examples below.
6. Return the final classification plus a short reasoning_summary (not hidden chain-of-thought).
is_lead is true only when a brand or founder in India is currently asking for
influencers, creators, UGC, or brand ambassadors. Not a lead if the market is the US, UK, EU,
UAE, or anywhere outside India. An influencer/creator agency
selling its own services is not a lead. Generic discussion is not a lead.
company is the brand name. Strip leading The/A/An. Use founder-of, quotes, @handles,
Reddit u/ names, or the email domain. Empty string if you would be guessing.
intent_type must be one of: {", ".join(INTENT_TYPES)}.
evidence must be a verbatim quote from the text. Do not invent facts.
confidence is 0-1.
{memory}
TEXT:
{excerpt}
"""


def _parse_model_json(raw: str) -> dict:
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            return json.loads(match.group(0))
    return {}


def _classification_from_dict(data: dict, provider: str) -> Classification:
    merged = {**LEAD_SCHEMA, **data}
    strength = str(merged.get("intent_strength") or "low")
    is_lead = bool(merged.get("is_lead"))
    confidence = _parse_confidence(merged.get("confidence")) or (
        {"high": 0.88, "medium": 0.72, "low": 0.55}.get(strength, 0.65) if is_lead else 0.35
    )
    return Classification(
        is_lead=is_lead,
        intent_type=str(merged.get("intent_type") or ""),
        intent_strength=strength,
        campaign_type=str(merged.get("campaign_type") or ""),
        geography=str(merged.get("geography") or ""),
        urgency=str(merged.get("urgency") or "low"),
        company=str(merged.get("company") or ""),
        industry=str(merged.get("industry") or ""),
        evidence=str(merged.get("evidence") or ""),
        provider=provider,
        confidence=confidence,
        reasoning=str(merged.get("reasoning_summary") or ""),
    )
