# Feature Specification: Instagram AI Analyzer & Growth Engine

**Feature Branch**: `001-instagram-ai-analyzer`
**Created**: 2026-06-30
**Status**: Draft
**Input**: User description: "Automated Instagram AI analysis system — extract metrics, store history, generate an Egyptian Arabic growth-strategy report via AI, keep up with niche-specific (AI/vibecoding) trends to suggest on-topic content, and operationalize the full idea→publish loop. Personal use first; public later."

> Derived from `plan.md` (Enhanced Implementation Plan). Tech stack, schema, and phased rollout live there; this spec captures the user stories, requirements, and success criteria that drive task generation.

## Clarifications

### Session 2026-06-30
- Q: Visual tool (n8n) vs custom code? → A: **Custom Python app, self-hosted via Docker** (two services: `cron` + `bot`). Code-first is a better fit for this logic-heavy data/AI pipeline (testable, diffable); the HITL gate is a small Telegram bot. n8n dropped.
- Q: Does repurposing auto-publish to X/LinkedIn? → A: **No — text-only drafts.** Generate + store all variants (Reel/Carousel/Story/X/LinkedIn) in `content_drafts` for manual copy-paste; X/LinkedIn auto-post is deferred (extra auth/scope/ToS risk).
- Q: Which publish formats first? → A: **All formats at once** — image, carousel, AND Reels in US5 (accept the extra Content Publishing API/async complexity up front for full reach).
- Q: How deep should predictive forecasting go? → A: **Lightweight heuristic now** — regression/LLM-heuristic per-draft engagement prediction + 30-day follower forecast with confidence band and accuracy tracking; no ML infrastructure.
- Q: Which trend sources first cut? → A: **All free-tier sources** — HN, Product Hunt, GitHub Trending, Hugging Face, Reddit, AI-newsletter RSS + Gemini Grounding in US2 from the start (all free; broad coverage maximizes freshness).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Daily metrics capture + weekly Egyptian Arabic strategy report (Priority: P1) 🎯 MVP

As the account owner, I want the system to automatically pull my Instagram metrics every day and
generate a weekly growth-strategy report in Egyptian Arabic (Islamic-friendly tone) via
Gemini 3.5 Flash, so I get actionable insight without manual work.

**Why this priority**: This is the core standalone value — data in, insight out. It must work
end-to-end before anything else. The system is useless without reliable capture + a delivered report.

**Independent Test**: Trigger the daily job manually → rows appear in `ig_profile_metrics` and
`ig_stories`; trigger the weekly job manually → a correct Egyptian Arabic report lands in `ai_reports`
and via email/Telegram, and the `engagement_rate` self-check passes.

**Acceptance Scenarios**:
1. **Given** a valid System User token, **When** the daily job runs, **Then** profile/followers, account insights, and stories (within 24h) are upserted into Supabase.
2. **Given** ≥1 week of captured data, **When** the weekly job runs, **Then** a structured Egyptian Arabic report (JSON + markdown) is generated, its echoed engagement-rate is within 10% of the DB value, and it is delivered and archived.
3. **Given** a near-expiry token, **When** the hourly token-health job runs, **Then** the token is refreshed or an alert fires before the weekly run breaks.

---

### User Story 2 - Niche trend intelligence + topic ideation (Priority: P2)

As the account owner, I want the system to scan niche-relevant trend sources (Hacker News, Product
Hunt, GitHub Trending, Hugging Face, Reddit, AI newsletters + Gemini Grounding) 3×/week and turn
fresh, on-niche AI/vibecoding signals into opportunity-scored content topic ideas — never generic
viral noise.

**Why this priority**: Differentiator for a fast-moving niche where freshness is the competitive
edge. Builds on US1's stored data and brand profile.

**Independent Test**: Run the trend scan manually → fresh signals land in `trend_signals` (deduped);
the ideation step produces 3–5 niche-relevant topics with `why_now` + `opportunity_score`; an
off-niche viral trend fed to the model is rejected.

**Acceptance Scenarios**:
1. **Given** the niche profile in `account_config`, **When** the trend scan runs, **Then** ≥3 sources are pulled and deduped on `signal_hash`, with Grounding citations stored.
2. **Given** recent trend signals + my top-performing themes, **When** ideation runs, **Then** topic ideas are produced that map to formats that work for me, each with an opportunity score.
3. **Given** an off-niche viral trend, **When** ideation runs, **Then** it is **rejected** and the model invents no tools/features not in the signals.

