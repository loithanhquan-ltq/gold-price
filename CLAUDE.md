# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the server (needs .env — copy from .env.example)
uvicorn backend.main:app --reload          # http://localhost:8000
docker compose up --build                  # same, containerized

# Tests — the only automated check; there is no lint or build step
pytest tests/ -v
pytest tests/test_sjc_parser.py::test_parse_synthetic -v

# Exercise the GitHub Actions path locally
python scripts/fetch_and_update.py --preview   # fetches, updates docs/data/prices.json, writes docs/preview.html, sends no email
python scripts/fetch_and_update.py             # fetches, writes prices.json, SENDS email
```

`--preview` is the safe way to iterate on the email design: it renders the exact same HTML with the chart embedded as a `data:` URI instead of a MIME `cid:` attachment. It is not read-only — it still fetches live prices and rewrites `docs/data/prices.json`.

Two config traps when running locally from `.env.example`: its `DATABASE_URL` is the Docker path (`sqlite:////app/data/gold_prices.db`), which fails outside the container — use `sqlite:///./data/gold_prices.db`; and it sets `SEND_HOUR=7`, while `backend/config.py` falls back to `10` when the variable is unset.

## Two independent pipelines

This is the single most important thing to understand: the repo contains **two parallel implementations** of "fetch prices → render email → send", and they do not share code beyond the scrapers.

| | FastAPI app | GitHub Actions job |
|---|---|---|
| Entry | `backend/main.py` (APScheduler at `SEND_HOUR`) | `scripts/fetch_and_update.py` (cron 03:00 UTC = 10:00 ICT) |
| Storage | SQLite via `backend/repository.py` | `docs/data/prices.json`, 90-day rolling |
| Email builder | `backend/email_service.py` + Jinja2 `backend/templates/` | inline `%%NAME%%` string templates in `fetch_and_update.py` |
| Chart | none | Matplotlib, CID inline (base64 `data:` URI only in `--preview`) |
| Frontend | `frontend/` served by FastAPI at `/` and `/static`, reads `/api/*` | `docs/` on GitHub Pages, reads `data/prices.json` |
| Deps | `requirements.txt` | `requirements-actions.txt` (deliberately minimal — no FastAPI/SQLAlchemy) |

`frontend/app.js` and `docs/app.js` are **different files that have diverged**, not copies: the FastAPI frontend polls `/api/prices/current` and `/api/status`, auto-refreshes every 5 minutes, and posts to protected endpoints with a token injected into the page; the Pages frontend fetches the static JSON once (cache-busted) and draws a Chart.js graph from the flat `history[]` entries. Editing one does not affect the other. When asked to change "the dashboard" or "the email", determine which pipeline is meant first — in practice the Actions/Pages path (`scripts/` + `docs/`) is the one that runs in production daily.

The workflow runs the script **twice** per day: once to send the email, then once with `--preview` to refresh `docs/preview.html`. Both runs fetch and rewrite `prices.json`; only the first sends mail. It commits `docs/data/prices.json` and `docs/preview.html` back to the repo, so the job needs `contents: write`.

Only `backend/scrapers/` is shared — but `fx.py` is imported only by the Actions script, so SJC/international scraper changes affect both pipelines while FX affects only the daily job.

### Data shapes

- `docs/data/prices.json` top-level `sjc` / `international` / `eur_vnd` are `PriceResult.as_dict()` objects (`source`, `currency`, `unit`, `buy_price`, `sell_price`, `high`, `low`); `history[]` entries are flat (`date`, `sjc_buy`, `sjc_sell`, `intl_price`, `intl_high`, `intl_low`, `eur_vnd`). `docs/app.js` reads the flat shape; the FastAPI frontend reads the nested API response.
- History is capped at 90 entries (`MAX_HISTORY`). When it has fewer than 7 entries, the script backfills up to 8 days of XAU/USD from CoinGecko's `market_chart`; backfilled days have `sjc_*: null` and no `eur_vnd` key.
- The "7-day" chart windows by calendar date (latest date − 6 days), not by entry count, so missed runs do not silently stretch it into a month; if fewer than 3 points remain it falls back to the last 7 entries.

## Scrapers

The three scraper entry points (`fetch_sjc_price`, `fetch_international_price`, `fetch_eur_vnd_rate`) each return a `PriceResult` (`backend/scrapers/base.py`):

