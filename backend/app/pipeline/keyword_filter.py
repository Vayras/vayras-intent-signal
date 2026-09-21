from app.pipeline.taxonomy import KEYWORD_TERMS

_DIRECTORY = ("beauty", "skincare", "makeup", "cosmetics", "d2c", "direct-to-consumer", "direct to consumer")


def keyword_hit(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in KEYWORD_TERMS)


def directory_hit(url: str = "", text: str = "") -> bool:
    host = url.lower()
    if any(part in host for part in ("linkedin.com/company", "linkedin.com/in", "linkedin.com/posts")):
        return True
    hay = f"{url} {text}".lower()
    if not any(mark in hay for mark in _DIRECTORY):
        return False
    return "india" in hay or ".in/" in hay or "d2c" in hay


def hit_terms(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in KEYWORD_TERMS if term in lower]
