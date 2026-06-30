# Tasks: Instagram AI Analyzer & Growth Engine

**Input**: Design documents from `/specs/001-instagram-ai-analyzer/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)
**Stack**: Python 3.12 application (Docker: `cron` + `bot` services) + Supabase Postgres 17 + Gemini 3.5 Flash. No n8n.
**Tests**: Not requested — verification is via manual dry-runs (each story's "Independent Test") + the plan's Testing & Validation Checklist. No per-task automated test tasks.
**Organization**: Tasks grouped by user story (US1–US5), mirroring the plan's rollout (MVP → v5). Each story is independently implementable/testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1…US5); Setup/Foundational/Polish have no label
- All artifacts are Python modules/jobs, SQL migrations, or prompt files — paths shown inline

## Path Conventions

- Python package: `app/` (jobs in `app/jobs/`, connectors in `app/connectors/`, etc.)
- Scheduled entry points: `python -m app.jobs.<name>`
- SQL migrations: `supabase/migrations/NNN_name.sql` · seeds: `supabase/seed/`
- Prompt files: `prompts/<name>-vN.md`
- Scheduling: `scheduler/crontab` (supercronic) · runtime: `docker-compose.yml`, `pyproject.toml`, `.env`
- Secrets: `pydantic-settings` env (Docker secrets) / Supabase Vault — never committed

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Accounts, credentials, and project scaffold.

- [ ] T001 Create Supabase project (Postgres 17); save project ref, DB connection string, and `service_role` key into `.env` (never committed)
- [ ] T002 [P] Create Meta Business app → add Instagram product → link IG Business account + Facebook Page; capture `IG_USER_ID`
- [ ] T003 [P] Create a Business Manager **System User**, assign to the Page, generate a **System User token** (non-expiring); store as `META_TOKEN` in `.env`
- [ ] T004 [P] Create Google AI Studio **API key** for `gemini-3.5-flash`; store as `GEMINI_API_KEY` in `.env`
- [ ] T005 [P] Create Telegram bot + chat id (and/or SMTP credentials); store `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, SMTP vars in `.env`
- [ ] T006 Create Supabase Storage bucket `content-media` (public read) for manual media uploads
- [X] T007 [P] Scaffold the Python project: `pyproject.toml` (Python 3.12; deps: `httpx`, `pydantic`, `pydantic-settings`, `supabase`, `psycopg2-binary`, `google-genai`, `python-telegram-bot`, `feedparser`, `praw`), `app/` package skeleton, `.env.example`
- [X] T008 [P] Create `docker-compose.yml` with `cron` (supercronic) + `bot` (always-on Telegram) services, and a `scheduler/crontab` placeholder

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Database schema, security, and shared Python infrastructure that ALL user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T009 Create schema migration for all 15 tables in `supabase/migrations/0001_init_schema.sql` (per plan §4)
- [X] T010 Create RLS policies migration in `supabase/migrations/0002_rls.sql` (service_role bypass; all tables keyed by `ig_user_id`)
- [X] T011 Create indexes + monthly range partitions migration in `supabase/migrations/0003_indexes_partitions.sql` (BRIN on timestamp cols; partition ig_profile_metrics, ig_media_performance, ig_stories by month)
- [X] T012 Seed `account_config` for the AI/vibecoding niche in `supabase/seed/0001_account_config.sql`
- [X] T013 Enable `pg_cron` + `pg_net` extensions in `supabase/migrations/0004_extensions.sql`
- [X] T014 [P] Implement `app/config.py` (`pydantic-settings` Settings: load all secrets/env)
- [X] T015 [P] Implement `app/db/client.py` (psycopg connection pool) and `app/db/logging.py` (write `pipeline_runs` rows: start/finish/status/api_calls_used/error/meta)
- [X] T016 [P] Implement `app/utils/retry.py` (exponential backoff + jitter; honor `Retry-After`; handle codes 4/17/32/613/80005) and `app/utils/buc.py` (parse `X-Business-Use-Case`/`X-App-Usage`; track BUC budget)
- [X] T017 Implement `app/db/models.py` (Pydantic models for DB rows + Gemini structured outputs)
- [X] T018 Establish prompt-versioning convention: create `prompts/` + `prompts/README.md` (pin-and-bump rule)