- **SJC**: PNJ JSON API only, no fallback. Prices arrive as strings in nghìn/lượng (`"144.000"`) and are scaled ×1,000 by `_vnd_per_tael`; `_check_range` rejects anything outside 10M–500M VND/tael. sjc.com.vn cannot be scraped at all (JS challenge). giavang.doji.vn was the original source and worked in CI until 2026-07-16, when it went JS-only — it now serves no price table to plain HTTP clients, so it was removed rather than left failing silently.
- **International**: Yahoo Finance `GC=F` → CoinGecko `tether-gold`. Yahoo has been returning 429 consistently, so in practice CoinGecko serves most runs — and it carries no high/low, which is why those fields read N/A in the email. Each branch rejects prices outside 500–20,000 USD.
- **EUR/VND**: `fetch_eur_vnd_rate()` in `backend/scrapers/fx.py` — open.er-api.com primary, jsDelivr currency-api fallback, both key-free daily reference feeds (Yahoo `EURVND=X` also 429s). `_check_rate` enforces 15,000–45,000 VND/EUR. Imported only by the Actions script; the FastAPI pipeline has no FX series.
- Retries come from the shared `network_retry` decorator, which deliberately does **not** retry 429/401/403/404.
- The source credit is duplicated in `backend/templates/email.html`, the Actions email template, and `docs/index.html`'s footer — swapping a source means updating all of them.

A failed fetch is not a failed run. `scripts/fetch_and_update.py` catches scraper exceptions, writes `null` for that day, and exits 0 — so the workflow stays green and the only symptom is a red "Không lấy được dữ liệu hôm nay" block in the email. Missing `GMAIL_*` variables likewise only skip the email; the JSON still updates. When prices go missing, check `docs/data/prices.json` history for `null` runs rather than the Actions status.

Tests are network-free: `test_sjc_parser.py` covers `_parse_pnj_json` against `tests/fixtures/pnj_sample.json` plus synthetic payloads; `test_fx_parser.py` covers both FX parsers and the ER-API → jsDelivr fallback order; `test_security.py` covers token enforcement; `test_change_calc.py` covers the change/format helpers. Keep parser coverage pointed at the source that actually runs: an earlier suite tested only the DOJI parser and stayed green through the four-day outage that killed that source, because fixtures don't notice a site going JS-only.

## Conventions that aren't obvious

- **Stale carry-forward** (FastAPI path only): `scheduler._fetch_or_carry` writes the previous day's row with `is_stale=1` when a fetch fails, so the daily email always has numbers. The Actions path instead writes `null` for that day and the chart draws a `×` marker.
- **BCC-style delivery**: both senders set `msg["To"]` to the sender (or the joined list) but pass the real recipient list to `sendmail()`'s envelope so recipients can't see each other. Don't "fix" the header/envelope mismatch. The Actions sender also logs only the recipient count — GitHub masks the exact secret string, so logging a joined list would leak every address.
- **Chart data URIs are blocked by Gmail** — email uses `cid:goldchart@tracker` with three-layer MIME nesting (mixed → related → alternative). Preview mode is the only place `data:` URIs are used. The FastAPI email has no chart at all.
- **Single worker only**: APScheduler runs in-process, so the Docker image must stay at one Uvicorn worker or the daily email fires multiple times. A local server with real credentials will also send the daily email at `SEND_HOUR`.
- **API token injection**: `GET /` reads `frontend/index.html` and substitutes `__API_TOKEN__` at request time; the protected endpoints (`/api/refresh`, `/api/email/test`) check the `X-API-Token` header. An empty `API_TOKEN` rejects every protected request — it fails closed rather than disabling auth.
- `GET /api/prices/current` is read-only and TTL-cached; only `POST /api/refresh` and the scheduler write to the DB. Failed live fetches are cached as `null` until the TTL expires.
- UI copy and email content are in Vietnamese; log messages and code comments are in English.
- `data/app.log` is tracked even though `.gitignore` ignores `data/`, so any local run dirties it; keep it out of feature commits.

## README drift

`README.md` still lists a `backend/`-centric structure, presents `frontend/` as the only UI (the production UI is `docs/` on Pages), documents `SEND_HOUR` default 7 (the code fallback is 10), and points at a `LICENSE` file that isn't in the repo. The committed `docs/preview.html` can lag behind the current template until the next Actions run. Trust the code; update these when touching the areas.
