from app.config import settings
from app.pipeline.taxonomy import INDUSTRIES

BASE_PHRASES = [
    "looking for influencers",
    "looking for creators",
    "need influencers",
    "need creators",
    "seeking influencers",
    "seeking creators",
    "influencers wanted",
    "creators wanted",
    "UGC creators wanted",
    "need UGC creators",
    "looking for UGC creators",
    "user generated content creators",
    "looking for influencer marketing",
    "looking for influencer marketing agency",
    "need influencer marketing agency",
    "recommend influencer marketing agency",
    "creator marketing agency",
    "creator campaign",
    "influencer campaign",
    "paid collaboration creators",
    "paid collab influencers",
    "micro influencers",
    "nano influencers",
    "brand ambassador",
    "campus ambassador",
    "creator partnerships",
    "influencer collaboration",
    "brand collaboration",
    "hiring influencer marketing manager",
    "hiring creator partnerships manager",
    "hiring social media influencer manager",
    "need Indian beauty creators",
    "does anyone know a good influencer marketing agency",
]

CITIES = [
    "Mumbai",
    "Bengaluru",
    "Bangalore",
    "Delhi",
    "New Delhi",
    "Gurgaon",
    "Gurugram",
    "Noida",
    "Hyderabad",
    "Pune",
    "Chennai",
    "Kolkata",
    "Jaipur",
    "Ahmedabad",
    "Surat",
    "Indore",
    "Kochi",
    "Goa",
]

PUBLIC_SOURCES = [
    "linkedin.com",
    "linkedin.com/company",
    "linkedin.com/in",
    "linkedin.com/posts",
    "linkedin.com/jobs",
    "reddit.com",
    "reddit.com/r/influencermarketing",
    "instagram.com",
    "facebook.com",
    "x.com",
    "wellfound.com",
    "naukri.com",
    "indeed.com",
    "lever.co",
    "greenhouse.io",
    "workable.com",
]


def generate_queries(
    country: str | None = None,
    industries: list[str] | None = None,
    avoid: list[str] | None = None,
) -> list[str]:
    country = country or settings.default_country
    industries = industries or INDUSTRIES
    queries = [f'"{phrase}" {country}' for phrase in BASE_PHRASES]
    extras = [
        f'"{phrase}" {industry} {country}'
        for phrase in (
            "looking for creators",
            "looking for influencers",
            "need UGC creators",
            "brand ambassador",
            "influencer marketing agency",
        )
        for industry in industries
    ]
    city_queries = [
        f'"{phrase}" {city}'
        for phrase in ("looking for influencers", "looking for creators", "need UGC creators", "brand ambassador")
        for city in CITIES
    ]
    source_queries = [
        f'"{phrase}" {country} site:{source}'
        for phrase in (
            "looking for influencers",
            "looking for creators",
            "need UGC creators",
            "influencer marketing agency",
            "brand ambassador",
            "creator partnerships",
            "hiring influencer marketing",
        )
        for source in PUBLIC_SOURCES
    ]
    campaign_queries = [
        f'"{campaign}" "{phrase}" {country}'
        for campaign in (
            "product launch",
            "new launch",
            "festive campaign",
            "Diwali campaign",
            "wedding season",
            "app launch",
            "store launch",
        )
        for phrase in ("creators", "influencers", "UGC")
    ]
    wide = [
        f'"{phrase}" {industry} {city}'
        for phrase in BASE_PHRASES
        for industry in industries
        for city in CITIES
    ]
    stock = list(
        dict.fromkeys(
            _priority_queries(country) + queries + extras + city_queries + source_queries + campaign_queries + wide
        )
    )
    if avoid:
        lowered = {name.lower() for name in avoid if name}
        stock = [q for q in stock if not any(name in q.lower() for name in lowered)]
    return _rotate(stock, settings.scan_query_limit)


def _priority_queries(country: str) -> list[str]:
    brands = (
        "beauty brand",
        "skincare brand",
        "makeup brand",
        "cosmetics brand",
        "D2C brand",
        "D2C beauty",
        "direct to consumer brand",
    )
    roles = (
        "founder",
        "CMO",
        "head of marketing",
        "influencer marketing manager",
        "creator partnerships",
    )
    out: list[str] = []
    for brand in brands:
        out.append(f'"{brand}" {country}')
        out.append(f'"{brand}" influencer marketing {country}')
        out.append(f'"{brand}" {country} site:linkedin.com/company')
        out.append(f'"{brand}" {country} site:linkedin.com')
    for role in roles:
        out.append(f'{role} "beauty brand" {country} site:linkedin.com/in')
        out.append(f'{role} D2C {country} site:linkedin.com/in')
    out.extend(
        [
            f'"looking for influencers" beauty {country} site:linkedin.com',
            f'"looking for creators" D2C {country} site:linkedin.com',
            f'"UGC" beauty brand {country} site:linkedin.com',
            f'hiring "influencer marketing" beauty {country} site:linkedin.com/jobs',
            f'hiring "creator partnerships" D2C {country} site:linkedin.com/jobs',
        ]
    )
    return out


_offset = 0


def _rotate(pool: list[str], n: int) -> list[str]:
    global _offset
    if not pool or n >= len(pool):
        return pool[:n]
    start = _offset % len(pool)
    _offset = start + n
    return (pool[start:] + pool[:start])[:n]


if __name__ == "__main__":
    _offset = 0
    assert _rotate(list("abcd"), 2) == ["a", "b"]
    assert _rotate(list("abcd"), 2) == ["c", "d"]
    print("ok")
