# Enhanced Implementation Plan: Automated Instagram AI Analysis System
**Version:** 2.0 (Enhanced) · **Date:** June 2026 · **Status:** Research-verified

> This document replaces `Instagram_AI_Analyzer_Plan_2026.md`. Every API, model, and platform claim
> below was verified against official Meta, Google, n8n, and Supabase sources (links in Appendix A).
> The original plan's goal is preserved and **extended** — **automatically extract Instagram metrics,
> store history, generate an Egyptian Arabic growth-strategy report via AI, AND keep up with
> niche-specific trends to suggest on-topic content ideas** — with the architecture hardened for
> correctness, reliability, cost, and scale.

---

## 0. Executive Summary — What Changed & Why

The original plan was directionally correct but contained several factual errors and omitted the
parts that determine whether such a system survives in production: rate-limit math, token lifecycle,
the 24-hour story-capture window, idempotent upserts, error recovery, observability, and prompt
versioning. This version fixes those gaps.

**Critical corrections (full table in Appendix A):**
1. **API version:** latest is **`v25.0`** (Feb 18, 2026), not v22.0. Meta now ships ~every 4 months.
2. **Rate limit:** there is **no** "200 calls/hour per token" limit. Instagram uses a **Business
   Use Case (BUC)** budget of **`4800 × (account impressions in last 24h)` per app+user pair**,
   rolling 24h. The entire data-acquisition strategy is redesigned around this.
3. **Two official API paths** exist now: *Instagram Login* (no Facebook Page needed) and
   *Facebook Login* (needs a Page, gives Business Discovery). Pick deliberately.
4. **`impressions` → `views`**: the `impressions`/`video_views` metrics were deprecated ~April 2025
   in favor of a unified **`views`** metric.
5. **Model:** `gemini-3.5-flash` is **real** (released May 19, 2026, GA). Use the GA ID
   `gemini-3.5-flash` (not the `-preview` marketing string). It supports **structured output /
   JSON schema**.
6. **n8n:** v2.x is real (latest 2.27.5), but the native **Supabase node has no upsert or raw SQL**.
   Use the **Postgres node** (direct connection) for analytics writes. The claim about "SQLite
   pooling drivers" was a hallucination — Supabase is PostgreSQL.

**Major additions:** incremental sync with cursors, separate daily story-capture job (24h expiry!),
15-table schema with partitioning + RLS, token auto-refresh + expiry monitoring, exponential-backoff
retry with jitter, an execution/audit log, structured-output AI with versioned prompts, a cheap
fallback model, delivery with retry, a phased rollout (MVP → v1 → v3), a test/validation checklist,
and a **niche-scoped Trend Intelligence module (Phase 6) that surfaces fresh, on-topic trends in the
AI/vibecoding niche and converts them into opportunity-scored content ideas — never generic viral noise**.

---

### Niche profile (drives every relevance decision in this plan)

> **Niche:** AI / "vibecoding" creator — building SaaS, websites, and mobile apps with Claude and
> other AI coding tools; covering new generative models (video/image generation tools) and
> AI-for-productivity. **Freshness is the #1 competitive advantage** here: new tools/models launch
> almost daily, so the best trend signals live **off-Instagram** (X, Hacker News, Product Hunt,
> GitHub, Hugging Face, Reddit, AI newsletters) plus Gemini **Grounding** (live web search).
> **Relevance is a hard gate** — only on-niche ideas pass, even if a trend is huge. Tone is
> **accuracy-first / anti-hype** (Islamic-friendly: honest, no exaggeration, verify before publishing).
> Competitor accounts: **none specified → auto-discovered** (see Phase 6.4).

---

## 1. Architecture Overview

```
   EXTERNAL TREND SOURCES                  SCHEDULING (cron → Python jobs)
   HN · Product Hunt · GitHub Trending     daily · weekly · 3×/wk · hourly
   Hugging Face · Reddit · AI-newsletter          │
   RSS · X · YouTube · IG hashtags                ▼
   Gemini Grounding (live web search)   ┌──────────────────────┐ ◄── competitor auto-discovery
        │                               │   DATA ACQUISITION   │
        │   ┌─────────────────────────► │  Instagram Graph API │
        │   │                           │  v25.0 (cursor paged)│
        ▼   │                           └──────────┬───────────┘
   ┌────────┴───────────┐                            │
   │  STORAGE — Supabase (PostgreSQL 17) ◄───────────┘ upsert (idempotent)
   │  15 tables · partitioned · RLS · BRIN · rollups
   └──┬───────────────┬──────────────────┬──────────────────┬───────────┘
      │ perf snapshot │ trend signals    │ exec log          │ metrics
      ▼               ▼                  ▼                   ▼
   ┌──────────────────────────┐   ┌─────────────────────────┐  ┌──────────────┐
   │  AI REPORT (Gemini 3.5)  │   │  TOPIC IDEATION         │  │ ANOMALY      │
   │  structured JSON, ECA    │   │  niche-filtered ideas   │  │ RADAR        │
   │  weekly strategy +       │   └───────────┬─────────────┘  │ instant alert│
   │  forecasts               │               ▼                │ + attribution│
   └────────────┬─────────────┘   ┌─────────────────────────┐  └──────┬───────┘
                │                 │  CONTENT ENGINE         │         │
                │                 │  draft → repurpose →    │         │
                │                 │  predict → schedule →   │         │
                │                 │  publish (HITL gate)    │         │
                │                 └───────────┬─────────────┘         │
                └──────────┬──────────────────┘                       │
                           ▼                                          │
             ┌──────────────────────────────────┐                    │
              │  DELIVERY (Python app)           │ ◄──────────────────┘
             │  Email + Telegram · retry · log  │
             └──────────────────────────────────┘
```

**Core principle:** *Acquire incrementally, store everything, recompute cheaply, generate on
demand.* The AI report is derived from already-cached data, so regenerating it never costs an API
call — only AI tokens.

---

## 2. Tech Stack (verified, with rationale)

| Layer | Choice | Version (verified) | Rationale |
|---|---|---|---|
| Data source | Instagram Graph API | **`v25.0`** base | Latest GA; older versions still callable but deprecate yearly |
| API path | **Facebook Login** path (recommend) | — | Gives Business Discovery (competitor benchmarks) + System User tokens (never expire) |
| Automation | **Python 3.12** app + scheduler | `supercronic` (cron in Docker) | Code-first: testable, version-controlled, full control over logic-heavy steps |
| Scheduler | `supercronic` (cron) or APScheduler | Docker cron sidecar | Invokes job entry points (`python -m app.jobs.<name>`) on schedule |
| Runtime | Docker Compose | — | Two services: `cron` (scheduled jobs) + `bot` (always-on HITL/approvals) |
| Database | Supabase | **Postgres 17** | Managed Postgres, RLS, pg_cron, Edge Functions, Database Webhooks |
| DB access | `supabase-py` + `psycopg` | — | Postgres connection for upserts / raw SQL; `service_role` server-side only |
| HTTP | `httpx` | — | Instagram Graph API + all trend-source connectors, with retries |
| Schema / config | `pydantic` v2, `pydantic-settings` | — | Structured-output validation for Gemini; typed config + secrets |
| AI model | Google Gemini API (AI Studio key) | **`gemini-3.5-flash`** (GA) | $1.50/$9.00 per 1M tok, 1M ctx, structured output; Arabic-capable |
| AI SDK | `google-genai` | — | Native Gemini calls, structured output (JSON schema), Grounding, cost tracking |
| Fallback AI | same API | `gemini-3.1-flash-lite` | ~6× cheaper; used if primary fails or for trivial summaries |
| HITL gate | `python-telegram-bot` | — | Inline Approve/Edit/Skip buttons; always-on `bot` service |
| Notifications | SMTP + Telegram bot | — | Email + Telegram for reports / topics / alerts |
| Language | Egyptian Arabic (العامية المصرية) | — | Required output language |
| **Trend signals** | Hacker News, Product Hunt, GitHub Trending, Hugging Face, Reddit, RSS | free public APIs | `feedparser` (RSS), `praw` (Reddit), `httpx` for the REST sources |
| **Grounding** | Gemini Grounding w/ Google Search | via `google-genai` | Live "what's new in [niche]" queries — the primary freshness engine |
| Optional | X/Twitter API, YouTube Data API | paid / quotad | Add later for extra signal; not needed for MVP |
| **Publishing** | Instagram Content Publishing API | `v25.0` · scope `instagram_content_publish` | Auto-schedule/publish image/carousel/Reels (Business account required). Phase 7.6 |