**Checkpoint**: Foundation ready — user story implementation can begin.

---

## Phase 3: User Story 1 - Daily capture + weekly report (Priority: P1) 🎯 MVP

**Goal**: Reliable daily Instagram data capture + a delivered weekly Egyptian Arabic strategy report.
**Independent Test**: `python -m app.jobs.daily_sync` → rows in `ig_profile_metrics`/`ig_stories`; `python -m app.jobs.weekly_report` → correct Egyptian Arabic report archived + delivered, engagement-rate self-check passes.

### Implementation for User Story 1

- [X] T019 [P] [US1] Implement `app/instagram/client.py` (Graph API `v25.0`; cursor paging; `views` not `impressions`) and `app/instagram/token.py` (read/refresh token, expiry tracking)
- [X] T020 [US1] Implement `app/jobs/daily_sync.py` (profile + account insights + stories → upsert `ig_profile_metrics`, `ig_stories`; log run) — after T019
- [X] T021 [US1] Implement `app/jobs/weekly_media_sync.py` (media since cursor → per-media insights → upsert `ig_media` + append `ig_media_performance`) — after T019
- [X] T022 [US1] Create `weekly_summary` materialized view + pg_cron nightly refresh in `supabase/migrations/0005_weekly_summary.sql`
- [X] T023 [US1] Write Egyptian Arabic strategy prompt `prompts/egyptian-strategy-v1.md` (Pydantic schema: headline, engagement_rate_avg, top_posts, what_works, what_to_fix, growth_opportunities, next_week_content, full_report_markdown)
- [X] T024 [US1] Implement `app/ai/gemini.py` (`google-genai` wrapper: structured output validated against Pydantic; engagement-rate self-check ±10%; fallback `gemini-3.1-flash-lite`; per-call token-cost tracking)
- [X] T025 [US1] Implement `app/jobs/weekly_report.py` (orchestrate media sync → Gemini → write `ai_reports` with prompt_version + cost)
- [X] T026 [US1] Implement `app/jobs/token_health.py` (hourly refresh or alert ≤7d expiry)
- [X] T027 [US1] Implement `app/notify/telegram.py` + `app/notify/email.py` (delivery with retry; idempotent on `run_id`; archive in `ai_reports`)
- [X] T028 [US1] Wire `pipeline_runs` logging into all US1 jobs; verify 7 clean daily snapshots with no lost stories

**Checkpoint**: US1 fully functional and independently testable — MVP shippable.

---

## Phase 4: User Story 2 - Niche trend intelligence + topic ideation (Priority: P2)

**Goal**: 3×/week niche trend scanning → opportunity-scored, on-niche topic ideas.
**Independent Test**: `python -m app.jobs.trend_scan` → fresh deduped signals + Grounding citations; `python -m app.jobs.topic_ideation` yields 3–5 on-niche topics; an off-niche viral trend is rejected.

### Implementation for User Story 2

- [X] T029 [P] [US2] Implement trend connectors `app/connectors/{hn,producthunt,github_trending,huggingface,reddit,rss}.py` (each: fetch **top 30** items since last scan → normalize → dedup on `signal_hash`)
- [X] T030 [P] [US2] Implement `app/ai/grounding.py` (Gemini Grounding query "newest AI coding tools / model launches this week in [keywords]"; store citations in `trend_signals.raw_json`)
- [X] T031 [US2] Implement `app/jobs/trend_scan.py` (run all connectors + grounding → upsert `trend_signals`) — after T029, T030
- [X] T032 [US2] Implement `app/jobs/competitor_discovery.py` (rank niche hashtags → seed `tracked_competitors`; weekly Business Discovery pull of competitor top media as signals)
- [X] T033 [US2] Write niche topic-ideation prompt `prompts/topics-vibecoding-v1.md` (hard relevance gate, anti-hype/accuracy-first, opportunity-score schema, Egyptian Arabic)
- [X] T034 [US2] Implement `app/jobs/topic_ideation.py` (account_config + trend_signals + weekly_summary + competitor saturation → Pydantic-validated JSON → `topic_suggestions`)
- [X] T035 [US2] Implement topic delivery (Telegram, 3×/wk) + `app/jobs/topic_backfill.py` (set `measured_engagement_rate` 2 weeks after publish)