---

### User Story 3 - Real-time anomaly radar (Priority: P3)

As the account owner, I want instant alerts (with attribution) when my followers or engagement
spike or drop, so I can react immediately instead of waiting for the weekly digest.

**Why this priority**: Cheap, high-signal, and turns the system into a real-time radar on top of
US1's daily data.

**Independent Test**: Inject a synthetic follower/engagement spike → an instant attributed alert
arrives on Telegram and an `anomalies` row is written; a normal day produces no false alert.

**Acceptance Scenarios**:
1. **Given** ≥28 days of metrics, **When** the post-sync anomaly job runs after a spike beyond the threshold (default **≥3σ** over the 28-day baseline, configurable in `account_config`), **Then** an alert fires with the causing post/time attributed.
2. **Given** normal day-to-day variance, **When** the anomaly job runs, **Then** no alert is sent.

---

### User Story 4 - Content engine: auto-draft, best-time, repurpose, predict (Priority: P4)

As the account owner, I want each approved topic turned into near-ready, multi-format content
(caption, hook, carousel slides/Reel script, hashtags), scheduled at my statistically best time,
repurposed across formats, and scored with a predicted-engagement band.

**Why this priority**: Operationalizes US2's ideas into publish-ready drafts. Larger build; ships
after capture/reporting/trends are proven.

**Independent Test**: From an approved topic, run the content engine → a multi-format draft set is
generated in Egyptian Arabic, each tagged with a best-time and predicted-engagement band; the
follower forecast runs; `best_time_slots` is filled from real history.

**Acceptance Scenarios**:
1. **Given** an approved `topic_suggestion`, **When** auto-draft runs, **Then** valid draft(s) are written to `content_drafts` (caption/hook/body/hashtags), on-brand and in Egyptian Arabic.
2. **Given** historical media performance, **When** the nightly job runs, **Then** `best_time_slots` is refreshed and each draft is tagged with a slot.
3. **Given** a draft, **When** repurposing runs, **Then** Reel/Carousel/Story/X-LinkedIn **text variants** are produced and stored (linked by `parent_repurpose_id`); no auto cross-posting.
4. **Given** a draft, **Then** a predicted engagement + confidence band is attached, and a 30-day follower forecast is produced.

---

### User Story 5 - Auto-publish with human-in-the-loop gate (Priority: P5)

As the account owner, I want approved drafts (with manually-uploaded media) to publish automatically
at their best time via the Content Publishing API, behind a mandatory Approve/Edit/Skip gate, and the
resulting post linked back to its draft/topic to close the learning loop.

**Why this priority**: Completes the loop but carries the most risk (publishing to a live account,
separate permission). Ships last, after everything else is validated.

**Independent Test**: A queued draft with `media_url` set cannot publish without the Approve gate;
once approved, it creates a container and publishes at `best_time`, and `published_media_id`
back-links to `content_drafts` and `topic_suggestions`.

**Acceptance Scenarios**:
1. **Given** a draft in `status='queued'`, **When** no approval is given, **Then** it does **not** publish.
2. **Given** an approved draft with `media_url` set (image, carousel, or Reel), **When** the scheduled publish time arrives, **Then** a container is created and the post publishes; the `media_id` is written back to the draft and topic.
3. **Given** a draft without `media_url`, **Then** it stays queued and pings the owner (manual media upload is the default; AI generation stays off).

---

