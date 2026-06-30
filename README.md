# Instagrowth — Instagram AI Analyzer & Growth Engine

Automated Instagram analytics + growth engine for the AI / vibecoding niche. It captures your
metrics daily, generates a **weekly Egyptian Arabic strategy report** via Gemini, scans
niche-specific trends into opportunity-scored topic ideas, drafts/repurposes multi-format
content, and auto-publishes behind a mandatory Telegram **Approve/Edit/Skip** gate.

Code-first: a single **Python 3.12** app run as two Docker services (`cron` + `bot`) on
**Supabase Postgres 17**. No visual automation tool. Output language: **العامية المصرية**
(Egyptian Arabic), Islamic-friendly, accuracy-first tone.

> Built from the spec/plan in `specs/001-instagram-ai-analyzer/`. See `plan.md` for the full
> architecture, schema, and phased rollout (MVP → v5).

## Architecture

```
External trend sources (HN/PH/GitHub/HF/Reddit/RSS + Gemini Grounding)
   │
   ▼
Instagram Graph API v25.0 (cursor paging, views)  ──►  Supabase Postgres 17
   │   (idempotent upserts, partitioned, RLS, BRIN, pg_cron rollups)         │
   ▼                                                                          ▼
Gemini 3.5 Flash (structured output, versioned prompts)  ◄── weekly_summary MV
   │   ├── Weekly Egyptian Arabic report (self-check ±10%)
   │   ├── Niche topic ideation (opportunity score, relevance gate)
   │   ├── Content engine: auto-draft / repurpose / best-time / predict
   │   └── Anomaly radar (≥3σ, attributed)  ──►  Delivery: Email + Telegram (HITL)
   ▼
Auto-publish (Content Publishing API, image/carousel/Reels) behind Telegram Approve gate
```

Two services (one image): `cron` (supercronic → `python -m app.jobs.*`) and `bot`
(always-on Telegram HITL/approvals).

## Project layout

```
app/
  config.py                 pydantic-settings: env + secrets
  db/     client.py models.py logging.py        psycopg pool + upsert + pipeline_runs
  instagram/ client.py token.py                 Graph API v25.0 (views), token lifecycle
  connectors/ hn producthunt github_trending huggingface reddit rss grounding   trend sources
  ai/      gemini.py grounding.py               google-genai: structured output, fallback, cost
  analysis/ baselines.py anomalies.py best_time.py hashtag_stats.py predict.py
  jobs/     daily_sync weekly_media_sync weekly_report token_health
            trend_scan topic_ideation competitor_discovery topic_backfill
            anomaly_detect auto_draft repurpose auto_publish cost_guard weekly_digest
  bot/     hitl.py                              Approve/Edit/Skip inline buttons
  notify/  telegram.py email.py                 delivery + retry, idempotent on run_id
  utils/   retry.py buc.py cost.py              backoff, BUC budget, monthly spend cap
prompts/                    versioned prompt markdown (pin-and-bump)
supabase/migrations/  supabase/seed/           15-table schema + RLS + partitions + rollups
scheduler/crontab  docker-compose.yml  Dockerfile  pyproject.toml
```

## Prerequisites (your external accounts — manual, ~1h)

These can't be automated; fill the values into `.env`:

1. **Supabase** — create a project (Postgres 17); copy project ref, **DB URL**, and the
   **`service_role` key** into `.env`. Run the migrations (`supabase/migrations/*.sql` in
   order) + the niche seed. Create a Storage bucket `content-media` (public-read).
2. **Meta / Instagram** — Business app → Instagram product → link your **IG Business account**
   + **Facebook Page**. Note your `IG_USER_ID`. Create a Business Manager **System User**,
   assign to the Page, generate a non-expiring **System User token** → `META_TOKEN`.
   (Later: request `instagram_content_publish` + App Review for v5.)
3. **Google Gemini** — AI Studio **API key** (`gemini-3.5-flash`) → `GEMINI_API_KEY`.
4. **Telegram** — create a bot, note `TELEGRAM_BOT_TOKEN` + your `TELEGRAM_CHAT_ID`.
5. **SMTP** — for email delivery (optional; Telegram alone works).