**Why Python over a visual tool (n8n/Make):** this pipeline is logic-heavy — BUC rate-limit math,
rolling std-dev anomaly detection, opportunity scoring, predictive regression, dedup hashing — all
cleaner, testable, and diffable as code. The one visual-tool convenience (HITL approval UI) is ~50
lines of Telegram-bot inline buttons. Code-first also fits the AI/vibecoding toolchain used to
build and maintain it.

**Why AI Studio (API key) over Vertex AI:** simple API-key auth, generous free tier. Move to Vertex
only if you later need enterprise compliance/IAM.

---

## 3. Phase 1 — Instagram Access & Token Lifecycle (corrected)

### 3.1 Account & app
- **Account:** Instagram **Business or Creator** account (Personal cannot use the API). A **linked
  Facebook Page** is required for the *Facebook Login* path (recommended; see 3.2).
- **App:** Create a **Business** use-case app in the [Meta Developer Portal](https://developers.facebook.com/).
- Submit for **App Review** for any permission beyond your own test users (required before going live
  with real usage; allow days/weeks of lead time).

### 3.2 Choose your API path
| | Facebook Login path (recommended) | Instagram Login path |
|---|---|---|
| Needs FB Page | Yes | **No** |
| Scopes | `instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement` | `instagram_business_basic`, (no separate insights scope — basic covers analytics) |
| System User token (non-expiring) | **Yes** | No |
| Business Discovery (competitor data) | **Yes** | No |
| Base host | `graph.facebook.com` | `graph.instagram.com` |

**Recommendation:** Facebook Login path + **System User token** in Business Manager. System User
tokens **do not expire on time**, eliminating the #1 operational headache (silent token expiry
breaking weekly runs). If you cannot get a System User token, fall back to a 60-day long-lived
user token with the refresh job in §3.4.

### 3.3 Required permissions (Facebook Login path)
`instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`.
Add `instagram_manage_comments` only if you later act on comments.

### 3.4 Token lifecycle automation (critical for unattended operation)
- Store the token + its expiry via `pydantic-settings` env (Docker secrets) or Supabase Vault,
  **never** in code/commits (no DB table for secrets).
- **Hourly cron job** (`app/jobs/token_health.py`): if expiry < 7 days away → refresh
  (`ig_refresh_token` on the Instagram Login path) or, on the Facebook Login path, rotate the System
  User token. If refresh fails → **alert**.
- **Alert rule:** token expiry ≤ 3 days AND refresh failed → page the owner (Telegram/email) before
  the weekly run breaks.

---

## 4. Phase 2 — Database Design (robust, 15 tables)

The original 2-table design loses Reels/Stories data, can't be upserted cleanly, and has no audit
trail or trend memory. This schema is **append-mostly with idempotent upserts**, partitioned for
time-series scale. Tables 8–11 power the Trend Intelligence module (Phase 6).

### 4.1 Tables

