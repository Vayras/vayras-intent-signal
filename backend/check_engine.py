"""Small self-check for classifier + scoring. No fixtures, no network."""

from app.pipeline.keyword_filter import keyword_hit
from app.pipeline.score import score_lead
from app.providers.ai import (
    classify_text,
    extract_handles,
    heuristic_classify,
    is_agency_seller,
    is_india_target,
    is_target_brand,
    resolve_company_name,
)
from app.providers.email_check import EmailCheckProvider
from app.pipeline.crawl import listing_hits_from_json, parse_document, text_from_reddit_json, text_from_social_html
from app.providers.search import platform_from_url, searx_categories
from app.providers.enrichment import PublicWebEnrichment
from app.pipeline.memory import Lesson, remembered_reject, retrieve_pack
from app.pipeline.rss import _hits_from_xml
from app.providers.ai import Classification, _critic_pass


def test_high_intent_is_lead():
    text = "We are looking for Indian beauty creators for our upcoming launch."
    result = heuristic_classify(text)
    assert result.is_lead, result
    assert result.intent_type in {"LOOKING_FOR_CREATORS", "LOOKING_FOR_INFLUENCERS", "PRODUCT_LAUNCH"}
    assert result.evidence
    assert "looking for" in result.evidence.lower()
    score, reasons = score_lead(text, result)
    assert score >= 60, (score, reasons)
    assert reasons


def test_agency_ask():
    text = "Does anyone know a good influencer marketing agency for a snacks brand in Delhi?"
    result = heuristic_classify(text)
    assert result.is_lead
    assert result.intent_type == "NEEDS_INFLUENCER_AGENCY"


def test_generic_discussion_is_not_a_lead():
    text = (
        "Influencer marketing is growing. Our company works with influencers "
        "and we are interested in creator marketing as a long-term channel."
    )
    result = heuristic_classify(text)
    assert not result.is_lead, result


def test_keyword_gate():
    assert keyword_hit("Need UGC creators for an upcoming campaign.")
    assert not keyword_hit("Quarterly earnings beat estimates across retail.")


def test_marketplace_is_not_a_lead():
    text = "Find & Hire India Influencers on Collabstr. India's first influencer marketplace."
    result = heuristic_classify(text)
    assert not result.is_lead, result


def test_contact_extraction():
    text = "Priya Nair, CMO — priya.nair@orbitdesk.com looking for creators to promote our app."
    contacts = PublicWebEnrichment().discover(text, "fixture://orbit-launch")
    assert contacts
    assert contacts[0].email == "priya.nair@orbitdesk.com"
    assert contacts[0].job_title == "CMO"


def test_gated_classify_skips_model_on_noise():
    text = "Find & Hire India Influencers on Collabstr. India's first influencer marketplace."
    result = classify_text(text)
    assert not result.is_lead
    assert result.provider == "Heuristic"


def test_handle_extract():
    text = "@nynkaa is looking for UGC creators in Mumbai this month."
    assert extract_handles(text, "https://instagram.com/nynkaa/p/abc") == ["nynkaa"]


def test_email_missing():
    assert EmailCheckProvider().check(None) == "missing"
    assert EmailCheckProvider().check("not-an-email") == "missing"


def test_html_contact_page():
    html = """
    <html><body>
      <a href="mailto:hello@kalathread.com">Email us</a>
      <a href="/contact">Contact</a>
      <a href="https://linkedin.com/company/kala-thread">LinkedIn</a>
      <footer>Rhea Kapoor, Brand Manager — press [at] kalathread.com</footer>
    </body></html>
    """
    doc = parse_document("https://kalathread.com/", html)
    assert "hello@kalathread.com" in doc.emails
    assert "press@kalathread.com" in doc.emails
    assert any(link.endswith("/contact") for link in doc.contact_links)
    assert doc.linkedin_url
    contacts = PublicWebEnrichment().discover(
        "Rhea Kapoor, Brand Manager — press [at] kalathread.com",
        "https://kalathread.com/contact",
    )
    assert contacts[0].email == "press@kalathread.com"


def test_social_html_uses_open_graph():
    html = """
    <html><head>
      <meta property="og:title" content="Nykaa on Instagram">
      <meta property="og:description" content="@nykaa: We are looking for UGC creators in Mumbai this month. DM hello@nykaa.com">
      <meta name="author" content="nykaa">
    </head><body><h1>Log in</h1><p>Sign up to see this post in the app.</p></body></html>
    """
    title, text = text_from_social_html("https://www.instagram.com/p/abc", html)
    assert title == "Nykaa on Instagram"
    assert "looking for UGC creators" in text
    assert "hello@nykaa.com" in text
    assert "Log in" not in text


