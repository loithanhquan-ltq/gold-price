<div align="center">

# Theo Dõi Giá Vàng

**Real-time Vietnamese & international gold price tracking with automated daily email reports**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/loithanhquan-ltq/gold-price/daily_gold.yml?style=flat-square&logo=githubactions&logoColor=white&label=daily%20job)](https://github.com/loithanhquan-ltq/gold-price/actions)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

</div>

---

## Overview

**Theo Dõi Giá Vàng** is a self-hosted gold price tracker that monitors Vietnamese SJC gold (via PNJ) and international XAU/USD (via Yahoo Finance/CoinGecko) in real time, plus the daily EUR→VND reference rate. It persists daily prices in a local database, serves a live web dashboard, and delivers a formatted HTML email report every morning — automatically.

```
┌─────────────────────────────────────────────────┐
│              Web Dashboard (dark UI)            │
│                                                 │
│  ┌──────────────────┐  ┌──────────────────────┐ │
│  │   SJC Gold       │  │  International Gold  │ │
│  │  Buy / Sell      │  │  Price / High / Low  │ │
│  │  VND / tael      │  │  USD / troy oz       │ │
│  └──────────────────┘  └──────────────────────┘ │
│                                                 │
│  [ Refresh Prices ]    [ Send Test Email ]      │
└─────────────────────────────────────────────────┘
```

---

## Features

- **Live scraping** — SJC prices from PNJ's JSON API, international XAU/USD from Yahoo Finance with CoinGecko fallback
- **EUR/VND tracking** — Daily mid-market reference rate from ExchangeRate-API, with a jsDelivr fallback
- **Daily email reports** — Multi-part HTML + plain-text emails with price changes, the EUR→VND rate, and a 7-day chart, sent silently via BCC so recipients stay private
- **Stale-data fallback** — If a fetch fails, the previous day's price is carried forward and flagged as stale
- **Persistent history** — SQLite database with upsert logic; 90-day rolling JSON exported to `docs/data/prices.json`
- **Web dashboard** — Responsive dark-themed SPA with auto-refresh every 5 minutes
- **GitHub Actions CI** — Daily scheduled job at 10:00 ICT; commits updated `prices.json` automatically
- **In-process scheduler** — APScheduler runs inside the FastAPI process; Docker is locked to a single worker to prevent duplicate jobs
- **Retry logic** — Exponential backoff via Tenacity; smart exception filtering skips retries on 4xx responses

---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.111 + Uvicorn |
| Database | SQLite (SQLAlchemy 2.0) |
| Scheduler | APScheduler 3.10 |
| Scraping | Requests 2.32 + BeautifulSoup4 4.12 |
| Retry | Tenacity 8.3 |
| Email | Python `smtplib` + Gmail SMTP (SSL) |
| Templating | Jinja2 3.1 |
| Charts | Matplotlib 3.9 (base64-encoded inline) |
| Frontend | Vanilla JS + CSS3 (no framework) |
| Container | Docker (Python 3.12-slim) |
| CI/CD | GitHub Actions |

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/loithanhquan-ltq/gold-price.git
cd gold-price

cp .env.example .env
# Edit .env with your credentials (see Environment Variables below)

docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000).

### Manual

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env

uvicorn backend.main:app --reload
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GMAIL_USER` | Yes | — | Gmail address used as the sender |
| `GMAIL_APP_PASSWORD` | Yes | — | 16-character [Gmail App Password](https://support.google.com/accounts/answer/185833) — **not** your regular password |
| `RECIPIENT_EMAIL` | Yes | — | Comma-separated list of recipient addresses. Recipients cannot see each other (BCC-style delivery) |
| `API_TOKEN` | Yes | — | Secret token for protected API endpoints |
| `SEND_HOUR` | No | `7` | Hour of day to send the daily email (24h, in `TIMEZONE`) |
| `TIMEZONE` | No | `Asia/Ho_Chi_Minh` | Python `ZoneInfo` timezone string |
| `CACHE_TTL_SECONDS` | No | `600` | How long live prices are cached before re-fetching |
| `DATABASE_URL` | No | `sqlite:////app/data/gold_prices.db` | SQLAlchemy connection string |
| `LOG_LEVEL` | No | `INFO` | Python logging level |