```sql
-- (1) Account/profile snapshot — daily append
CREATE TABLE ig_profile_metrics (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  snapshot_date date NOT NULL DEFAULT CURRENT_DATE,
  ig_user_id    text NOT NULL,
  followers_count  int, follows_count int, media_count int,
  -- account-level insights (period=day), 90-day API window
  reach             int, profile_views int, total_views int,
  accounts_engaged  int, follows_and_unfollows int,
  raw_json          jsonb,
  UNIQUE (ig_user_id, snapshot_date)
);

-- (2) Media master (one row per post, upserted by media_id)
CREATE TABLE ig_media (
  media_id        text PRIMARY KEY,
  ig_user_id      text NOT NULL,
  media_type      text,                -- IMAGE|VIDEO|CAROUSEL_ALBUM|REELS
  caption         text,
  permalink       text,
  publish_date    timestamptz NOT NULL,
  first_seen_at   timestamptz NOT NULL DEFAULT now(),
  last_synced_at  timestamptz NOT NULL DEFAULT now()
);

-- (3) Media performance — time-series of per-post metrics (metrics evolve; keep history)
CREATE TABLE ig_media_performance (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  media_id     text NOT NULL REFERENCES ig_media(media_id) ON DELETE CASCADE,
  snapshot_ts  timestamptz NOT NULL DEFAULT now(),
  likes_count, comments_count, reach, views, saved, shares, plays int,
  engagement_rate numeric(6,4) GENERATED ALWAYS AS
    (CASE WHEN reach > 0 THEN (likes_count+comments_count+saved+shares)::numeric / reach END) STORED,
  UNIQUE (media_id, snapshot_ts)
);

-- (4) Stories — MUST be captured within 24h of expiry (separate daily job)
CREATE TABLE ig_stories (
  story_id     text PRIMARY KEY,
  ig_user_id   text NOT NULL,
  publish_ts   timestamptz NOT NULL,
  captured_ts  timestamptz NOT NULL DEFAULT now(),
  exits, views, reach, replies, taps_forward, taps_back int
);

-- (5) Audience demographics — lifetime metric, up to 45 top entries, needs ≥100 followers
CREATE TABLE ig_audience (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ig_user_id    text NOT NULL,
  snapshot_ts   timestamptz NOT NULL DEFAULT now(),
  breakdown     text NOT NULL,         -- age|gender|city|country
  bucket        text NOT NULL,         -- e.g. '18-24', 'male', 'Cairo'
  value         numeric NOT NULL,
  UNIQUE (ig_user_id, snapshot_ts, breakdown, bucket)
);

-- (6) AI reports — full history of generated strategies (so you can diff week-over-week)
CREATE TABLE ai_reports (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ig_user_id      text NOT NULL,
  generated_at    timestamptz NOT NULL DEFAULT now(),
  period_start    date NOT NULL,
  period_end      date NOT NULL,
  model           text NOT NULL,       -- 'gemini-3.5-flash'
  prompt_version  text NOT NULL,       -- e.g. 'egyptian-v3'
  input_tokens    int, output_tokens int, cost_usd numeric(10,4),
  summary         text,                -- short headline
  report_markdown text NOT NULL,       -- full Arabic report
  report_json     jsonb                -- structured output
);

-- (7) Execution/audit log — every pipeline run (observability + idempotency key)
CREATE TABLE pipeline_runs (
  run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_name        text NOT NULL,       -- 'daily_profile'|'weekly_media'|'stories_capture'|'ai_report'
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  status          text NOT NULL,       -- success|failed|partial
  api_calls_used  int DEFAULT 0,
  error           text,
  meta            jsonb                -- buc_budget_remaining, tokens refreshed, etc.
);

-- (8) Niche & account config — single source of truth for relevance + tone (Phase 6)
CREATE TABLE account_config (
  ig_user_id        text PRIMARY KEY,
  niche             text NOT NULL,         -- 'AI / vibecoding creator'
  subtopics         text[],                -- {saas, web, mobile, generative-models, productivity-ai}
  keywords          text[],                -- EN + AR seed terms
  target_hashtags   text[],                -- {vibecoding, aicoding, buildinpublic, cursor, claude}
  brand_voice       text,                  -- 'accuracy-first, anti-hype, practical'
  taboos            text[],                -- {no hype/scammy claims, no piracy, verify before publish}
  offtopic_blocklist  text[],
  monthly_cost_cap_usd numeric DEFAULT 20,   -- hard monthly AI-spend cap (USD); alert 80%, throttle 100%
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- (9) Tracked competitor accounts (auto-discovered, see Phase 6.4)
CREATE TABLE tracked_competitors (
  ig_user_id           text NOT NULL,
  competitor_username  text NOT NULL,
  competitor_ig_id     text,
  reason               text,                -- 'auto: top engager in #vibecoding'
  added_at             timestamptz NOT NULL DEFAULT now(),
  active               boolean NOT NULL DEFAULT true,
  PRIMARY KEY (ig_user_id, competitor_username)
);

-- (10) Raw trend signals — append, dedup on signal_hash
CREATE TABLE trend_signals (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ig_user_id    text NOT NULL,
  source        text NOT NULL,              -- hn|producthunt|github|hf|reddit|rss|twitter|youtube|grounding|ig_hashtag|competitor
  title         text NOT NULL,
  url           text,
  summary       text,
  signal_ts     timestamptz NOT NULL DEFAULT now(),
  momentum      text,                       -- rising|stable|peaked
  signal_hash   text NOT NULL,              -- sha256(url|title) for dedup
  raw_json      jsonb,
  UNIQUE (signal_hash)
);

-- (11) AI-generated topic suggestions — with closed-loop status (Phase 6.5–6.6)
CREATE TABLE topic_suggestions (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ig_user_id        text NOT NULL,
  suggested_at      timestamptz NOT NULL DEFAULT now(),
  title             text NOT NULL,          -- Arabic topic idea
  angle             text,                   -- specific hook / POV
  trend_hook        text,                   -- why now (links signal(s))
  format            text,                   -- Reel|Carousel|Story|Carousel+Reel
  niche_fit         text,                   -- core|adjacent
  opportunity_score numeric(5,2),           -- freshness × fit × low-IG-coverage × your-strength
  suggested_hashtags text[],
  draft_outline     text,                   -- 3-5 bullet hook/structure
  status            text NOT NULL DEFAULT 'suggested', -- suggested|drafted|published|measured|skipped
  published_media_id text,                  -- → ig_media.media_id (closes the loop)
  measured_engagement_rate numeric(6,4),
  prompt_version    text NOT NULL
);

-- (12) Content drafts — AI-generated, versioned, multi-format (Phase 7)
CREATE TABLE content_drafts (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ig_user_id          text NOT NULL,
  topic_suggestion_id uuid REFERENCES topic_suggestions(id) ON DELETE SET NULL,
  parent_repurpose_id uuid REFERENCES content_drafts(id),   -- links repurpose variants to a parent
  format              text NOT NULL,        -- Reel|Carousel|Story|X|LinkedIn
  caption             text,
  hook                text,                 -- first 3s / slide 1 (the make-or-break line)
  body_json           jsonb,                -- {slides:[...]} or {script:"..."}
  hashtags            text[],
  best_time           timestamptz,          -- suggested publish slot (from best_time_slots)
  predicted_engagement numeric(6,4),        -- Phase 7.5
  pred_confidence     numeric(4,2),
  prompt_version      text NOT NULL,
  variant_label       text,                 -- 'A'|'B' for A/B
  media_url           text,                 -- public URL of the image/video asset (Phase 7.7)
  media_source        text DEFAULT 'manual', -- manual (you upload) | generated (AI, off by default)
  status              text NOT NULL DEFAULT 'draft', -- draft|approved|queued|published|skipped
  created_at          timestamptz NOT NULL DEFAULT now()
);

-- (13) Best-time slots — day×hour heatmap, refreshed nightly by pg_cron (Phase 7.2)
CREATE TABLE best_time_slots (
  ig_user_id          text NOT NULL,
  day_of_week         smallint NOT NULL,    -- 0=Sun .. 6=Sat
  hour                smallint NOT NULL,    -- 0..23 (account timezone)
  sample_count        int,
  avg_reach           numeric,
  avg_engagement_rate numeric(6,4),
  score               numeric,              -- combined reach×engagement, normalized 0..1
  updated_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (ig_user_id, day_of_week, hour)
);

-- (14) Publish jobs — Content Publishing API container lifecycle (Phase 7.6)
CREATE TABLE publish_jobs (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_draft_id    uuid NOT NULL REFERENCES content_drafts(id) ON DELETE CASCADE,
  scheduled_at        timestamptz NOT NULL,
  container_id        text,                 -- IG media container id (create step)
  status              text NOT NULL DEFAULT 'queued', -- queued|created|published|failed
  published_media_id  text,                 -- → ig_media.media_id (closes the loop)
  error               text,
  attempts            int NOT NULL DEFAULT 0,
  created_at          timestamptz NOT NULL DEFAULT now()
);

-- (15) Anomalies — detected spikes/drops with attribution (Phase 8)
CREATE TABLE anomalies (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ig_user_id          text NOT NULL,
  detected_at         timestamptz NOT NULL DEFAULT now(),
  metric              text NOT NULL,        -- followers|engagement_rate|reach|post_engagement
  direction           text NOT NULL,        -- spike|drop
  severity            numeric(4,2),         -- how many std-devs from baseline
  expected            numeric, actual numeric,
  attributed_media_id text,                 -- which post caused it (if any)
  notified            boolean NOT NULL DEFAULT false
);
```

### 4.2 Performance & integrity
- **Partition** `ig_profile_metrics`, `ig_media_performance`, `ig_stories` by **month** (Postgres 15+
  declarative range partitioning on the date column) — keeps old partitions droppable/archivable.
- **BRIN indexes** on all timestamp columns (space-efficient on naturally-ordered time data).
- **Generated `engagement_rate`** column guarantees the formula is consistent everywhere:
  `(likes + comments + saved + shares) / reach`. (Define this exactly in §6.2.)
- **RLS:** enable on every table. The Python app / Edge-Function path uses the `service_role` key
  (server-side only, bypasses RLS); a future user-facing dashboard uses `authenticated` with
  policies scoped to `ig_user_id`.

### 4.3 Rollups (pg_cron, nightly)
Refresh a `weekly_summary` **materialized view** (followers Δ, avg engagement, top 3 posts, posting
cadence, best media type). The AI agent reads from this view, not raw tables — keeping prompts small
and cheap.

---

## 5. Phase 3 — Data Acquisition Strategy (rate-limit-aware)

### 5.1 The real rate limit
Instagram uses **Business Use Case (BUC) rate limiting**:
> `calls within 24h = 4800 × (account impressions in last 24h)` per **app + user pair**, rolling 24h.

