from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import FIXTURES_DIR, settings


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    platform: str


class SearchProvider:
    name = "SearchProvider"

    def search(self, query: str, limit: int = 8, **_kwargs) -> list[SearchHit]:
        raise NotImplementedError

    def status(self) -> tuple[bool, str]:
        raise NotImplementedError


class NoSearchProvider(SearchProvider):
    name = "NoLiveSearch"

    def search(self, query: str, limit: int = 8, **_kwargs) -> list[SearchHit]:
        raise RuntimeError("No live search provider configured. Set SEARXNG_URL to collect real leads.")

    def status(self) -> tuple[bool, str]:
        return False, "Set SEARXNG_URL to collect real leads. Fixture search is disabled."


class SearxngSearchProvider(SearchProvider):
    name = "SearXNG"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def search(self, query: str, limit: int = 8, categories: str = "general") -> list[SearchHit]:
        with httpx.Client(timeout=15.0, headers={"User-Agent": settings.user_agent}) as client:
            response = client.get(
                f"{self.base_url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "language": "en",
                    "categories": categories,
                    "safesearch": 0,
                },
            )
            response.raise_for_status()
            payload = response.json()
        hits: list[SearchHit] = []
        for item in payload.get("results", [])[:limit]:
            url = item.get("url") or ""
            if not url.startswith("http"):
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=item.get("title") or url,
                    snippet=item.get("content") or "",
                    platform=platform_from_url(url),
                )
            )
        return hits

    def status(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=4.0) as client:
                response = client.get(f"{self.base_url}/healthz")
                if response.status_code >= 400:
                    response = client.get(self.base_url, params={"q": "india", "format": "json"})
            return response.status_code < 500, f"{self.base_url} ({response.status_code})"
        except Exception as exc:  # pragma: no cover - network
            return False, str(exc)


class FixtureSearchProvider(SearchProvider):
    """Local public-style pages so the pipeline works with zero paid APIs."""

    name = "FixtureIndex"

    def __init__(self, fixtures_dir: Path = FIXTURES_DIR):
        self.fixtures_dir = fixtures_dir
        self._index = _load_fixture_index(fixtures_dir)

    def search(self, query: str, limit: int = 8, **_kwargs) -> list[SearchHit]:
        tokens = {token.lower() for token in query.replace('"', " ").split() if len(token) > 2}
        scored: list[tuple[int, SearchHit]] = []
        for hit in self._index:
            hay = f"{hit.title} {hit.snippet} {hit.url}".lower()
            score = sum(1 for token in tokens if token in hay)
            if score:
                scored.append((score, hit))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in scored[:limit]] or self._index[:limit]

    def status(self) -> tuple[bool, str]:
        return True, f"{len(self._index)} fixture pages on disk"


class CompositeSearchProvider(SearchProvider):
    name = "CompositeSearch"

    def __init__(self, providers: list[SearchProvider]):
        self.providers = providers

    def search(self, query: str, limit: int = 8, **kwargs) -> list[SearchHit]:
        seen: set[str] = set()
        hits: list[SearchHit] = []
        for provider in self.providers:
            try:
                for hit in provider.search(query, limit=limit, **kwargs):
                    if hit.url in seen:
                        continue
                    seen.add(hit.url)
                    hits.append(hit)
                    if len(hits) >= limit:
                        return hits
            except Exception:
                continue
        return hits

    def status(self) -> tuple[bool, str]:
        parts = []
        any_active = False
        for provider in self.providers:
            active, detail = provider.status()
            any_active = any_active or active
            parts.append(f"{provider.name}: {detail}")
        return any_active, " | ".join(parts)


def get_search_provider() -> SearchProvider:
    providers: list[SearchProvider] = []
    if settings.searxng_url:
        providers.append(SearxngSearchProvider(settings.searxng_url))
    if settings.demo_mode or not providers:
        if settings.demo_mode:
            providers.append(FixtureSearchProvider())
        else:
            providers.append(NoSearchProvider())
    return providers[0] if len(providers) == 1 else CompositeSearchProvider(providers)


def searx_categories(query: str) -> str:
    # ponytail: SearXNG's "social media" category is Lemmy/Mastodon/Tootfinder only —
    # no Reddit/Instagram/LinkedIn/X engine exists, so site: queries for those belong
    # in "general" where the real web engines (brave/duckduckgo/google) actually run.
    lower = query.lower()
    if any(token in lower for token in ("product launch", "new launch", "press", "yourstory", "inc42")):
        return "news"
    return "general"


def platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "reddit.com" in host or host.endswith("redd.it"):
        return "reddit"
    if "instagram.com" in host:
        return "instagram"
    if "facebook.com" in host or host.endswith("fb.com"):
        return "facebook"
    if "youtube.com" in host or host.endswith("youtu.be"):
        return "youtube"
    if "tiktok.com" in host:
        return "tiktok"
    if "threads.net" in host or "threads.com" in host:
        return "threads"
    if "linkedin.com" in host:
        return "linkedin"
    if "twitter.com" in host or host == "x.com" or host.endswith(".x.com"):
        return "x"
    if any(part in host for part in ("naukri", "indeed", "lever", "greenhouse", "wellfound")):
        return "job_board"
    if any(part in host for part in ("yourstory", "inc42", "techcrunch", "economictimes")):
        return "news"
    if host.startswith("forum") or "community" in host:
        return "forum"
    return "company_site"


def _load_fixture_index(fixtures_dir: Path) -> list[SearchHit]:
    index_path = fixtures_dir / "index.json"
    if not index_path.exists():
        return []
    raw = json.loads(index_path.read_text())
    hits = []
    for item in raw:
        hits.append(
            SearchHit(
                url=item["url"],
                title=item["title"],
                snippet=item["snippet"],
                platform=item.get("platform") or platform_from_url(item["url"]),
            )
        )
    return hits