## Setup

```bash
cp .env.example .env          # fill in the secrets above
# Run the SQL migrations against Supabase (SQL Editor or `supabase migration up`):
#   supabase/migrations/0001..0008 + supabase/seed/0001_account_config.sql
# (replace <YOUR_IG_USER_ID> in the seed with your IG_USER_ID)

docker compose up -d --build  # starts `cron` (supercronic) + `bot` (Telegram HITL)
```

## Environment variables (`.env`)

| Var | Purpose |
|---|---|
| `SUPABASE_DB_URL` | psycopg DSN (`postgresql://...`) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | project URL + server-side key |
| `IG_USER_ID`, `META_TOKEN` | IG account + System User token |
| `IG_API_VERSION` | Graph API version (default `v25.0`) |
| `GEMINI_API_KEY` | Gemini AI Studio key |
| `GEMINI_MODEL_PRIMARY` / `GEMINI_MODEL_FALLBACK` | default `gemini-3.5-flash` / `gemini-3.1-flash-lite` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | delivery + HITL |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | email delivery |
| `ACCOUNT_TIMEZONE`, `TREND_MAX_PER_SOURCE`, `LOG_LEVEL` | runtime tuning |
| Optional: `PRODUCTHUNT_TOKEN`, `REDDIT_CLIENT_ID/SECRET/USER_AGENT`, `RSS_FEEDS` | extra sources |

> Set `META_TOKEN_KIND=system_user` if you're using a non-expiring System User token (skips the
> refresh path). Never commit `.env`.

## Dry-runs (manual validation — the MVP test)

```bash
docker compose exec cron python -m app.jobs.daily_sync       # rows in ig_profile_metrics / ig_stories
docker compose exec cron python -m app.jobs.weekly_report    # Egyptian Arabic report → ai_reports + email/Telegram
docker compose exec cron python -m app.jobs.trend_scan       # fresh signals → trend_signals (deduped)
docker compose exec cron python -m app.jobs.topic_ideation   # 3–5 niche ideas → topic_suggestions
docker compose exec cron python -m app.jobs.anomaly_detect   # post-sync radar (inject a spike to test)
```

MVP = 7 clean daily snapshots + one delivered report with the engagement-rate self-check passing.

## Schedules (`scheduler/crontab`)

| Cadence | Job |
|---|---|
| Daily 02:00 | `daily_sync` (profile + insights + **stories — 24h expiry**) |
| Hourly | `token_health` |
| Daily 02:30 | `anomaly_detect` (runs after sync) |
| Daily 03:00 | `topic_backfill` (measured_engagement_rate ≥14d) |
| Sun 06:00 | `weekly_report` (media deep-dive + AI report) |
| Sun 07:00 | `weekly_digest` |
| Mon/Wed/Fri 08:00 | `trend_scan` → 08:30 `topic_ideation` |
| Quarterly | `competitor_discovery` |
| Daily 09:00 / 10:00 | `auto_draft` / `repurpose` |
| Daily 00:15 | `cost_guard` |

Edit `scheduler/crontab` and restart the `cron` service to change cadences.

## Notes & limits

- **Metric:** all code uses `views` / `total_views` — never `impressions` (deprecated ~Apr 2025).
- **Stories** expire in 24h — the daily job is mandatory; the anomaly radar also alerts if none
  are captured within 25h.
- **Media assets:** text is generated by the engine; media is **manual** by default (upload to the
  `content-media` bucket, paste the URL into `content_drafts.media_url`). AI generation stays OFF
  until explicitly enabled. See `prompts/README.md`.
- **Cost cap:** hard monthly limit in `account_config.monthly_cost_cap_usd` (default $20). Alert at
  80%, throttle non-essential AI at 100% (data capture + anomaly radar keep running).
- **Prompt versioning:** every AI output stores its `prompt_version`; bump (`-v2`) instead of editing
  live. See `prompts/README.md`.

## Status

All code-doable tasks (US1–US5 + polish) are implemented. Pending **manual** validation:
the plan's end-to-end Testing & Validation Checklist (`plan.md` §13) and the first-day Setup
Runbook (`plan.md` Appendix C) against your live accounts.