There is **no fixed "200/hour"** number. A small account (say 500 daily impressions) gets
~2.4M calls/day of budget — effectively unbounded for this use case. A near-zero-activity account
gets a tiny budget. **Monitor the `X-Business-Use-Case` / `X-App-Usage` response headers** and store
remaining budget in `pipeline_runs.meta`. Throttle codes to handle: `4` (app), `17` (user),
`32` (Pages), `613` (BUC), `80005` (instagram).

### 5.2 Scheduled jobs (Instagram + trend)
| Job | Cadence | Why |
|---|---|---|
| **A. Daily profile + stories** | Daily (e.g. 02:00) | Profile = 1 cheap call; **Stories expire in 24h** — this is the #1 data-loss risk the original plan ignored. Capture them daily or lose them forever. |
| **B. Weekly media deep-dive + AI report** | Weekly (Sun 06:00) | Re-fetch last 30 days of media metrics, recompute engagement, run AI. Media insights are retained **2 years** by Meta, so weekly is safe. |
| **C. Hourly token-health check** | Hourly | Refresh/alert on token expiry (§3.4). |
| **D. Trend scan** | 3×/week (Mon/Wed/Fri 08:00) | Fast niche — tools launch daily, so weekly is too slow. Pull fresh signals from HN/PH/GitHub/HF/Reddit/RSS + Gemini Grounding. See Phase 6. |
| **E. Competitor discovery refresh** | Quarterly | Re-rank niche hashtags → add/prune `tracked_competitors`. One-off seed run at setup (Phase 6.4). |

### 5.3 Incremental sync (avoid re-fetching everything)
- Maintain `last_synced_media_id` / `since` cursor per user (store in a `sync_state` table or
  `pipeline_runs.meta`).
- Media list: paginate with cursor-based `after` tokens (not offset). Only fetch posts newer than
  the cursor for *master* records; re-fetch the last 30 days only for *performance* snapshots.
- Account-level insights: **max 90-day query window** per request; paginate backward. Note a **~48h
  data-delay**, so always end the window 2 days ago.
- **Stories:** the 24h lifetime means a daily job is mandatory; also subscribe to the
  `story_insights` **webhook** if you want near-real-time capture.

### 5.4 Idempotency
Every write is an **upsert on the natural key** (`UNIQUE (ig_user_id, snapshot_date)`,
`UNIQUE (media_id, snapshot_ts)`, etc.). Re-running a failed job produces the same result — safe to
retry. `pipeline_runs.run_id` doubles as an idempotency/dedup key for delivery.

---

## 6. Phase 4 — Application Architecture (Python, code-first)

The system is a single **Python 3.12 application** run as two Docker services: `cron` (scheduled
jobs, each a `python -m app.jobs.<name>` process) and `bot` (always-on Telegram bot for HITL
approvals + notifications). All DB writes go through **`psycopg` / `supabase-py`** with raw-SQL
upserts (the Supabase REST client lacks upsert / raw SQL — same caveat the old n8n Supabase node had).

**Project layout:**
```
app/
  config.py              # pydantic-settings: env + secrets (service_role, GEMINI_API_KEY, META_TOKEN…)
  db/ client.py models.py logging.py     # Postgres conn + pipeline_runs helper
  instagram/ client.py token.py          # Graph API v25.0 (cursor paging, views), token store/refresh
  connectors/ hn.py producthunt.py github_trending.py huggingface.py reddit.py rss.py
  ai/ gemini.py grounding.py             # google-genai: structured output (pydantic), fallback, cost
  analysis/ baselines.py anomalies.py best_time.py hashtag_stats.py predict.py
  jobs/ daily_sync.py weekly_media_sync.py weekly_report.py token_health.py
        trend_scan.py topic_ideation.py competitor_discovery.py topic_backfill.py
        anomaly_detect.py auto_draft.py repurpose.py auto_publish.py cost_guard.py weekly_digest.py
  bot/ hitl.py                           # python-telegram-bot: Approve/Edit/Skip inline buttons
  notify/ telegram.py email.py
  utils/ retry.py buc.py                 # backoff + jitter, BUC header parse + budget tracking
prompts/                                 # versioned prompt markdown
supabase/migrations/  supabase/seed/     # SQL schema + niche seed
scheduler/crontab  docker-compose.yml  pyproject.toml  tests/
```

### 6.1 Daily job (profile + stories) — `app/jobs/daily_sync.py`
1. Scheduled daily 02:00 (cron, timezone-aware).
2. Read token + cursors + BUC budget from DB (`app/instagram/token.py`).
3. `GET /v25.0/{ig-user-id}?fields=followers_count,follows_count,media_count`
4. `GET /v25.0/{ig-user-id}/insights?metric=reach,views,accounts_engaged,follows_and_unfollows&period=day&metric_time=end_of_day`
5. `GET /v25.0/{ig-user-id}/stories` → loop insights per story.
6. Upsert `ig_profile_metrics`, `ig_stories` (psycopg).
7. Log a `pipeline_runs` row (calls used, BUC headers, status).

### 6.2 Weekly job (media + AI + delivery) — `app/jobs/weekly_media_sync.py` + `weekly_report.py`
1. Sun 06:00.
2. Fetch media since cursor → per-media insights (use `views`, not `impressions`).
3. Upsert `ig_media` + append `ig_media_performance`.
4. Refresh `weekly_summary` materialized view via `pg_cron` (or a psycopg call).
5. `app/ai/gemini.py` → Gemini 3.5 Flash structured output validated against a **Pydantic** model (§7).
6. (Optional) HITL: `app/bot/hitl.py` sends a Telegram Approve/Edit/Skip for big strategic shifts.
7. `app/notify/` → Email + Telegram with retry (§10).

### 6.3 Retry & backoff (`app/utils/retry.py` — wraps every `httpx` call)
- 3 retries on `429`/`5xx`, **exponential backoff with jitter** (2s ± 1s, 8s ± 4s, 30s ± 10s).
- Honor `Retry-After`. Parse BUC budget from `X-Business-Use-Case` / `X-App-Usage` (`app/utils/buc.py`).
- On terminal failure → `pipeline_runs.status='failed'` + alert (§11).

### 6.4 Trend-scan & topic-ideation (`app/jobs/trend_scan.py` + `topic_ideation.py`) — Phase 6 in brief
1. Mon/Wed/Fri 08:00 (fast niche → 3×/week).
2. Each `app/connectors/*` module pulls one source (HN, Product Hunt, GitHub Trending, Hugging Face,
   Reddit, RSS) → normalize → upsert `trend_signals` (dedup on `signal_hash`).
3. `app/ai/grounding.py` → Grounding query "newest AI coding tools / model launches this week in
   [keywords]" → add hits to `trend_signals` with `source='grounding'`.
4. `app/jobs/topic_ideation.py` → Gemini 3.5 Flash consumes (`account_config` + recent `trend_signals`
   + `weekly_summary` top themes + competitor saturation) → niche-filtered, opportunity-scored topics
   into `topic_suggestions` as structured JSON (Pydantic-validated). Off-niche trends rejected by
   prompt rule (Phase 6.5).
5. `app/notify/` → top 3–5 topics to Telegram (distinct from the Sunday report), with retry.

---

## 7. Phase 5 — AI Integration & Prompt Engineering (structured + versioned)

