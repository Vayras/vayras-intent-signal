from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from app.providers.search import SearchHit

import httpx
from bs4 import BeautifulSoup

from app.config import FIXTURES_DIR, settings

_robot_cache: dict[str, RobotFileParser] = {}


@dataclass
class Page:
    url: str
    domain: str
    title: str
    text: str
    content_hash: str
    platform: str


def page_from_hit(hit: SearchHit) -> Page | None:
    """Fetch the page when robots allow it; otherwise use the public search snippet."""
    if hit.url.startswith("fixture://"):
        return fetch_page(hit.url, hit.platform)
    host = urlparse(hit.url).netloc
    page = scrape_social(hit) if is_social_host(host) else fetch_page(hit.url, hit.platform)
    if page and len(page.text) >= 40:
        return page
    text = f"{hit.title}. {hit.snippet}".strip()
    if len(text) < 40:
        return None
    return Page(
        url=hit.url,
        domain=host,
        title=hit.title,
        text=text[:4000],
        content_hash=_hash_text(text),
        platform=hit.platform,
    )


SOCIAL_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "fb.com",
    "www.fb.com",
    "threads.com",
    "www.threads.com",
    "threads.net",
    "www.threads.net",
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "redd.it",
    "twitter.com",
    "www.twitter.com",
    "x.com",
    "www.x.com",
    "linkedin.com",
    "www.linkedin.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "tiktok.com",
    "www.tiktok.com",
}

CONTACT_LINK_HINTS = ("contact", "about", "team", "people", "our-team", "company", "connect")


@dataclass
class Document:
    url: str
    domain: str
    title: str
    text: str
    emails: list[str]
    contact_links: list[str]
    linkedin_url: str | None
    instagram_url: str | None


def is_social_host(host: str) -> bool:
    host = host.lower().removeprefix("www.")
    return host in {item.removeprefix("www.") for item in SOCIAL_HOSTS} or host in SOCIAL_HOSTS


def scrape_social(hit: SearchHit) -> Page | None:
    """Public page only. No login, no wall bypass. Login chrome is dropped."""
    chunks: list[str] = []
    title = hit.title
    host = urlparse(hit.url).netloc.lower()

    reddit_text = ""
    if "reddit.com" in host or host.endswith("redd.it"):
        reddit = _fetch_reddit(hit.url)
        if reddit:
            title = reddit.get("title") or title
            reddit_text = reddit.get("text") or ""
            chunks.append(reddit_text)

    if "youtube.com" in host or host.endswith("youtu.be"):
        chunks.append(_fetch_youtube_oembed(hit.url) or "")

    if len(reddit_text) < 80:
        crawled = _crawl4ai(hit.url)
        html = (crawled[0] if crawled else None) or _fetch_raw(hit.url)
        if html:
            page_title, page_text = text_from_social_html(hit.url, html)
            title = title or page_title
            chunks.append(page_text)
        if crawled and crawled[1]:
            chunks.append(crawled[1])

    chunks.append(f"{hit.title}. {hit.snippet}".strip())
    text = _merge_text(*chunks)
    if len(text) < 40:
        return None
    return Page(
        url=hit.url,
        domain=urlparse(hit.url).netloc,
        title=title or hit.title,
        text=text[:20000],
        content_hash=_hash_text(text),
        platform=hit.platform,
    )