> **Tip:** For Gmail, enable 2-step verification and generate a dedicated App Password — the regular account password will not work with SMTP.

---

## API Reference

### Public

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web dashboard (injects API token server-side) |
| `GET` | `/api/health` | Liveness check; returns scheduler status |
| `GET` | `/api/prices/current` | Latest live prices (TTL-cached) |
| `GET` | `/api/prices/history?days=7` | Historical prices from the database |
| `GET` | `/api/status` | Scheduler status and next scheduled run |

### Protected (requires `X-API-Token` header)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/refresh` | Force-fetch live prices and write to DB |
| `POST` | `/api/email/test` | Trigger the full daily job immediately |

**Example response** — `GET /api/prices/current`:

```json
{
  "sjc": {
    "source": "SJC",
    "currency": "VND",
    "unit": "tael",
    "buy_price": 123400000,
    "sell_price": 125600000
  },
  "international": {
    "source": "INTERNATIONAL",
    "currency": "USD",
    "unit": "troy_oz",
    "buy_price": 3327.50,
    "high": 3341.00,
    "low": 3310.20
  },
  "fetched_at": "2026-06-25T10:00:00+07:00"
}
```

---

## Architecture

```
┌─────────────┐     scrape      ┌──────────────────┐
│  PNJ        │ ──────────────► │                  │
│  (SJC JSON) │                 │  backend/        │
└─────────────┘                 │  scrapers/       │
                                │                  │
┌─────────────┐     API call    │  sjc.py          │
│  Yahoo      │ ──────────────► │  international.py│
│  Finance    │                 │                  │
└─────────────┘                 └────────┬─────────┘
                                         │ upsert
                                ┌────────▼─────────┐
                                │   SQLite DB      │
                                │  gold_prices     │
                                └────────┬─────────┘
                                         │
                    ┌────────────────────┼───────────────────┐
                    │                    │                   │
           ┌────────▼──────┐   ┌─────────▼──────┐  ┌───────▼──────┐
           │  FastAPI      │   │  APScheduler   │  │  GitHub      │
           │  /api/*       │   │  daily @ 07:00 │  │  Actions     │
           └────────┬──────┘   └─────────┬──────┘  │  daily 10:00 │
                    │                    │          └──────────────┘
           ┌────────▼──────┐   ┌─────────▼──────┐
           │  Frontend     │   │  email_service │
           │  Dashboard    │   │  Gmail SMTP    │
           └───────────────┘   └────────────────┘
```

---

## Project Structure

```
gold-price/
├── backend/
│   ├── main.py              # FastAPI app and routes
│   ├── models.py            # SQLAlchemy ORM model
│   ├── database.py          # Engine and session setup
│   ├── repository.py        # DB query helpers
│   ├── scheduler.py         # APScheduler job definition
│   ├── email_service.py     # SMTP email builder and sender
│   ├── config.py            # Env var loading and validation
│   ├── cache.py             # Simple in-memory TTL cache
│   ├── security.py          # API token dependency
│   ├── logging_config.py    # Rotating file + console logging
│   ├── scrapers/
│   │   ├── base.py          # PriceResult dataclass + retry wrapper
│   │   ├── sjc.py           # PNJ JSON scraper
│   │   ├── fx.py            # EUR/VND reference rate
│   │   └── international.py # Yahoo Finance / CoinGecko
│   └── templates/
│       ├── email.html       # Jinja2 HTML email template
│       └── email.txt        # Plain-text fallback template
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── scripts/
│   └── fetch_and_update.py  # GitHub Actions entry point
├── tests/
│   ├── test_sjc_parser.py
│   ├── test_security.py
│   ├── test_change_calc.py
│   └── fixtures/
├── docs/
│   └── data/prices.json     # 90-day rolling price history
├── .github/workflows/
│   └── daily_gold.yml
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## GitHub Actions Setup

The workflow at `.github/workflows/daily_gold.yml` runs daily at **10:00 ICT (03:00 UTC)** and can also be triggered manually from the Actions tab.

**Required repository secrets:**

| Secret | Description |
|---|---|
| `GMAIL_USER` | Sender Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password |
| `RECIPIENT_EMAIL` | Comma-separated recipient list |

The job fetches prices, sends the daily email, and commits the updated `docs/data/prices.json` back to the repository.

---

## License

MIT — see [LICENSE](LICENSE).