### 7.1 Model
**`gemini-3.5-flash`** (GA). Pricing: **$1.50 / 1M input, $9.00 / 1M output**. A typical weekly run
(small JSON + ~2k-token Arabic report) costs a **fraction of a cent**. Call it via the **`google-genai`
SDK** (`app/ai/gemini.py`) with an **AI Studio API key**.

### 7.2 Structured output (deterministic, parseable)
Enforce a **Pydantic model** (mapped to the Gemini JSON-schema structured-output capability) so
downstream code can rely on the shape:
```jsonc
{
  "headline": "string",                 // one-line summary (Egyptian Arabic)
  "engagement_rate_avg": "number",      // computed, echoed for verification
  "top_posts": [{"media_id":"string","why":"string"}],
  "what_works": ["string", "..."],
  "what_to_fix": ["string", "..."],
  "growth_opportunities": [{"title":"string","how":"string","effort":"low|med|high"}],
  "next_week_content": ["string", "..."],
  "full_report_markdown": "string"      // the human-readable Egyptian Arabic report
}
```
Store `report_json` *and* `report_markdown` in `ai_reports`.

### 7.3 System prompt (versioned — store `prompt_version` with each report)
> Prompt version `egyptian-v1`. Pin in code; bump when changed; never edit live silently.

> أنت خبير استراتيجي في السوشيال ميديا والتسويق الرقمي. هتسالك على بيانات JSON لحساب انستجرام
> (عدد المتابعين، التفاعل، الريتش/الفيوهات، ومحتوى البوستات).
>
> المهام:
> 1. حلّل الأرقام وقول إيه اللي شغال كويس وإيه اللي محتاج يتغيّر.
> 2. احسب نسبة التفاعل (Engagement Rate) = (لايكات + تعليقات + حفظ + مشاركات) ÷ الريتش، لكل بوست وللمتوسط.
> 3. طلّع 3 فرص نمو واضحة ومحددة قابلة للتنفيذ على طول، مع تقدير المجهود (قليل/متوسط/عالي).
> 4. اقترح أفكار محتوى للأسبوع الجاي بناءً على الأرقام.
> 5. ركّز على الفيوهات (views) مش الـ impressions لأن دي المتريكا الحالية.
>
> **مهم جداً:** الرد كله بالعامية المصرية، بطريقة ودودة ومحفّزة، ومن منظور إسلامي يراعي الضوابط
> (صدق، تجنّب المبالغة، احترام). اتلتزم تماماً بمخطط JSON المطلوب. لو في رقم ناقص قول صراحة "بيانات ناقصة".

**Engineering notes:**
- **Few-shot:** include 1–2 past good reports as examples to lock tone and format.
- **Self-check:** the prompt asks the model to echo `engagement_rate_avg`; the job (`app/ai/gemini.py`)
  compares it to the DB-computed value — if they diverge >10%, flag for review.
- **Dialect caveat:** Egyptian Masri is **not officially benchmarked** by Google. Test 3–5 prompts
  before going live; tune the tone sample if output drifts to MSA.
- **Fallback:** if `gemini-3.5-flash` errors/timeouts, retry once on `gemini-3.1-flash-lite`
  (cheaper, weaker) and tag the report `model=fallback`.

---

## 8. Phase 6 — Trend Intelligence & Topic Ideation (niche-scoped)

**Goal:** detect what's *fresh and on-niche* (new AI tools, model launches, vibecoding discourse)
and convert it into concrete, opportunity-scored content ideas mapped to the formats that perform for
**this** account. **Hard rule: never suggest generic viral content.** Every idea must pass a niche
relevance gate and map to your strengths. For a tools/news niche, *being early* is the win, so the
engine explicitly scores "fresh + on-niche + not-yet-covered on Instagram + matches a format you're
good at".

### 8.1 Niche config — the relevance gate
Everything reads from one configurable row in `account_config` (§4, table 8):
- `niche`, `subtopics`, `keywords` (EN + AR), `target_hashtags`
- `brand_voice`, `taboos` (e.g. *no hype, no piracy, verify before publishing*), `offtopic_blocklist`
- tracked competitors (auto-discovered, §8.4)

The AI uses this as a **hard filter** — anything off-niche is dropped regardless of virality. Update
this row as the niche evolves; never hardcode it in prompts.

### 8.2 Trend sources (niche-specific, ranked by freshness)
For the AI/vibecoding niche the freshest signals are **off-Instagram**:

| Source | What it gives | Access | Cost |
|---|---|---|---|
| **Gemini Grounding (Google Search)** ⭐ | live web: "newest AI coding tools / model launches" | built into the Gemini node | per-query |
| **Hacker News** | dev/AI-tool launches & discussion | `hn.algolia.com/api`, Firebase API | free |
| **Product Hunt** | new AI tools shipping daily | GraphQL API | free tier |
| **GitHub Trending** | hot AI/LLM repos | scrape / community mirrors | free |
| **Hugging Face** | trending models & papers (`/api/trending`) | public API | free |
| **Reddit** | r/LocalLLaMA, r/ChatGPTCoding, r/SideProject, r/SaaS top | Reddit API (OAuth) | free tier |
| **AI newsletters RSS** | curated: Simon Willison, TLDR AI, Ben's Bites, The Rundown | RSS | free |
| Instagram hashtags | #vibecoding #aicoding #buildinpublic #cursor #claude (FB Login path) | Graph API | API budget |
| Business Discovery | tracked competitors' recent top media | Graph API | API budget |
| **Optional** | X/Twitter, YouTube Data API | API tier | paid/quotad — add later |

**MVP:** start with the free tier (Grounding + HN + PH + GitHub + HF + Reddit + RSS). That alone
covers launches before they reach Instagram. Add X/YouTube for extra signal later.

### 8.3 Trend-scan job (3×/week)
Cadence **Mon/Wed/Fri** — this niche moves daily, so a weekly scan always makes you late. Each scan:
fetch each source's **top 30** items since the last scan (cap per source, configurable) → normalize
into `{source,title,url,summary,ts, momentum}` → upsert into `trend_signals` (dedup on
`sha256(url|title)`). Keep raw JSON for the AI. Momentum (`rising|stable|peaked`) is inferred from
how fast a signal repeats across sources.

### 8.4 Competitor auto-discovery (seed once, refresh quarterly)
You have no competitor list, so the system builds one:
1. Query your `target_hashtags` → collect accounts appearing with strong engagement.
2. Rank by (engagement_rate, recency, follower fit) → seed `tracked_competitors` with the top 5–10.
3. **Quarterly** recompute: add risers, prune dormant ones.
4. Weekly, **Business Discovery** pulls each competitor's recent top media → store as
   `trend_signals` with `source='competitor'`. This tells the model *what's already saturated*
   so it can steer you toward gaps instead of copycat content.

### 8.5 Topic ideation (AI, niche-filtered, opportunity-scored)
Runs on scan days (lightweight) and folds a summary into the Sunday report. Input to Gemini 3.5
Flash: (1) `account_config`, (2) `trend_signals` from the last 7 days, (3) your top-performing
themes/formats from `weekly_summary`, (4) competitor-saturation signals.

