# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the server (needs .env — copy from .env.example)
uvicorn backend.main:app --reload          # http://localhost:8000
docker compose up --build                  # same, containerized

# Tests
pytest tests/ -v
pytest tests/test_sjc_parser.py::test_parse_synthetic -v

# Exercise the GitHub Actions path locally
python scripts/fetch_and_update.py --preview   # writes docs/preview.html, sends no email
python scripts/fetch_and_update.py             # fetches, writes prices.json, SENDS email
```

`--preview` is the safe way to iterate on the email design: it renders the exact same HTML with the chart embedded as a `data:` URI instead of a MIME `cid:` attachment.

## Two independent pipelines

This is the single most important thing to understand: the repo contains **two parallel implementations** of "fetch prices → render email → send", and they do not share code beyond the scrapers.

| | FastAPI app | GitHub Actions job |
|---|---|---|
| Entry | `backend/main.py` (APScheduler, `SEND_HOUR`, default 07:00 ICT) | `scripts/fetch_and_update.py` (cron 03:00 UTC = 10:00 ICT) |
| Storage | SQLite via `backend/repository.py` | `docs/data/prices.json`, 90-day rolling |
| Email builder | `backend/email_service.py` + Jinja2 `backend/templates/` | inline `%%NAME%%` string templates in `fetch_and_update.py` |
| Chart | none | Matplotlib, base64/CID inline |
| Frontend | `frontend/` (served by FastAPI, reads `/api/*`) | `docs/` (GitHub Pages, reads `data/prices.json`) |
| Deps | `requirements.txt` | `requirements-actions.txt` (deliberately minimal — no FastAPI/SQLAlchemy) |

`frontend/app.js` and `docs/app.js` are **different files that have diverged**, not copies. Editing one does not affect the other. When asked to change "the dashboard" or "the email", determine which pipeline is meant first — in practice the Actions/Pages path (`scripts/` + `docs/`) is the one that runs in production daily.

Only `backend/scrapers/` is shared. A scraper change affects both pipelines.

## Scrapers

`fetch_sjc_price()` and `fetch_international_price()` each have a primary source and a fallback, and both return a `PriceResult` (`backend/scrapers/base.py`):

- **SJC**: PNJ JSON API only, no fallback. Prices are strings in nghìn/lượng, scaled ×1,000 by `_vnd_per_tael`. sjc.com.vn cannot be scraped at all (JS challenge). giavang.doji.vn was the original source and worked in CI until 2026-07-16, when it went JS-only — it now serves no price table to plain HTTP clients, so it was removed rather than left failing silently.
- **International**: Yahoo Finance `GC=F` → CoinGecko `tether-gold`. Yahoo has been returning 429 consistently, so in practice CoinGecko serves most runs — and it carries no high/low, which is why those fields read N/A in the email.

Both apply sanity-range checks (`_check_range`, `500 < price < 20_000`) that raise rather than return implausible values — this is the main defense against a silently changed API shape. Retries come from the shared `network_retry` decorator, which deliberately does **not** retry 429/401/403/404.

Tests cover the parser only (`_parse_pnj_json`), against `tests/fixtures/pnj_sample.json` — no network. Keep coverage pointed at the source that actually runs: an earlier suite tested only the DOJI parser and stayed green through a four-day production outage of the PNJ-era scraper.

**A failed fetch is not a failed run.** `scripts/fetch_and_update.py` catches scraper exceptions, writes `null` for that day, and exits 0 — so the workflow stays green and the only symptom is a red "Không lấy được dữ liệu hôm nay" block in the email. When prices go missing, check `docs/data/prices.json` history for `null` runs rather than the Actions status.

## Conventions that aren't obvious

- **Stale carry-forward** (FastAPI path only): `scheduler._fetch_or_carry` writes the previous day's row with `is_stale=1` when a fetch fails, so the daily email always has numbers. The Actions path instead writes `null` for that day and the chart draws a `×` marker.
- **BCC-style delivery**: both senders set `msg["To"]` to the sender (or the joined list) but pass the real recipient list to `sendmail()`'s envelope so recipients can't see each other. Don't "fix" the header/envelope mismatch.
- **Chart data URIs are blocked by Gmail** — email uses `cid:goldchart@tracker` with three-layer MIME nesting (mixed → related → alternative). Preview mode is the only place `data:` URIs are used.
- **Single worker only**: APScheduler runs in-process, so the Docker image must stay at one Uvicorn worker or the daily email fires multiple times.
- **API token injection**: `GET /` reads `frontend/index.html` and substitutes `__API_TOKEN__` at request time; the protected endpoints (`/api/refresh`, `/api/email/test`) check the `X-API-Token` header.
- `GET /api/prices/current` is read-only and TTL-cached; only `POST /api/refresh` and the scheduler write to the DB.
- UI copy and email content are in Vietnamese; log messages and code comments are in English.

## README drift

`README.md` describes SJC as coming from DOJI and lists a `backend/`-centric structure. Both predate the PNJ switch and the Actions pipeline. Trust the code; update the README when touching these areas.
