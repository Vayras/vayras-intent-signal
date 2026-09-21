"""RSS discovery. Stdlib XML — no feedparser."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.providers.search import SearchHit, platform_from_url

# India marketing / D2C / startup news. Failures are ignored per feed.
FEEDS = [
    "https://www.socialsamosa.com/feed/",
    "https://yourstory.com/feed",
    "https://inc42.com/feed/",
    "https://www.adgully.com/feed/",
    "https://www.medianews4u.com/feed/",
]


def rss_hits(limit: int = 40) -> list[SearchHit]:
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for feed in FEEDS:
        if len(hits) >= limit:
            break
        try:
            for hit in _parse_feed(feed):
                if hit.url in seen:
                    continue
                seen.add(hit.url)
                hits.append(hit)
                if len(hits) >= limit:
                    break
        except Exception:
            continue
    return hits


def _parse_feed(url: str) -> list[SearchHit]:
    with httpx.Client(timeout=12.0, headers={"User-Agent": settings.user_agent}, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    return _hits_from_xml(response.content)


def _hits_from_xml(raw: bytes) -> list[SearchHit]:
    root = ET.fromstring(raw)
    items: list[SearchHit] = []
    for node in list(root.iter()):
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag not in {"item", "entry"}:
            continue
        link = _child_text(node, "link") or _child_attr(node, "link", "href")
        title = _child_text(node, "title") or link
        snippet = _child_text(node, "description") or _child_text(node, "summary") or ""
        if not link or not link.startswith("http"):
            continue
        host = urlparse(link).netloc.lower()
        items.append(
            SearchHit(
                url=link,
                title=title[:300],
                snippet=snippet[:400],
                platform=platform_from_url(link) if host else "news",
            )
        )
    return items


def _child_text(node: ET.Element, name: str) -> str:
    for child in node:
        if child.tag.rsplit("}", 1)[-1].lower() == name:
            return (child.text or "").strip()
    return ""


def _child_attr(node: ET.Element, name: str, attr: str) -> str:
    for child in node:
        if child.tag.rsplit("}", 1)[-1].lower() == name:
            return (child.attrib.get(attr) or child.attrib.get(f"{{{child.tag.split('}')[0][1:]}}}{attr}") or "").strip()
    return ""