Structured output → `topic_suggestions`:
```jsonc
{
  "topics": [{
    "title": "...",                 // Egyptian Arabic topic idea
    "angle": "...",                 // specific hook / POV
    "trend_hook": "...",            // why now (e.g. "X أطلقوا الأداة من يومين")
    "format": "Reel|Carousel|Story|Carousel+Reel",  // chosen from what works for YOU
    "niche_fit": "core|adjacent",   // relevance verdict
    "opportunity_score": 0-100,     // freshness × niche-fit × low-IG-coverage × your-strength
    "suggested_hashtags": ["..."],
    "why_now": "...",
    "draft_outline": "..."          // 3–5 bullet hook/structure to start scripting
  }]
}
```

**Opportunity score (the differentiator for a tools/news niche):** high = *fresh launch* + *on-niche*
+ *few IG creators have covered it yet* + *matches a format you perform in*. First-mover coverage of
a brand-new tool is the single highest-value play in this niche, so the score rewards it.

**Relevance gate & accuracy rules (baked into the prompt):**
- Drop anything off-niche — even massive trends — if it doesn't map to `account_config`.
- **Never invent tools/features.** Only use signals present in the provided data + Grounding
  citations. If unsure → mark `draft_outline` with "اتأكد قبل النشر" (verify before publishing).
- Prefer signals < 7 days old; explicitly flag ones where IG coverage is still low.

### 8.6 Closed-loop learning (topics get smarter over time)
Each `topic_suggestions` row has a `status`: `suggested → drafted → published → measured → skipped`.
When you publish, set `published_media_id` to the new `ig_media.media_id`. Two weeks later, a job
backfills `measured_engagement_rate` and compares it to your account average. Winning topics become
few-shot examples in future prompts, so the model learns which of *its* ideas actually land with
*your* audience — the loop that makes suggestions improve week over week.

### 8.7 Topic prompt (versioned — `topics-vibecoding-v1`)
> أنت ستراتيجيست محتوى متخصص في نيش "الـ vibecoding" وبناء التطبيقات والسايتات بأدوات الذكاء
> الاصطناعي (Claude وغيره). هتاخد: (1) ملف النيش والكلمات المفتاحية، (2) إشارات ترندز من آخر أسبوع
> (أدوات وموديلات جديدة، نقاشات)، (3) أنواع المحتوى اللي بتنجح معايا، (4) المحتوى اللي المنافسين
> غطوه بالفعل.
>
> المطلوب: اقترح 3–5 أفكار محتوى **فقط داخل النيش**. لكل فكرة: عنوان، زاوية محددة، ليه دلوقتي
> (trend hook)، الفورمات (Reel/Carousel/Story) المناسب ليا، وخطاف/هيكل مبدئي. رتّبهم حسب
> فرصة الإبهار (fresh + on-niche + مفيش حد غطاه على انستجرام + يناسب نقاط قوتي).
>
> **قواعد صارمة:** ممنوع اقتراح ترندز عامة برة النيش حتى لو بتتفاعل. **ماتخترعش** أداة ولا ميزة
> غير موجودة في البيانات؛ لو مش متأكد اكتب "اتأكد قبل النشر". الرد بالعامية المصرية، نبرة
> عملية وصادقة (بدون مبالغة)، وبترتيب JSON المطلوب بالظبط.

**Notes:** Grounding lets the model cite where it saw a launch — store citations in
`trend_signals.raw_json` so you can verify. Re-run the 3–5 prompt test before going live and tune the
tone if output drifts to MSA.

---

## 9. Phase 7 — Content Engine (idea → published, closed loop)

The system so far *measures* and *ideates*. This phase closes the loop: turn each approved topic into
near-ready multi-format content, schedule it at the optimal time, publish automatically behind a
human gate, and predict how it will do — then feed the result back into learning. Tables 12–15.

### 9.1 Auto-draft (topic → near-ready post)
On-demand (from a delivered topic) or batched, the AI Agent runs on a `topic_suggestion` +
`account_config.brand_voice` + your 3–5 best past captions (few-shot) to generate, in Egyptian Arabic:
- **caption** (on-brand, CTA included) · **hook** (first 3s / slide 1 — the make-or-break line)
- **carousel slides** (if Carousel) or **Reel script / talking points** (if Reel)
- **hashtag set** (optimized & rotated, see 9.4) · **suggested best-time** (9.2) · **predicted engagement** (9.5)
Stored in `content_drafts` with `status='draft'`, versioned. Generate **2 variants (A/B)** when the
topic's `opportunity_score` is high.

### 9.2 Best-time-to-post (derived from your own data)
A nightly `pg_cron` job aggregates `ig_media_performance` into the `best_time_slots` heatmap
(avg reach & engagement by **day-of-week × hour**, normalized `score`). The drafter tags each draft
with its top slot; high-confidence slots surface in the Sunday report. Only uses posts ≥48h old
(the data-delay window); recomputes weekly.

### 9.3 Repurposing (one idea → every format)
From one approved topic/outline, a single AI pass emits variants — **Reel script, Carousel, Story
sequence, and a short X/LinkedIn post** — linked by `parent_repurpose_id`. Maximizes reach per idea
and feeds cross-platform publishing (optional X/LinkedIn APIs; the IG variant feeds auto-publish).

### 9.4 Hashtag optimization
Track per-hashtag historical reach/engagement (parsed from `ig_media.caption` tags); rotate the set
per post (avoid penalized repetition), mix broad + niche tags, cap ~10–15. Generated per draft;
performance flows back into the ranking so weak tags decay out.

### 9.5 Predictive forecasting
- **Per-draft prediction:** features (format, topic cluster, hour-slot, caption length, hashtag count,
  your recent avg engagement) → predicted engagement + confidence band. Shown on each draft so you
  prioritize the strongest. Start with regression / LLM-heuristic — **no heavy ML**.
- **Follower trajectory:** project next-30-day growth from `ig_profile_metrics` (exponential
  smoothing); surfaced in the report. Track forecast accuracy over time and recalibrate.

### 9.6 Auto-publish / schedule (with mandatory human gate)
Uses the Instagram **Content Publishing API** (`instagram_content_publish` scope; Business account
required; image/video/carousel/Reels via create-container → publish). `publish_jobs` (table 14)
tracks each container's lifecycle. **Mandatory HITL gate**: a draft enters `status='queued'` → the
always-on **Telegram bot** (`app/bot/hitl.py`) sends a one-tap **Approve / Edit / Skip** inline
keyboard → on approve, `app/jobs/auto_publish.py` creates the container and publishes at the draft's
`best_time` — **only if `media_url` is set** (see 9.7); otherwise it stays `queued` and pings you to
attach media. The resulting `media_id` is written back to `content_drafts` and `topic_suggestions` —
**closing the learning loop** (Phase 6.6).

### 9.7 Media assets (manual now, AI-generated later — NOT auto-wired)
Content Publishing requires the actual image/video at a **public URL**; the drafter produces *text*
only, so media is a deliberately **decoupled** step:

- **Now (manual upload — default):** you create/export the asset, upload it to a **Supabase Storage**
  bucket (public path), and paste the URL into `content_drafts.media_url` (`media_source='manual'`).
  The publish gate (9.6) just reads this field. **Nothing generates or fetches media automatically.**
- **Later (AI generation — off by default, behind a flag):** an optional job can call an image/video
  model (carousel cover, short Reel clip) to fill `media_url` with `media_source='generated'`. This
  stays **un-wired** — invoked only when you explicitly enable it after the rest is proven. It writes
  to the same `media_url` column, so 9.6 needs no changes.

> **Why decoupled:** lets you validate drafting, scheduling, and the publish gate with your own media
> first, then bolt generation on later without touching the core flow.