**Checkpoint**: US1 + US2 both work independently.

---

## Phase 5: User Story 3 - Real-time anomaly radar (Priority: P3)

**Goal**: Instant attributed alerts on follower/engagement spikes or drops.
**Independent Test**: Injected spike → instant attributed alert + `anomalies` row; normal day → no alert.

### Implementation for User Story 3

- [X] T036 [P] [US3] Implement `app/analysis/baselines.py` (7-day & 28-day mean ± std-dev; default alert threshold **≥3σ**, configurable) + baselines SQL view in `supabase/migrations/0006_baselines.sql`
- [X] T037 [US3] Implement `app/analysis/anomalies.py` + `app/jobs/anomaly_detect.py` (runs after daily sync; compares to baseline; writes `anomalies`; sends instant attributed Telegram alert; also alerts on **missed story capture** — no new stories in 25h)

**Checkpoint**: US1–US3 independently functional.

---

## Phase 6: User Story 4 - Content engine: draft, best-time, repurpose, predict (Priority: P4)

**Goal**: Approved topic → near-ready multi-format drafts, best-time, repurpose, predicted engagement + forecast.
**Independent Test**: From an approved topic → multi-format draft set (Egyptian Arabic), each with best-time + predicted band; `best_time_slots` filled; follower forecast runs.

### Implementation for User Story 4

- [X] T038 [P] [US4] Implement `app/analysis/best_time.py` + `supabase/migrations/0007_best_time.sql` (day×hour heatmap from `ig_media_performance`, posts ≥48h old; nightly pg_cron refresh)
- [X] T039 [P] [US4] Implement `app/jobs/auto_draft.py` (caption/hook/slides|script/hashtags; A/B variant for high-opportunity topics; tag `best_time` + `predicted_engagement`)
- [X] T040 [P] [US4] Implement `app/jobs/repurpose.py` (one topic → Reel script/Carousel/Story/X-LinkedIn **text variants**, linked by `parent_repurpose_id`; no auto cross-post)
- [X] T041 [US4] Implement `app/analysis/hashtag_stats.py` + `supabase/migrations/0008_hashtag_stats.sql` (per-tag performance stats + rotation/decay); wire into `app/jobs/auto_draft.py`
- [X] T042 [US4] Implement `app/analysis/predict.py` (per-draft engagement prediction via regression/LLM-heuristic, no heavy ML; 30-day follower forecast with confidence band); wire into `app/jobs/auto_draft.py`
- [X] T043 [US4] Add manual media-upload support: paste Storage path into `content_drafts.media_url` (`media_source='manual'`); document the upload step (generation stays OFF) in `prompts/README.md`

**Checkpoint**: US1–US4 independently functional; idea→draft loop complete (no auto-publish yet).

---

## Phase 7: User Story 5 - Auto-publish with HITL gate (Priority: P5)

**Goal**: Approved drafts with `media_url` auto-publish at best time behind a mandatory Approve/Edit/Skip Telegram gate; loop closed.
**Independent Test**: Queued draft won't publish without approval; approved+media publishes at `best_time`; `published_media_id` back-links to draft + topic.

### Implementation for User Story 5

- [ ] T044 [US5] Request `instagram_content_publish` permission + prep App Review; document limits in `prompts/README.md`
- [X] T045 [US5] Implement `app/jobs/auto_publish.py` (`publish_jobs` lifecycle; create-container → publish at `best_time`; supports image, carousel, AND Reels; ONLY if `media_url` set, else ping owner)
- [X] T046 [US5] Implement `app/bot/hitl.py` (`python-telegram-bot` inline Approve/Edit/Skip buttons) gating the publish step in the always-on `bot` service
- [X] T047 [US5] Add back-link: write resulting `published_media_id` to `content_drafts` and `topic_suggestions` (closes the learning loop) in `app/jobs/auto_publish.py`

