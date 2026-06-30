-- 0001_init_schema.sql — Instagrowth core schema (15 tables)
-- Idempotent upserts are keyed on natural UNIQUE/PK keys (see app/db code).
-- Three time-series tables are RANGE-partitioned by month in 0003_indexes_partitions.sql.

-- (1) Account/profile snapshot — daily append, partitioned by snapshot_date ----------
CREATE TABLE IF NOT EXISTS ig_profile_metrics (
    id                  bigint GENERATED ALWAYS AS IDENTITY,
    snapshot_date       date NOT NULL DEFAULT CURRENT_DATE,
    ig_user_id          text NOT NULL,
    followers_count     int,
    follows_count       int,
    media_count         int,
    reach               int,            -- account-level insights, period=day
    profile_views       int,
    total_views         int,            -- use views/total_views, NOT impressions
    accounts_engaged    int,
    follows_and_unfollows int,
    raw_json            jsonb,
    PRIMARY KEY (ig_user_id, snapshot_date)
) PARTITION BY RANGE (snapshot_date);

-- (2) Media master — one row per post, upserted by media_id --------------------------
CREATE TABLE IF NOT EXISTS ig_media (
    media_id        text PRIMARY KEY,
    ig_user_id      text NOT NULL,
    media_type      text,               -- IMAGE|VIDEO|CAROUSEL_ALBUM|REELS
    caption         text,
    permalink       text,
    publish_date    timestamptz NOT NULL,
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    last_synced_at  timestamptz NOT NULL DEFAULT now()
);

-- (3) Media performance — per-post time-series, partitioned by snapshot_ts ------------
CREATE TABLE IF NOT EXISTS ig_media_performance (
    id              bigint GENERATED ALWAYS AS IDENTITY,
    media_id        text NOT NULL REFERENCES ig_media(media_id) ON DELETE CASCADE,
    snapshot_ts     timestamptz NOT NULL DEFAULT now(),
    likes_count     int,
    comments_count  int,
    reach           int,
    views           int,                -- views, not impressions
    saved           int,
    shares          int,
    plays           int,
    engagement_rate numeric(6,4) GENERATED ALWAYS AS
        (CASE WHEN reach IS NOT NULL AND reach > 0
              THEN (COALESCE(likes_count,0) + COALESCE(comments_count,0)
                    + COALESCE(saved,0) + COALESCE(shares,0))::numeric / reach
              END) STORED,
    PRIMARY KEY (media_id, snapshot_ts)
) PARTITION BY RANGE (snapshot_ts);

-- (4) Stories — MUST be captured within 24h of expiry, partitioned by publish_ts ------
CREATE TABLE IF NOT EXISTS ig_stories (
    story_id        text NOT NULL,
    ig_user_id      text NOT NULL,
    publish_ts      timestamptz NOT NULL,
    captured_ts     timestamptz NOT NULL DEFAULT now(),
    exits           int,
    views           int,
    reach           int,
    replies         int,
    taps_forward    int,
    taps_back       int,
    PRIMARY KEY (story_id, publish_ts)
) PARTITION BY RANGE (publish_ts);

-- (5) Audience demographics — lifetime metric, ≥45 buckets, needs ≥100 followers -------
CREATE TABLE IF NOT EXISTS ig_audience (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ig_user_id      text NOT NULL,
    snapshot_ts     timestamptz NOT NULL DEFAULT now(),
    breakdown       text NOT NULL,      -- age|gender|city|country
    bucket          text NOT NULL,      -- e.g. '18-24', 'male', 'Cairo'
    value           numeric NOT NULL,
    UNIQUE (ig_user_id, snapshot_ts, breakdown, bucket)
);

-- (6) AI reports — full history of generated strategies (week-over-week diffing) -------
CREATE TABLE IF NOT EXISTS ai_reports (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ig_user_id      text NOT NULL,
    generated_at    timestamptz NOT NULL DEFAULT now(),
    period_start    date NOT NULL,
    period_end      date NOT NULL,
    model           text NOT NULL,      -- 'gemini-3.5-flash'
    prompt_version  text NOT NULL,      -- e.g. 'egyptian-strategy-v1'
    input_tokens    int,
    output_tokens   int,
    cost_usd        numeric(10,4),
    summary         text,               -- short headline
    report_markdown text NOT NULL,      -- full Arabic report
    report_json     jsonb
);

-- (7) Execution / audit log — every pipeline run (observability + idempotency) ---------
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name        text NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    status          text NOT NULL,      -- success|failed|partial
    api_calls_used  int DEFAULT 0,
    error           text,
    meta            jsonb               -- buc_budget_remaining, tokens_refreshed, cost_usd …
);