> **Scope note:** Content Publishing is a separately-reviewed permission and has per-account daily
> limits; ship the gate first, auto-publish last (see rollout v5).

---

## 10. Phase 8 — Delivery

- **Channels:** Email (SMTP node, HTML + markdown) + one messenger (Telegram bot webhook or Discord).
- **Idempotent:** include `run_id` in the message; dedupe on receiver side. Re-runs don't spam.
- **Retry:** 3 attempts with backoff on the output node; on failure → alert (§11) and the report is
  still safely stored in `ai_reports` for manual retrieval.
- **Archive:** every report is queryable from `ai_reports` (week-over-week diffing becomes trivial).

---

## 11. Phase 9 — Reliability, Observability & Security

**Reliability**
- Every job writes a `pipeline_runs` row: `started_at`, `finished_at`, `status`, `api_calls_used`,
  `error`, `meta`. Partial success is a distinct status (`partial`).
- Exponential-backoff retry on all HTTP and notify calls (§6.3).
- **Idempotent upserts** mean any job is safe to re-run after a crash.

**Observability & alerting** (Python `app/notify/` + a Supabase Database Webhook option)
- Alert (Telegram/email) on: any `failed`/`partial` run · token expiry ≤ 7d · refresh failure ·
  BUC budget < 15% · AI cost spikes · no new posts captured in 14 days · **no stories captured in the
  last 25h** (24h-expiry data-loss risk).
- Weekly digest: followers Δ, avg engagement, posts published, cost spent.

**Anomaly detection (instant radar)** — runs after each daily sync
- Compare today's metrics to rolling baselines (7-day & 28-day mean ± std-dev); alert when a metric
  exceeds the **default ≥3σ** over the 28-day baseline (configurable in `account_config`). Covers
  follower spike/drop, engagement spike/drop (account-level or a single post), a post beating/missing
  its prediction.
- On detection → instant Telegram alert with **attribution** (which post/time caused it) and an
  `anomalies` row (table 15). Turns the system from a weekly digest into a real-time radar.