def text_from_social_html(url: str, html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = _meta(soup, "og:title") or (soup.title.get_text(" ", strip=True) if soup.title else url)
    desc = _meta(soup, "og:description") or _meta(soup, "twitter:description") or _meta(soup, "description")
    author = _meta(soup, "author") or _meta(soup, "article:author") or _meta(soup, "og:site_name")
    ld = _json_ld_text(soup)
    emails = _emails_from_html(soup, html)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    visible = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    if _looks_like_login_wall(visible):
        visible = ""
    lines = [item for item in (f"Author: {author}" if author else "", desc, ld, visible[:12000]) if item]
    if emails:
        lines.append("Emails: " + ", ".join(emails))
    handles = re.findall(r"(?<![A-Za-z0-9])@([A-Za-z0-9._]{2,30})", " ".join(lines) + " " + url)
    if handles:
        uniq = list(dict.fromkeys(h.strip("._") for h in handles if h.lower() not in {"instagram", "facebook", "youtube"}))
        if uniq:
            lines.append("Handles: " + " ".join("@" + h for h in uniq[:8]))
    return title, _merge_text(*lines)


def reddit_watch_hits(subreddits: str | None = None, limit: int = 25) -> list[SearchHit]:
    hits: list[SearchHit] = []
    seen: set[str] = set()
    names = [item.strip().lstrip("r/") for item in (subreddits or settings.reddit_subreddits).split(",") if item.strip()]
    for sub in names:
        for sort in ("new", "hot"):
            for hit in listing_hits_from_json(_fetch_subreddit_listing(sub, sort, limit), sub):
                if hit.url in seen:
                    continue
                seen.add(hit.url)
                hits.append(hit)
    return hits


def listing_hits_from_json(payload, subreddit: str = "") -> list[SearchHit]:
    children = (payload or {}).get("data", {}).get("children", []) if isinstance(payload, dict) else []
    hits: list[SearchHit] = []
    for child in children:
        post = child.get("data") or {}
        permalink = post.get("permalink") or ""
        if not permalink:
            continue
        url = permalink if permalink.startswith("http") else f"https://www.reddit.com{permalink}"
        title = post.get("title") or url
        snippet = (post.get("selftext") or title)[:400]
        hits.append(SearchHit(url=url.split("?")[0], title=title, snippet=snippet, platform="reddit"))
    _ = subreddit
    return hits


def text_from_reddit_json(payload) -> dict[str, str]:
    post = {}
    comments: list[str] = []
    listing = payload if isinstance(payload, list) else [payload]
    if listing:
        children = (listing[0] or {}).get("data", {}).get("children", [])
        if children:
            post = children[0].get("data") or {}
    if len(listing) > 1:
        for child in (listing[1] or {}).get("data", {}).get("children", [])[:8]:
            body = (child.get("data") or {}).get("body") or ""
            author = (child.get("data") or {}).get("author") or ""
            if body and author != "AutoModerator":
                comments.append(f"{author}: {body}" if author else body)
    title = post.get("title") or ""
    author = post.get("author") or ""
    body = post.get("selftext") or post.get("body") or ""
    flair = post.get("link_flair_text") or ""
    sub = post.get("subreddit") or ""
    lines = [
        f"Author: u/{author}" if author else "",
        f"Subreddit: r/{sub}" if sub else "",
        f"Flair: {flair}" if flair else "",
        title,
        body,
        ("Comments:\n" + "\n".join(comments)) if comments else "",
    ]
    return {"title": title, "text": _merge_text(*lines)}


def fetch_document(url: str) -> Document | None:
    """Fetch public HTML. Keeps footer/nav because emails often live there."""
    if url.startswith("fixture://") or not url.startswith("http"):
        return None
    if not _robots_allowed(url):
        return None
    crawled = _crawl4ai(url)
    html = (crawled[0] if crawled else None) or _fetch_raw(url)
    if not html:
        return None
    return parse_document(url, html)


def parse_document(url: str, html: str) -> Document:
    soup = BeautifulSoup(html, "lxml")
    emails = _emails_from_html(soup, html)
    linkedin = _first_href(soup, "linkedin.com/company") or _first_href(soup, "linkedin.com/in")
    instagram = _first_href(soup, "instagram.com/")
    contact_links = _contact_links(soup, url)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = _extract_title(html, url) or (soup.title.get_text(" ", strip=True) if soup.title else url)
    text = (_extract_text(html, url) or re.sub(r"\s+", " ", soup.get_text(" ", strip=True)))[:20000]
    return Document(
        url=url,
        domain=urlparse(url).netloc,
        title=title,
        text=text,
        emails=emails,
        contact_links=contact_links,
        linkedin_url=linkedin,
        instagram_url=instagram,
    )


def fetch_page(url: str, platform: str = "") -> Page | None:
    if url.startswith("fixture://"):
        return _from_fixture(url, platform)
    crawled = _crawl4ai(url)
    if crawled:
        html, markdown, title = crawled
        page = _from_html(url, html, platform, markdown, title)
        if page and len(page.text) >= 40:
            return page
    html = _fetch_raw(url)
    return _from_html(url, html, platform) if html else None


def _from_fixture(url: str, platform: str) -> Page | None:
    slug = url.removeprefix("fixture://")
    path = FIXTURES_DIR / f"{slug}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    text = data["text"]
    return Page(
        url=url,
        domain=data.get("domain") or slug,
        title=data.get("title") or slug,
        text=text,
        content_hash=_hash_text(text),
        platform=platform or data.get("platform") or "forum",
    )


def _from_html(url: str, html: str, platform: str, markdown: str = "", title_hint: str = "") -> Page:
    extracted = (markdown or "").strip() or _extract_text(html, url)
    if is_social_host(urlparse(url).netloc):
        title, text = text_from_social_html(url, html)
        title = title_hint or title
        text = _merge_text(text, extracted)
    else:
        soup = BeautifulSoup(html, "lxml")
        og = _meta(soup, "og:description") or _meta(soup, "description")
        title = title_hint or _extract_title(html, url) or _meta(soup, "og:title") or (soup.title.get_text(" ", strip=True) if soup.title else url)
        if extracted:
            text = _merge_text(og, extracted)
        else:
            for tag in soup(["script", "style", "noscript", "nav", "footer"]):
                tag.decompose()
            text = _merge_text(og, re.sub(r"\s+", " ", soup.get_text(" ", strip=True)))
    return Page(
        url=url,
        domain=urlparse(url).netloc,
        title=title,
        text=text[:20000],
        content_hash=_hash_text(text),
        platform=platform,
    )


def _fetch_raw(url: str) -> str | None:
    if not url.startswith("http") or not _robots_allowed(url):
        return None
    try:
        with httpx.Client(
            timeout=settings.crawl_timeout_seconds,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return None
            return response.text
    except Exception:
        return None


def _fetch_subreddit_listing(subreddit: str, sort: str, limit: int):
    path = f"/r/{subreddit}/{sort}.json"
    for host in ("www.reddit.com", "old.reddit.com"):
        raw = _reddit_public_get(f"https://{host}{path}?limit={limit}&raw_json=1")
        if not raw:
            raw = _crawl_html(f"https://{host}{path}?limit={limit}&raw_json=1")
        if not raw:
            continue
        try:
            data = json.loads(_json_from_rendered(raw))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("data"):
            return data
    html = _crawl_html(f"https://old.reddit.com/r/{subreddit}/{sort}/")
    if html:
        return _listing_payload_from_old_reddit(html, subreddit)
    return {}


def _fetch_reddit(url: str) -> dict[str, str] | None:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path or path.endswith(".json"):
        json_url = url
    else:
        json_url = f"{parsed.scheme}://{parsed.netloc}{path}.json"
    raw = _reddit_public_get(json_url)
    if not raw:
        return None
    try:
        return text_from_reddit_json(json.loads(raw))
    except json.JSONDecodeError:
        return None


def _json_from_rendered(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("{") or raw.startswith("["):
        return raw
    match = re.search(r"(<pre[^>]*>)?(\{.*\}|\[.*\])(</pre>)?", raw, re.S)
    return match.group(2) if match else raw


def _listing_payload_from_old_reddit(html: str, subreddit: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    children = []
    for thing in soup.select(".thing.link"):
        permalink = thing.get("data-permalink") or ""
        title_el = thing.select_one("a.title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        body_el = thing.select_one(".usertext-body")
        body = body_el.get_text(" ", strip=True) if body_el else ""
        if not permalink or not title:
            continue
        children.append({"data": {"title": title, "selftext": body, "permalink": permalink, "subreddit": subreddit}})
    return {"data": {"children": children}} if children else {}


_crawl_local = threading.local()


def _crawl_html(url: str) -> str | None:
    got = _crawl4ai(url)
    return got[0] if got else None


def _markdown_from_result(result) -> str:
    md = getattr(result, "markdown", None)
    if md is None:
        return ""
    if isinstance(md, str):
        return md.strip()
    for attr in ("fit_markdown", "raw_markdown", "markdown"):
        val = getattr(md, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return str(md).strip()


def _crawl4ai(url: str) -> tuple[str, str, str] | None:
    """Crawl4AI render. Returns html, markdown, title. No API key."""
    if not url.startswith("http"):
        return None
    # ponytail: Reddit/social robots is Disallow:/; public posts still need a render
    if not is_social_host(urlparse(url).netloc) and not _robots_allowed(url):
        return None
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError:
        return None

    async def _arun(crawler):
        result = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=int(max(settings.crawl_timeout_seconds, 25) * 1000),
            ),
        )
        if not result or not getattr(result, "success", False):
            return None
        html = result.html or result.cleaned_html or ""
        markdown = _markdown_from_result(result)
        meta = getattr(result, "metadata", None) or {}
        title = meta.get("title", "") if isinstance(meta, dict) else ""
        if not html and not markdown:
            return None
        return html, markdown, title or ""

    try:
        loop = getattr(_crawl_local, "loop", None)
        crawler = getattr(_crawl_local, "crawler", None)
        if loop is None or crawler is None:
            loop = asyncio.new_event_loop()
            crawler = AsyncWebCrawler(
                config=BrowserConfig(headless=True, verbose=False, user_agent=settings.user_agent)
            )
            loop.run_until_complete(crawler.start())
            _crawl_local.loop = loop
            _crawl_local.crawler = crawler
        return loop.run_until_complete(_arun(crawler))
    except Exception:
        return None


def _extract_text(html: str, url: str = "") -> str:
    """trafilatura article text. No API key."""
    if not html:
        return ""
    try:
        import trafilatura

        text = trafilatura.extract(html, url=url or None, include_comments=True, favor_recall=True)
    except Exception:
        return ""
    return re.sub(r"\s+", " ", text).strip() if text else ""


def _extract_title(html: str, url: str = "") -> str:
    if not html:
        return ""
    try:
        import trafilatura

        meta = trafilatura.extract_metadata(html, default_url=url or None)
        title = getattr(meta, "title", None) if meta else None
        return title.strip() if title else ""
    except Exception:
        return ""


def _reddit_public_get(url: str) -> str | None:
    # ponytail: Reddit robots is Disallow:/; public .json is the read API for r/influencermarketing
    try:
        with httpx.Client(
            timeout=settings.crawl_timeout_seconds,
            headers={
                "User-Agent": "IntentRadar/0.1 (public subreddit watch; +https://localhost)",
                "Accept": "application/json",
            },
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return None
            return response.text
    except Exception:
        return None


def _fetch_youtube_oembed(url: str) -> str:
    try:
        with httpx.Client(timeout=settings.crawl_timeout_seconds, headers={"User-Agent": settings.user_agent}) as client:
            response = client.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"})
            if response.status_code >= 400:
                return ""
            data = response.json()
    except Exception:
        return ""
    title = data.get("title") or ""
    author = data.get("author_name") or ""
    return _merge_text(f"Author: {author}" if author else "", title)


def _meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return (tag.get("content") or "").strip() if tag else ""


def _json_ld_text(soup: BeautifulSoup) -> str:
    bits: list[str] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("headline", "name", "description", "articleBody", "text", "caption"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    bits.append(val.strip())
            author = item.get("author")
            if isinstance(author, dict) and author.get("name"):
                bits.append(f"Author: {author['name']}")
            elif isinstance(author, str) and author.strip():
                bits.append(f"Author: {author}")
    return _merge_text(*bits)


def _looks_like_login_wall(text: str) -> bool:
    lower = text.lower()
    return len(text) < 500 and any(
        needle in lower for needle in ("log in", "sign up", "create new account", "see this post in", "allow cookies")
    )


def _merge_text(*parts: str) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        clean = re.sub(r"\s+", " ", part or "").strip()
        if len(clean) < 8:
            continue
        key = clean.lower()[:220]
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return "\n".join(out)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _robots_allowed(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = _robot_cache.get(robots_url)
    if parser is None:
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            with httpx.Client(timeout=settings.crawl_timeout_seconds, headers={"User-Agent": settings.user_agent}) as client:
                response = client.get(robots_url)
            if response.status_code >= 400:
                return True
            parser.parse(response.text.splitlines())
        except Exception:
            return True
        _robot_cache[robots_url] = parser
    try:
        return parser.can_fetch(settings.user_agent, url)
    except Exception:
        return True


def fixture_dir() -> Path:
    return FIXTURES_DIR


def _emails_from_html(soup: BeautifulSoup, html: str) -> list[str]:
    found: list[str] = []
    for tag in soup.select('a[href^="mailto:"]'):
        href = tag.get("href") or ""
        found.append(href.split(":", 1)[-1].split("?")[0])
    obfuscated = re.sub(r"\s*(?:\[at\]|\(at\))\s*", "@", html, flags=re.I)
    obfuscated = re.sub(r"\s*(?:\[dot\]|\(dot\))\s*", ".", obfuscated, flags=re.I)
    found.extend(re.findall(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", obfuscated, flags=re.I))
    clean: list[str] = []
    seen: set[str] = set()
    for raw in found:
        email = raw.strip().strip(".,;<>").lower()
        if email in seen or email.endswith((".png", ".jpg", ".gif", ".webp")):
            continue
        if any(part in email for part in ("example.com", "sentry", "wixpress", "noreply", "godaddy")):
            continue
        seen.add(email)
        clean.append(email)
    return clean[:12]


def _first_href(soup: BeautifulSoup, needle: str) -> str | None:
    for tag in soup.select("a[href]"):
        href = tag.get("href") or ""
        if needle in href.lower() and href.startswith("http"):
            return href.split("?")[0]
    return None


def _contact_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    host = urlparse(base_url).netloc
    links: list[str] = []
    seen: set[str] = set()
    for tag in soup.select("a[href]"):
        href = tag.get("href") or ""
        label = f"{href} {tag.get_text(' ', strip=True)}".lower()
        if not any(hint in label for hint in CONTACT_LINK_HINTS):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != host:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute.split("#")[0])
    return links[:4]
