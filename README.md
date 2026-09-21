# Intent Radar

A self-hosted, zero-budget **influencer marketing intent engine**.

It looks for people who are asking for influencers, creators, UGC, brand ambassadors, or an agency *today* — not a scraped directory of marketing managers who might someday need one.

```
Public pages → cheap keyword filter → local classifier → company + evidence → dashboard
```

The first version is scoped the way the plan asked:

- one country (India)
- a handful of industries (beauty, fashion, D2C, fintech, food, wellness, SaaS, jewellery)
- ~30 intent queries
- public-style sources: Reddit, forums, job boards, news, company pages
- human review before any outreach is sent

## What you get

- **Lead radar** with WHY NOW, evidence, source, score breakdown, and CRM status
- **Filters** for intent type, strength, campaign, industry, source, and status
- **Find contact** from the source post, then the company homepage / contact / about / team pages. Emails stay unverified unless DNS/MX answers. Mailboxes are never guessed.
- **Draft outreach** — copy only. Sending is off on purpose
- **Run scan** through provider interfaces (`SearchProvider`, `AIProvider`, `EnrichmentProvider`, `EmailProvider`)

SearXNG and MuseSpark plug in when you have them; otherwise the engine uses a local fixture index and a transparent heuristic classifier.

## Run locally

Needs Python 3.12+ and Node 20+.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 47221
```

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 43123
```

Open [http://127.0.0.1:43123](http://127.0.0.1:43123). The Vite dev server proxies `/api` to the backend.

Or build the UI and let FastAPI serve it:

```bash
cd frontend && npm run build
cd ../backend && uvicorn app.main:app --host 127.0.0.1 --port 43123
```

SQLite lives at `backend/data/radar.db`. Point `DATABASE_URL` at PostgreSQL if you want the compose file.

## Run on a server

Needs Python 3.12+, Node 20+, and outbound HTTPS so SearXNG and the crawler can reach public pages.

```bash
git clone <your-github-repo-url> intent-radar
cd intent-radar

cd frontend && npm install && npm run build && cd ..

cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# set SEARXNG_URL and DEMO_MODE=false after SearXNG is up
```

Start SearXNG (Docker is the usual path on a real server):

```bash
docker compose up -d searxng
```

Then serve the API and built UI on one port:

```bash
cd backend
source .venv/bin/activate
set -a && source .env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 43123
```

Open `http://<server>:43123`. Put a reverse proxy in front if you want HTTPS.

`DEMO_MODE=false` hides the sample fixture index. The crawler still respects `robots.txt` and will not log into Instagram, Facebook, or LinkedIn.

### MuseSpark (classifier)

Meta Model API at `https://api.meta.ai/v1`. Set your key in `backend/.env`:

```bash
MUSESPARK_API_KEY=<your Model API key>
MUSESPARK_MODEL=muse-spark-1.2
```

`MODEL_API_KEY` is accepted as an alias. The keyword gate still drops junk. Promising text goes to MuseSpark; if the key is missing, local Ollama or the heuristic runs.

### Local Ollama (fallback)

On the same machine, not in the cloud:

```bash
# https://ollama.com
ollama pull llama3.2
# default listen: http://127.0.0.1:11434
```

### Cron (continuous discovery)

```bash
# every 4 hours
0 */4 * * * cd /path/to/intent-radar/backend && .venv/bin/python -m app.cli scan >> /tmp/intent-scan.log 2>&1
```

Or set `SCAN_INTERVAL_MINUTES=240` in `.env` and let the API process loop locally.

After each scan, mark leads **genuine / false positive / no contact** so you can see if quality is improving.

## Optional providers

| Interface | Default | Upgrade |
| --- | --- | --- |
| `SearchProvider` | Fixture index of public-style posts | `SEARXNG_URL=http://127.0.0.1:8888` |
| `AIProvider` | Heuristic classifier | MuseSpark at `MUSESPARK_API_KEY` / `MUSESPARK_MODEL`, or Ollama at `OLLAMA_URL` / `OLLAMA_MODEL` |
| `EnrichmentProvider` | Public page text | Apollo / Hunter later |
| `EmailProvider` | DNS/MX + manual draft | Gmail / SMTP later |

```bash
cp backend/.env.example backend/.env
docker compose up -d searxng
# If Docker overlay mounts fail (some VMs), run SearXNG from source:
#   git clone --depth 1 https://github.com/searxng/searxng.git /tmp/searxng
#   cd /tmp/searxng && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-server.txt
#   SEARXNG_SETTINGS_PATH=/path/to/this/repo/searxng/settings.yml \
#     PYTHONPATH=/tmp/searxng .venv/bin/granian --interface wsgi --host 127.0.0.1 --port 8888 searx.webapp:app
```

`searxng/settings.yml` enables `format=json` and turns the bot limiter off for local use. Point the API at it with `SEARXNG_URL=http://127.0.0.1:8888` and `DEMO_MODE=false`.

The crawler does not bypass logins, CAPTCHAs, paywalls, or `robots.txt`.

## Checks

```bash
cd backend
PYTHONPATH=. python check_engine.py
```

## Product rule

Do not optimize for “how many contacts we stored.”

Optimize for: **Brand X is actively looking for creators, here is the sentence they wrote, here is the source, here is who to talk to.**

What is still open versus the original plan is in [`remaining.md`](remaining.md).