**Checkpoint**: Full idea→publish→measure loop complete end-to-end.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Guardrails, observability, and validation spanning all stories.

- [X] T048 [P] Implement `app/jobs/cost_guard.py` (aggregate monthly AI spend from `pipeline_runs.meta`; alert at 80%; throttle non-essential AI at 100%, keeping data capture + anomaly radar running)
- [X] T049 [P] Implement `app/jobs/weekly_digest.py` (followers Δ, avg engagement, posts published, cost spent, forecast accuracy)
- [ ] T050 Execute the plan's Testing & Validation Checklist end-to-end (token, API v25.0, views metric, BUC backoff, retention windows, idempotency, AI self-check, relevance gate, anomaly radar, cost cap, publish gate)
- [ ] T051 Verify the Setup Runbook (plan Appendix C) reproduces from scratch → first report in a clean environment
- [X] T052 Write project `README.md` (architecture summary, `.env` vars, `docker compose` usage, how to run dry-runs, schedules in `scheduler/crontab`)

---

## Dependencies & Execution Order

### Phase Dependencies
- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup; **BLOCKS all user stories**.
- **US1 (Phase 3)**: Depends on Foundational — no dependencies on other stories. **This is the MVP.**
- **US2 (Phase 4)**: Depends on Foundational; reads US1's stored data + rollups but is independently testable.
- **US3 (Phase 5)**: Depends on Foundational + US1's daily data.
- **US4 (Phase 6)**: Depends on Foundational + US2's `topic_suggestions` (and US1 history for best-time/predict).
- **US5 (Phase 7)**: Depends on US4's `content_drafts`.
- **Polish (Phase 8)**: Can start after US1; T050/T051 run after all targeted stories.

### Within Each User Story
- SQL/views/migrations before the Python code that reads them.
- Prompt files before the jobs that consume them.
- Shared infra (`app/ai/gemini.py`, `app/utils/*`, `app/notify/*`) before the jobs that call them.
- Logging wiring last within each story; each story is independently testable at its checkpoint.

### Parallel Opportunities
- Phase 1: T002–T005 (different external accounts) + T007/T008 (scaffolds) all parallel.
- Phase 2: T014–T016 (distinct modules) parallel.
- US1: T019–T021 (client + two jobs, distinct files) parallel.
- US2: T029–T031 (connectors + grounding + scan, distinct files) parallel.
- US4: T038–T040 (best-time, auto-draft, repurpose — distinct files) parallel.

---

## Parallel Example: User Story 2

```bash
# Launch these independent modules together:
Task: "Implement trend connectors app/connectors/{hn,producthunt,github_trending,huggingface,reddit,rss}.py"
Task: "Implement Gemini Grounding in app/ai/grounding.py"
Task: "Implement competitor discovery in app/jobs/competitor_discovery.py"
```

---

## Implementation Strategy

### MVP First (US1 only)
1. Complete Phase 1 (Setup) + Phase 2 (Foundational).
2. Complete Phase 3 (US1).
3. **STOP and VALIDATE**: 7 clean daily snapshots + one delivered report (Independent Test).
4. Demo/ship MVP.

### Incremental Delivery (mirrors plan rollout v1→v5)
1. Setup + Foundational → foundation ready.
2. + US1 → report delivered (MVP).
3. + US2 → niche topic ideas.
4. + US3 → real-time anomaly radar.
5. + US4 → content engine (drafts, best-time, repurpose, predict).
6. + US5 → auto-publish with HITL gate (full loop).
7. Polish: cost guardrails, digest, full validation.

---

## Notes
- [P] = different files, no dependencies. [Story] label maps a task to its user story for traceability.
- Verification is manual dry-run per each story's "Independent Test" (tests not requested).
- Commit after each task or logical group; respect the per-story checkpoints.
- Register each finished job in `scheduler/crontab` and restart the `cron` service.
- Avoid: vague tasks, same-file conflicts, cross-story dependencies that break independence.