**Cost guardrails** — hard monthly AI-spend cap (`account_config.monthly_cost_cap_usd`, default $20)
- Every AI call writes its token cost into `pipeline_runs.meta`; a monthly aggregate compares to the cap.
- **80%** → alert; **100%** → auto-throttle non-essential AI (topic ideation, drafting, repurposing)
  while keeping data acquisition + anomaly radar running (they're cheap/essential). You can raise the
  cap in `account_config` anytime. No surprise bills.

**Security**
- **No secrets in code/commits.** Tokens/API keys live in `pydantic-settings` env (Docker secrets)
  or Supabase Vault — referenced, never printed. Never log a token.
- **RLS** on all tables; `service_role` key used only server-side (Python app; Supabase Edge
  Functions are available but **unused** — all compute lives in the Python app).
- **Principle of least permission:** request only the scopes in §3.3.
- **Network:** restrict Supabase to known IPs for the self-hosted app; rotate keys quarterly.
- Keep Python deps + Docker images current (pin versions; patch regularly).

---

## 12. Phase 10 — Rollout Plan (ship in slices)

| Milestone | Scope | Definition of done |
|---|---|---|
| **MVP (week 1)** | Manual token · daily profile job + stories capture · Postgres upsert · `pipeline_runs` logging | 7 consecutive days of clean daily snapshots in Supabase; stories not lost. |
| **v1 (week 2)** | Weekly media deep-dive · materialized rollup · Gemini 3.5 Flash structured report · email delivery | One correct Egyptian Arabic report delivered; `engagement_rate` self-check passes. |
| **v2 (week 3)** | Token auto-refresh + expiry alerts · retry/backoff · Telegram delivery · HITL approval gate · **competitor auto-discovery + Business Discovery seeding** · cost/observability dashboard | Runs unattended for 2 weeks with zero manual intervention; alerts fire correctly on injected failures. |
| **v3 (week 4)** | **Trend Intelligence (Phase 6) + anomaly radar (Phase 9):** 3×/wk trend scan (HN/PH/GitHub/HF/Reddit/RSS + Grounding) → `trend_signals`; niche-filtered topic ideation → `topic_suggestions`; daily anomaly detection → instant alerts with attribution | One week of **niche-relevant, non-generic** ideas; every idea passes the relevance gate; competitor list auto-built; an injected follower/engagement spike triggers a correct attributed alert. |
| **v4 (week 5–6)** | **Content Engine (Phase 7), minus auto-publish:** auto-draft (caption/hook/slides/script/hashtags) · `best_time_slots` heatmap · repurposing · per-draft prediction + follower forecast | From an approved topic, a near-ready multi-format draft set in Egyptian Arabic, each tagged with a best-time and a predicted-engagement band; forecast accuracy tracked. |
| **v5 (week 7)** | **Auto-publish with HITL gate (Phase 7.6):** Content Publishing API approval + `publish_jobs` lifecycle → scheduled container publish at best-time → `media_id` back-link | One Reel/Carousel published automatically via the Approve gate at its predicted best time; the post links back to its draft & topic, closing the loop end-to-end. |

This slice order front-loads value: a working report in **week 2**, resilience in **week 3**, the
**differentiating trend engine** in week 4, the **content engine** in weeks 5–6, and **full
automation (publish)** in week 7 — each slice independently useful, the inverse risk of the original
single-shot plan.

---

## 13. Phase 11 — Testing & Validation Checklist

- [ ] **Token:** System User token (FB path) validated; expiry = never. If 60-day token: refresh
      job proven to extend it; alert fires when forcibly expired.
- [ ] **API version:** confirm `v25.0` responds; run one of each endpoint (profile, media, media
      insights, stories, account insights, demographics).
- [ ] **Metric correctness:** use `views`/`total_views`, not `impressions`, in all queries.
- [ ] **Rate limit:** log `X-Business-Use-Usage` headers; confirm BUC budget math; inject a `429`
      and verify backoff + retry succeeds.
- [ ] **Data retention:** stories captured within 24h; account-insights query ends 48h before now;
      no query exceeds 90-day window.
- [ ] **Idempotency:** re-run the weekly job twice → identical DB state, no duplicate rows, no
      duplicate delivered messages (dedupe on `run_id`).
- [ ] **AI:** structured output validates against schema; echoed engagement-rate within 10% of DB
      value; report is Egyptian Arabic (spot-check); fallback model triggers on primary failure.
- [ ] **Trends (Phase 6):** scan pulls from ≥3 sources; signals dedup correctly on `signal_hash`;
      Grounding citations are stored and spot-verified accurate.
- [ ] **Relevance gate:** feed the model an off-niche viral trend → it must be **rejected**; feed an
      on-niche fresh launch → it must produce a topic with a `why_now` + `opportunity_score`.
- [ ] **Accuracy:** the model never invents a tool/feature not present in the provided signals.
- [ ] **Closed loop:** a published topic links to its `media_id`; the backfill job populates
      `measured_engagement_rate` 2 weeks later.
- [ ] **Content Engine (Phase 7):** auto-draft produces a valid multi-format draft from a topic
      (Egyptian Arabic, on-brand); `best_time_slots` fills from real history; repurpose variants link
      via `parent_repurpose_id`; per-draft prediction + follower forecast emit a confidence band.
- [ ] **Predictions:** forecast tracks vs actual over 2 weeks; per-draft predictions correlate with
      measured engagement (directionally correct ≥70%).
- [ ] **Anomaly radar:** inject a spike/drop → instant attributed alert + `anomalies` row; normal
      days produce no false alerts.
- [ ] **Auto-publish (Phase 7.6):** a queued draft cannot publish without the Approve gate; approved
      draft creates a container and publishes at `best_time`; `published_media_id` back-links to
      `content_drafts` and `topic_suggestions`.
- [ ] **Media assets (§9.7):** publish is blocked while `media_url` is empty (pings you); a manual
      upload to the Storage bucket + paste unblocks it; generation stays off by default.
- [ ] **Cost guardrails:** injecting spend to 80% fires an alert; at 100% non-essential AI throttles
      while data acquisition + anomaly radar keep running; raising the cap resumes it.
- [ ] **Security:** no token/key appears in app logs or `pipeline_runs`; RLS blocks
      anonymous reads.
- [ ] **Failure modes:** kill DB / block API / revoke token → correct `failed` status + alert.

---

## Appendix A — Verified facts vs. original-plan claims

| Original claim | Verified reality | Source |
|---|---|---|
| API `v22.0` | **`v25.0`** (Feb 18, 2026) is latest; ~4-month cadence | Meta changelog |
| "200 calls/hour per user token" | **BUC: `4800 × impressions` per 24h, per app+user**; per-user limit undisclosed | Meta Rate Limiting doc |
| Single API path | **Two paths**: Instagram Login (no Page) vs Facebook Login (Page + System User + Business Discovery) | Meta docs |
| `impressions` metric | **Deprecated ~Apr 2025 → `views`** (still in some stale doc examples) | Brandwatch/Supermetrics + Meta community |
| `gemini-3.5-flash` "May 2026" | **Real — released May 19, 2026 (Google I/O), GA**; use GA ID (not `-preview`) | DeepMind / Google Cloud docs |
| "most cost-efficient" | True among *frontier* models; Flash-Lite is cheaper (non-frontier) | Vertex pricing |
| n8n "v2.0 AI-first" | v2.x real (2.27.5); AI first-class **since v1.0 (2023)**; 2.0 was cleanup/security | npm + GitHub releases |
| Supabase "SQLite pooling drivers" | **Hallucination** — Supabase is **Postgres 17**; SQLite change in n8n 2.0 was to n8n's *own* internal DB | n8n release PR #22336 |
| Supabase node = upsert/query | Native Supabase node has **no upsert / no SQL** — use **Postgres node** | n8n Supabase/Postgres node docs |

**Key data-retention facts:** Media insights **2 yrs** · Account insights **90 days** · Stories
**24h** after expiry · max **90-day** query window · up to **48h** data delay · some metrics need
**≥100 followers**.

---

## Appendix B — Source links
- Meta changelog: `developers.facebook.com/docs/graph-api/changelog`
- Rate limiting: `developers.facebook.com/docs/graph-api/overview/rate-limiting`
- IG User / Insights: `developers.facebook.com/docs/instagram-api/reference/ig-user`
- Access tokens: `developers.facebook.com/docs/facebook-login/access-tokens/`
- Gemini 3.5 Flash: `docs.cloud.google.com/.../models/gemini/3-5-flash` · `deepmind.google/models/gemini/flash/`
- Gemini pricing: `cloud.google.com/.../generative-ai/pricing`
- Python libs: `google-genai` (ai.google.dev/gemini-api/docs/sdks) · `httpx` · `pydantic` · `supabase-py` · `psycopg` · `python-telegram-bot` · `feedparser` · `praw`
- Supabase: `supabase.com/docs` (Postgres 17, RLS, pg_cron, Edge Functions, Database Webhooks)
- Scheduler: `supercronic` `github.com/aptible/supercronic` (or APScheduler `apscheduler.readthedocs.io`)
- Gemini Grounding (Google Search): `docs.cloud.google.com/.../grounding`
- Trend sources: Hacker News `github.com/HackerNews/API` · Product Hunt API `api.producthunt.com/v2/docs` · Hugging Face `huggingface.co/docs/hub/api` · Reddit API `support.reddithelp.com` · Google Trends RSS `trends.google.com/trends/api/rss`
- Instagram Content Publishing API: `developers.facebook.com/docs/instagram-api/guides/content-publishing`

---

## Appendix C — Setup Runbook (first day → first report)

> You're building this for yourself first; the schema is already keyed by `ig_user_id` so going
> multi-account/public later is mostly an RLS policy change. Do these in order.

**1. Supabase (≈20 min)**
1. Create a project (Postgres 17). Save the **project ref**, **DB connection string**, and
   **`service_role` key** (server-side only — never expose).
2. Run the 15 table definitions from §4 as a migration (Supabase → SQL Editor, or `supabase migration`).
3. Enable **`pg_cron`** + **`pg_net`** (Database → Extensions); add the nightly rollup + `best_time_slots`
   refresh jobs (§4.3, §9.2).
4. Create a **Storage bucket** (`content-media`) for manual media uploads (§9.7); set it public-read.

**2. Meta / Instagram (≈30 min + review time)**
5. In the [Meta Developer Portal](https://developers.facebook.com/): create a **Business** app → add the
   **Instagram** product → link your **IG Business account** + **Facebook Page**.
6. Note your **`ig-user-id`** (Graph API Explorer: `GET /me/accounts` → page → `instagram_business_account`).
7. In **Business Manager → System Users**, create a System User and assign it to the Page → generate a
   **System User token** (does not expire). Request scopes from §3.3 (+ `instagram_content_publish` for v5).
8. (Later) submit **App Review** if you open it beyond your own test users.

**3. Google Gemini (≈5 min)**
9. [Google AI Studio](https://aistudio.google.com/) → **Get API key**. Model = `gemini-3.5-flash` (GA).

**4. Python app (≈30 min)**
10. `git clone` the project; copy `.env.example` → `.env` and fill: `SUPABASE_DB_URL`,
    `SUPABASE_SERVICE_ROLE_KEY`, `GEMINI_API_KEY`, `META_TOKEN` + `IG_USER_ID`, `TELEGRAM_BOT_TOKEN`
    + `TELEGRAM_CHAT_ID`, SMTP settings. (Secrets via `pydantic-settings`; never commit.)
11. `docker compose up -d` → starts the `cron` service (supercronic) + `bot` service (Telegram HITL).
12. Edit `scheduler/crontab` to register the job entry points: daily (§6.1), weekly report (§6.2),
    token-health (§3.4), trend-scan (§6.4), and (later) content-engine + publish-gate.

**5. Seed & dry-run (≈15 min)**
13. Insert your row into `account_config` (niche = "AI / vibecoding creator", keywords, hashtags, voice,
    `monthly_cost_cap_usd`).
14. **Run the daily job manually** (`python -m app.jobs.daily_sync`) → verify rows appear in
    `ig_profile_metrics` / `ig_stories`.
15. **Run the weekly job manually** (`python -m app.jobs.weekly_report`) → confirm the Egyptian Arabic
    report lands in `ai_reports` + email, and the `engagement_rate` self-check (§7) passes.
16. Only then **enable the schedules** in `scheduler/crontab` (daily 02:00, weekly Sun 06:00,
    trend-scan Mon/Wed/Fri 08:00) and restart the `cron` service.

**Definition of a working MVP:** step 15 succeeds and you have 7 clean daily snapshots — you're ready to
layer Trend Intelligence (Phase 6) and the Content Engine (Phase 7) per the rollout.
