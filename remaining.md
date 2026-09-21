# Remaining

Against `influencer_marketing_intent_engine_plan.md`. This is what is still open after the first usable slice plus MuseSpark, handle→brand resolve, SMTP checks, and quality rates.

The product is finished when a salesperson can open the radar and consistently see: source, exact evidence, company, campaign, decision maker, and a usable business contact. That last half is still weak on live social posts.

## Done enough to use

- Intent types, keyword gate, transparent score, evidence-first classify
- SearXNG queries for India (cities + a few industries)
- Vue radar, filters, CRM status, View source, Find contact, Draft outreach
- Provider interfaces (Search / AI / Enrichment / Email)
- Companies, leads, contacts, crawl pages
- Public-web enrichment: source post, then homepage / about / contact / team
- DNS/MX only (no guessed mailboxes; sending off)
- MuseSpark (Meta Model API) behind the heuristic gate; Ollama if the key is missing
- Handle → brand name (MuseSpark) then official-site search
- SMTP RCPT after DNS/MX for emails found on public pages
- Quality rates: genuine / false positive / contact discovery
- Official-site resolve via local SearXNG
- `python -m app.cli scan` for cron, or `SCAN_INTERVAL_MINUTES`
- Quality marks: genuine / false positive / no contact

## Still remaining

### Lead quality

- MuseSpark key must be set (`MUSESPARK_API_KEY` or `MODEL_API_KEY`). Without it, live scans stay on the heuristic.
- Outreach reply rate is still untracked (send is off).
- Social hits are scraped (Reddit `.json`, Open Graph, YouTube oEmbed). Login walls stay login walls; we keep the public caption/snippet only.

### Company and people

- Company name is still a guess from the post or @handle. Many live leads stay unnamed.
- No solid pass for industry / city / size beyond regex and homepage text.
- People extraction is title regex (Founder, CMO, …), not a real decision-maker finder.
- Brand resolve helps only when the classifier already got a usable name.

### Contacts

- High-intent posts are often Reddit / Instagram / Facebook. No email on the source, and often no official site to crawl.
- SMTP RCPT is on; many networks block port 25 so status stays `mx_ok`.
- Paid enrichers (Apollo / Hunter) are interfaces only.
- No path from `@brand wants UGC` → confirmed `hello@brand.com` when the site is unknown.

### Discovery that keeps running

- Cron exists; it is not configured for you. Wire it on the server.
- No dedicated scrapers for Reddit, job boards, press rooms, or creator-program pages — only SearXNG hits plus httpx.
- Query set is still India + a few industries. Not done: other countries, languages, campaign types, product categories.

### Stack the plan named that we skipped

- Scrapy / Crawlee
- Playwright (JS-rendered public pages)
- trafilatura (BeautifulSoup only)
- PostgreSQL as the default (SQLite works; `DATABASE_URL` can point at Postgres)
- Postgres-backed crawl queue and a separate worker
- SMTP verify

Playwright would help public JS sites. It still cannot open logged-in social posts.

### Phase 4 outreach

- Drafts exist. Human-approval queue, Gmail/SMTP send, and follow-up tracking do not.
- Keep send off until quality marks show the leads are real.

## Build next, in order (local only)

1. Put your **MuseSpark** Model API key in `backend/.env`.
2. Turn on **cron** and review the quality rates weekly.
3. Playwright for public JS pages, then Postgres queue, then outreach send.

Paid enrichers (Apollo / Hunter) stay interfaces only. Send stays off until quality marks say the leads are real.