### Edge Cases
- Instagram API returns `429`/BUC throttle mid-sync → exponential backoff with jitter, honor `Retry-After`, mark `partial`, alert on terminal failure.
- Stories not captured within 24h → data permanently lost; daily job must be resilient + alert on missed capture.
- `impressions` metric absent (deprecated) → all code uses `views`/`total_views`.
- Gemini returns off-schema JSON or wrong dialect → schema validation fails the run; fallback model `gemini-3.1-flash-lite` retry; tone spot-checks.
- Monthly AI spend exceeds cap → throttle non-essential AI; keep data capture + anomaly radar running.
- Content Publishing API not yet approved/unavailable → auto-publish degrades to "queue + manual publish"; everything upstream still works.

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001**: System MUST capture Instagram profile, account insights, media, stories, and (later) demographics daily via Graph API `v25.0` using `views` (not `impressions`).
- **FR-002**: System MUST store data in Supabase (Postgres 17) with idempotent upserts and a `pipeline_runs` audit log per job.
- **FR-003**: System MUST generate a weekly Egyptian Arabic strategy report via Gemini 3.5 Flash using structured (JSON-schema) output, with a versioned prompt.
- **FR-004**: System MUST manage token lifecycle (System User token preferred; auto-refresh + expiry alert otherwise).
- **FR-005**: System MUST scan all free-tier niche trend sources 3×/week (Hacker News, Product Hunt, GitHub Trending, Hugging Face, Reddit, AI-newsletter RSS) + Gemini Grounding, dedup signals, and produce niche-filtered, opportunity-scored topic ideas (reject off-niche).
- **FR-006**: System MUST detect metric anomalies (followers/engagement) post-sync and alert instantly with attribution.
- **FR-007**: System MUST auto-draft multi-format content (caption/hook/slides/script/hashtags) in Egyptian Arabic from approved topics, with best-time + predicted engagement.
- **FR-008**: System MUST repurpose one topic into Reel/Carousel/Story/X-LinkedIn **text drafts** stored in `content_drafts` (manual copy-paste; no auto cross-posting in v1).
- **FR-009**: System MUST publish approved drafts via the Content Publishing API (image, carousel, AND Reels) behind a mandatory HITL gate, only when `media_url` is set; default media source is manual upload (generation off).
- **FR-010**: System MUST enforce a hard monthly AI-cost cap (`account_config.monthly_cost_cap_usd`): alert at 80%, throttle non-essential AI at 100%.
- **FR-011**: System MUST deliver outputs (reports, topics, alerts) via email + Telegram with retry and idempotent dedupe.
- **FR-012**: All schema tables MUST be keyed by `ig_user_id` and protected by RLS (single-account now, multi-account-ready later).

### Key Entities
- **ig_profile_metrics, ig_media, ig_media_performance, ig_stories, ig_audience**: captured Instagram data (time-series).
- **ai_reports**: generated weekly strategy reports (versioned prompts, cost tracked).
- **account_config**: niche profile, brand voice, taboos, hashtags, cost cap — the relevance gate.
- **tracked_competitors**: auto-discovered competitor accounts.
- **trend_signals**: raw, deduped niche trend signals.
- **topic_suggestions**: AI-generated, opportunity-scored ideas with closed-loop status.
- **content_drafts**: multi-format drafts (text only; `media_url` external).
- **best_time_slots, publish_jobs, anomalies, pipeline_runs**: derived/scheduling/observability entities.

## Success Criteria *(mandatory)*

### Measurable Outcomes
- **SC-001**: 7 consecutive days of clean daily snapshots in Supabase with zero lost stories (US1 done).
- **SC-002**: A correct Egyptian Arabic weekly report is generated and delivered with the engagement-rate self-check passing (US1 done).
- **SC-003**: At least one week of ≥3 niche-relevant, non-generic topic ideas delivered, each passing the relevance gate (US2 done).
- **SC-004**: An injected spike triggers a correct attributed anomaly alert within the same daily cycle (US3 done).
- **SC-005**: From one approved topic, a full multi-format draft set is produced, each with a best-time and predicted-engagement band (US4 done).
- **SC-006**: One post published automatically via the Approve gate at its predicted best time, with the loop closed end-to-end (US5 done).
- **SC-007**: Monthly AI spend never exceeds the configured cap.

## Assumptions
- Instagram account is a **Business/Creator** account linked to a Facebook Page; a **System User token** is obtainable (FB Login path).
- Single owner/account for v1; multi-account/public is a later (mostly RLS) change.
- Media is created/uploaded **manually** for now; AI asset generation is out of scope (flagged off).
- Trend sources are accessed via their free public APIs/RSS (HN, PH, GitHub, HF, Reddit, newsletters); X/YouTube are optional/later.
- Data-retention/ToS compliance is deferred (personal use first, per owner).
- The automation engine is a **custom Python 3.12 application self-hosted via Docker** (two services: `cron` for scheduled jobs + `bot` for the always-on Telegram HITL/approvals); Supabase Postgres 17 is the only datastore. No n8n.
