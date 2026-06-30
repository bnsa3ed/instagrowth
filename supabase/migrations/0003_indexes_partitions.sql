-- 0003_indexes_partitions.sql — monthly RANGE partitions + BRIN indexes
-- Per plan §4.2: partition ig_profile_metrics, ig_media_performance, ig_stories by month,
-- and add space-efficient BRIN indexes on all naturally-ordered timestamp columns.

-- ── Monthly partitions for the current + next 24 months (2026-01 .. 2027-12) ──────────
-- Indexes defined on the parent partitioned table propagate to each child automatically.
DO $$
DECLARE
    mon date := DATE '2026-01-01';
    last date := DATE '2027-12-01';
    ym text;
    nxt date;
BEGIN
    WHILE mon <= last LOOP
        ym  := to_char(mon, 'YYYYMM');
        nxt := mon + INTERVAL '1 month';

        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS ig_profile_metrics_%s PARTITION OF ig_profile_metrics FOR VALUES FROM (%L) TO (%L);',
            ym, mon, nxt);
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS ig_media_performance_%s PARTITION OF ig_media_performance FOR VALUES FROM (%L) TO (%L);',
            ym, mon, nxt);
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS ig_stories_%s PARTITION OF ig_stories FOR VALUES FROM (%L) TO (%L);',
            ym, mon, nxt);

        mon := nxt;
    END LOOP;

    -- DEFAULT partitions catch anything outside the created range (keeps writes safe).
    CREATE TABLE IF NOT EXISTS ig_profile_metrics_default PARTITION OF ig_profile_metrics DEFAULT;
    CREATE TABLE IF NOT EXISTS ig_media_performance_default PARTITION OF ig_media_performance DEFAULT;
    CREATE TABLE IF NOT EXISTS ig_stories_default PARTITION OF ig_stories DEFAULT;
END $$;

-- ── BRIN indexes on timestamp columns (space-efficient on ordered time data) ─────────
CREATE INDEX IF NOT EXISTS brin_ig_profile_metrics_date   ON ig_profile_metrics   USING BRIN (snapshot_date);
CREATE INDEX IF NOT EXISTS brin_ig_media_performance_ts   ON ig_media_performance USING BRIN (snapshot_ts);
CREATE INDEX IF NOT EXISTS brin_ig_stories_publish_ts     ON ig_stories           USING BRIN (publish_ts);
CREATE INDEX IF NOT EXISTS brin_ig_stories_captured_ts    ON ig_stories           USING BRIN (captured_ts);
CREATE INDEX IF NOT EXISTS brin_ig_audience_snapshot_ts   ON ig_audience          USING BRIN (snapshot_ts);
CREATE INDEX IF NOT EXISTS brin_ig_media_publish_date     ON ig_media             USING BRIN (publish_date);

-- ── Supporting btree indexes for common lookups ─────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_ig_media_ig_user            ON ig_media (ig_user_id, publish_date DESC);
CREATE INDEX IF NOT EXISTS idx_ai_reports_ig_user_period   ON ai_reports (ig_user_id, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started       ON pipeline_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_trend_signals_ig_user_ts    ON trend_signals (ig_user_id, signal_ts DESC);
CREATE INDEX IF NOT EXISTS idx_topic_sugg_ig_user_status   ON topic_suggestions (ig_user_id, status, suggested_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_drafts_status       ON content_drafts (ig_user_id, status, best_time);
CREATE INDEX IF NOT EXISTS idx_anomalies_ig_user_detected  ON anomalies (ig_user_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_publish_jobs_status         ON publish_jobs (status, scheduled_at);