def test_reddit_json_keeps_post_and_comments():
    payload = [
        {"data": {"children": [{"data": {
            "title": "Looking for Indian beauty creators",
            "selftext": "We need UGC for a launch next week.",
            "author": "kala_thread",
            "subreddit": "IndianStartups",
        }}]}},
        {"data": {"children": [{"data": {"author": "cmo_priya", "body": "Email press@kalathread.com"}}]}},
    ]
    parsed = text_from_reddit_json(payload)
    assert "Looking for Indian beauty creators" in parsed["text"]
    assert "u/kala_thread" in parsed["text"]
    assert "press@kalathread.com" in parsed["text"]


def test_searx_categories():
    # SearXNG has no Reddit/Instagram/LinkedIn/X engine; "social media" is Lemmy/Mastodon
    # only, so site: queries for those platforms must go through "general" instead.
    assert searx_categories('"looking for creators" site:reddit.com') == "general"
    assert searx_categories('"product launch" influencers India') == "news"
    assert searx_categories('"looking for influencers" India') == "general"


def test_social_platform_from_url():
    assert platform_from_url("https://www.instagram.com/p/abc") == "instagram"
    assert platform_from_url("https://www.facebook.com/reel/1") == "facebook"
    assert platform_from_url("https://www.reddit.com/r/influencermarketing/comments/1") == "reddit"


def test_agency_seller_is_not_a_lead():
    text = (
        "Grynow is the best influencer marketing agency in India, helping brands "
        "connect with the right influencers, KOLs, and ambassadors."
    )
    assert is_agency_seller(text, "Grynow")
    result = heuristic_classify(text)
    assert not result.is_lead, result


def test_subreddit_listing_is_reddit():
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Looking for indian influencers to promote my app",
                        "selftext": "I am founder of the balanced news.",
                        "permalink": "/r/influencermarketing/comments/abc/looking_for_indian_influencers/",
                    }
                }
            ]
        }
    }
    hits = listing_hits_from_json(payload, "influencermarketing")
    assert hits
    assert hits[0].platform == "reddit"
    assert "reddit.com/r/influencermarketing" in hits[0].url
    assert "Looking for indian influencers" in hits[0].title


def test_founder_of_keeps_article_brand():
    text = "I am founder of the balanced news. Looking for indian influencers to promote my app."
    assert resolve_company_name(text) == "Balanced News"
    result = heuristic_classify(text)
    assert result.is_lead, result
    assert result.company == "Balanced News"


def test_company_from_email_domain():
    text = "We are looking for UGC creators for our launch. Email press@kalathread.com"
    assert resolve_company_name(text) == "Kalathread"


def test_brands_filter_keeps_d2c_drops_agency():
    assert is_target_brand(
        "I am founder of the balanced news. Looking for indian influencers to promote my app.",
        "Balanced News",
        "saas",
    )
    assert is_target_brand(
        "We are officially looking for fashion content creators who love styling.",
        "Incense Clothing Co.",
        "fashion",
    )
    assert not is_target_brand(
        "Drishti Media is expanding its creator network and we're looking for creators in Fashion.",
        "Drishti Media",
        "beauty",
    )
    assert not is_target_brand(
        "Premium D2C brands need creators who treat their feed like a magazine.",
        "Slowliving Suki",
        "d2c",
    )
    assert not is_target_brand("Why does the government need influencers?", "IT. It")
    assert is_target_brand("Indian D2C skincare brand based in Mumbai.", "Dot & Key", "beauty")


def test_directory_and_linkedin_people():
    from app.pipeline.keyword_filter import directory_hit
    from app.providers.enrichment import _person_from_linkedin
    from app.pipeline.queries import _priority_queries

    assert directory_hit("https://www.linkedin.com/company/mamaearth/", "Mamaearth")
    assert directory_hit("https://example.in/about", "Indian D2C skincare brand")
    assert not directory_hit("https://example.com/blog", "random post")
    person = _person_from_linkedin(
        "https://www.linkedin.com/in/meera-shah",
        "Meera Shah - CMO - Lumora | LinkedIn",
    )
    assert person and person.name == "Meera Shah" and person.job_title == "CMO"
    pack = _priority_queries("India")
    assert any("linkedin.com/in" in q for q in pack)
    assert any("beauty brand" in q for q in pack)