-- (8) Niche & account config — single source of truth for relevance + tone ------------
CREATE TABLE IF NOT EXISTS account_config (
    ig_user_id          text PRIMARY KEY,
    niche               text NOT NULL,          -- 'AI / vibecoding creator'
    subtopics           text[],                 -- {saas, web, mobile, generative-models, productivity-ai}
    keywords            text[],                 -- EN + AR seed terms
    target_hashtags     text[],                 -- {vibecoding, aicoding, buildinpublic, cursor, claude}
    brand_voice         text,                   -- 'accuracy-first, anti-hype, practical'
    taboos              text[],                 -- {no hype/scammy claims, no piracy, verify before publish}
    offtopic_blocklist  text[],
    monthly_cost_cap_usd numeric DEFAULT 20,    -- hard monthly AI-spend cap (USD); alert 80%, throttle 100%
    anomaly_sigma_threshold numeric(4,2) DEFAULT 3.0,  -- ≥Nσ anomaly trigger (default ≥3σ)
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- (9) Tracked competitor accounts (auto-discovered) ------------------------------------
CREATE TABLE IF NOT EXISTS tracked_competitors (
    ig_user_id           text NOT NULL,
    competitor_username  text NOT NULL,
    competitor_ig_id     text,
    reason               text,                  -- 'auto: top engager in #vibecoding'
    added_at             timestamptz NOT NULL DEFAULT now(),
    active               boolean NOT NULL DEFAULT true,
    PRIMARY KEY (ig_user_id, competitor_username)
);

-- (10) Raw trend signals — append, dedup on signal_hash --------------------------------
CREATE TABLE IF NOT EXISTS trend_signals (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ig_user_id      text NOT NULL,
    source          text NOT NULL,              -- hn|producthunt|github|hf|reddit|rss|grounding|ig_hashtag|competitor
    title           text NOT NULL,
    url             text,
    summary         text,
    signal_ts       timestamptz NOT NULL DEFAULT now(),
    momentum        text,                       -- rising|stable|peaked
    signal_hash     text NOT NULL,              -- sha256(url|title) for dedup
    raw_json        jsonb,
    UNIQUE (signal_hash)
);

-- (11) AI-generated topic suggestions — closed-loop status ------------------------------
CREATE TABLE IF NOT EXISTS topic_suggestions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ig_user_id          text NOT NULL,
    suggested_at        timestamptz NOT NULL DEFAULT now(),
    title               text NOT NULL,          -- Arabic topic idea
    angle               text,                   -- specific hook / POV
    trend_hook          text,                   -- why now (links signal(s))
    format              text,                   -- Reel|Carousel|Story|Carousel+Reel
    niche_fit           text,                   -- core|adjacent
    opportunity_score   numeric(5,2),           -- freshness × fit × low-IG-coverage × your-strength
    suggested_hashtags  text[],
    draft_outline       text,                   -- 3-5 bullet hook/structure
    status              text NOT NULL DEFAULT 'suggested',  -- suggested|drafted|published|measured|skipped
    published_media_id  text,                   -- → ig_media.media_id (closes the loop)
    measured_engagement_rate numeric(6,4),
    prompt_version      text NOT NULL
);

-- (12) Content drafts — AI-generated, versioned, multi-format --------------------------
CREATE TABLE IF NOT EXISTS content_drafts (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ig_user_id          text NOT NULL,
    topic_suggestion_id uuid REFERENCES topic_suggestions(id) ON DELETE SET NULL,
    parent_repurpose_id uuid REFERENCES content_drafts(id),   -- links repurpose variants to a parent
    format              text NOT NULL,           -- Reel|Carousel|Story|X|LinkedIn
    caption             text,
    hook                text,                    -- first 3s / slide 1
    body_json           jsonb,                   -- {slides:[...]} or {script:"..."}
    hashtags            text[],
    best_time           timestamptz,             -- suggested publish slot (from best_time_slots)
    predicted_engagement numeric(6,4),
    pred_confidence     numeric(4,2),
    prompt_version      text NOT NULL,
    variant_label       text,                    -- 'A'|'B' for A/B
    media_url           text,                    -- public URL of the asset (manual upload by default)
    media_source        text DEFAULT 'manual',   -- manual | generated (off by default)
    status              text NOT NULL DEFAULT 'draft',  -- draft|approved|queued|published|skipped
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- (13) Best-time slots — day×hour heatmap, refreshed nightly by pg_cron -----------------
CREATE TABLE IF NOT EXISTS best_time_slots (
    ig_user_id          text NOT NULL,
    day_of_week         smallint NOT NULL,       -- 0=Sun .. 6=Sat
    hour                smallint NOT NULL,       -- 0..23 (account timezone)
    sample_count        int,
    avg_reach           numeric,
    avg_engagement_rate numeric(6,4),
    score               numeric,                 -- combined reach×engagement, normalized 0..1
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ig_user_id, day_of_week, hour)
);

-- (14) Publish jobs — Content Publishing API container lifecycle ------------------------
CREATE TABLE IF NOT EXISTS publish_jobs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_draft_id    uuid NOT NULL REFERENCES content_drafts(id) ON DELETE CASCADE,
    scheduled_at        timestamptz NOT NULL,
    container_id        text,                    -- IG media container id (create step)
    status              text NOT NULL DEFAULT 'queued',  -- queued|created|published|failed
    published_media_id  text,                    -- → ig_media.media_id (closes the loop)
    error               text,
    attempts            int NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- (15) Anomalies — detected spikes/drops with attribution ------------------------------
CREATE TABLE IF NOT EXISTS anomalies (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ig_user_id          text NOT NULL,
    detected_at         timestamptz NOT NULL DEFAULT now(),
    metric              text NOT NULL,          -- followers|engagement_rate|reach|post_engagement
    direction           text NOT NULL,          -- spike|drop
    severity            numeric(4,2),           -- how many std-devs from baseline
    expected            numeric,
    actual              numeric,
    attributed_media_id text,                   -- which post caused it (if any)
    notified            boolean NOT NULL DEFAULT false
);