def test_india_only_drops_foreign():
    assert is_india_target("We are looking for Indian beauty creators for our upcoming launch.")
    assert is_india_target("Need UGC creators in Mumbai this month.")
    assert is_india_target("Looking for creators", "https://kalathread.in/cast")
    assert not is_india_target("Looking for influencers in the US for our NYC launch.")
    assert not is_india_target("UK brand looking for creators in London.")
    result = classify_text("Roblox is looking for influencers in the United States. DM us.")
    assert not result.is_lead


def test_memory_rejects_similar_mistake():
    lessons = [
        Lesson(
            verdict="reject",
            company="Roblox",
            evidence="Roblox is looking for influencers to join our creator program this summer",
            source_url="https://facebook.com/groups/old",
            label="dismissed",
        )
    ]
    assert remembered_reject(
        "Roblox is looking for influencers to join our creator program this summer",
        "Roblox",
        "https://facebook.com/groups/new",
        lessons,
    )
    assert not remembered_reject(
        "Nykaa is looking for beauty creators for a Diwali lipstick launch",
        "Nykaa",
        "https://instagram.com/p/abc",
        lessons,
    )
    result = classify_text(
        "Roblox is looking for influencers to join our creator program this summer. DM us.",
        "https://facebook.com/groups/new",
        lessons,
    )
    assert not result.is_lead
    assert "memory" in result.provider


def test_critic_rejects_campaign_recap():
    result = Classification(
        is_lead=True,
        intent_type="CREATOR_CAMPAIGN",
        intent_strength="high",
        campaign_type="creator_campaign",
        geography="India",
        urgency="low",
        company="Brand X",
        industry="beauty",
        evidence="campaign recap",
        provider="test",
        confidence=0.9,
    )
    out = _critic_pass(result, "Brand X influencer campaign recap. We wrapped up last year.")
    assert not out.is_lead
    assert "recap" in out.critique.lower() or "completed" in out.critique.lower()


def test_score_penalizes_recap():
    text = "Brand Y influencer campaign recap. We wrapped up last year."
    result = heuristic_classify(text)
    score, reasons = score_lead(text, result)
    assert any("recap" in reason.lower() or "Historical" in reason for reason in reasons)
    assert score < 40


def test_retrieve_pack_splits_keep_and_reject():
    lessons = [
        Lesson("keep", "Nykaa", "Looking for Indian beauty creators for our launch", "https://a", "genuine"),
        Lesson("reject", "Roblox", "Roblox is looking for influencers to join our creator program", "https://b", "false_positive"),
    ]
    keep = retrieve_pack("Looking for Indian beauty creators for a lipstick launch", lessons)
    reject = retrieve_pack("Roblox is looking for influencers to join our creator program this summer", lessons)
    assert keep.keep and keep.keep[0].company == "Nykaa"
    assert reject.reject and reject.reject[0].company == "Roblox"


def test_rss_parses_items():
    raw = b"""<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Looking for creators</title>
        <link>https://yourstory.com/2026/brand-asks</link>
        <description>A D2C brand in Mumbai</description>
      </item>
    </channel></rss>"""
    hits = _hits_from_xml(raw)
    assert hits and hits[0].url.endswith("/brand-asks")
    assert "creators" in hits[0].title.lower()


def test_trafilatura_keeps_article_body():
    html = """
    <html><head><title>Kala Thread launch</title></head>
    <body>
      <nav>Home About Careers</nav>
      <article><p>We are looking for Indian beauty creators for our upcoming launch.</p></article>
      <footer>Copyright 2026</footer>
    </body></html>
    """
    doc = parse_document("https://kalathread.com/launch", html)
    assert "looking for Indian beauty creators" in doc.text


if __name__ == "__main__":
    tests = [
        test_high_intent_is_lead,
        test_agency_ask,
        test_generic_discussion_is_not_a_lead,
        test_keyword_gate,
        test_marketplace_is_not_a_lead,
        test_contact_extraction,
        test_gated_classify_skips_model_on_noise,
        test_handle_extract,
        test_email_missing,
        test_html_contact_page,
        test_social_html_uses_open_graph,
        test_reddit_json_keeps_post_and_comments,
        test_searx_categories,
        test_social_platform_from_url,
        test_agency_seller_is_not_a_lead,
        test_subreddit_listing_is_reddit,
        test_founder_of_keeps_article_brand,
        test_company_from_email_domain,
        test_brands_filter_keeps_d2c_drops_agency,
        test_directory_and_linkedin_people,
        test_india_only_drops_foreign,
        test_memory_rejects_similar_mistake,
        test_critic_rejects_campaign_recap,
        test_score_penalizes_recap,
        test_retrieve_pack_splits_keep_and_reject,
        test_rss_parses_items,
        test_trafilatura_keeps_article_body,
    ]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} checks passed")
