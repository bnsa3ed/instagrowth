-- 0005_weekly_summary.sql — weekly rollup materialized view + nightly pg_cron refresh
-- The AI agent reads from this compact view (not raw tables) → small, cheap prompts.
-- Followers Δ, avg engagement, top 3 posts, posting cadence, best media type.

CREATE MATERIALIZED VIEW IF NOT EXISTS weekly_summary AS
SELECT
    m.ig_user_id,
    date_trunc('week', now())                                  AS week_start,
    (SELECT followers_count FROM ig_profile_metrics p
       WHERE p.ig_user_id = m.ig_user_id ORDER BY snapshot_date DESC LIMIT 1)
    -
    (SELECT followers_count FROM ig_profile_metrics p
       WHERE p.ig_user_id = m.ig_user_id ORDER BY snapshot_date DESC OFFSET 1 LIMIT 1)
                                                               AS followers_delta,
    (SELECT AVG(engagement_rate) FROM ig_media_performance mp
       JOIN ig_media im ON im.media_id = mp.media_id
      WHERE im.ig_user_id = m.ig_user_id
        AND mp.snapshot_ts > now() - interval '7 days')         AS avg_engagement_rate,
    COUNT(DISTINCT m.media_id)                                  AS posts_this_week,
    (SELECT array_agg(row_to_json(t))
       FROM (
         SELECT im2.media_id, im2.media_type, mp2.engagement_rate
           FROM ig_media_performance mp2
           JOIN ig_media im2 ON im2.media_id = mp2.media_id
          WHERE im2.ig_user_id = m.ig_user_id
            AND mp2.snapshot_ts > now() - interval '7 days'
          ORDER BY COALESCE(mp2.engagement_rate, 0) DESC LIMIT 3
       ) t)                                                     AS top_posts,
    (SELECT mode() WITHIN GROUP (ORDER BY im3.media_type)
       FROM ig_media im3
      WHERE im3.ig_user_id = m.ig_user_id
        AND im3.publish_date > now() - interval '7 days')       AS best_media_type
FROM ig_media m
WHERE m.publish_date > now() - interval '7 days'
GROUP BY m.ig_user_id;

CREATE UNIQUE INDEX IF NOT EXISTS weekly_summary_uidx
    ON weekly_summary (ig_user_id, week_start);

-- Nightly refresh via pg_cron (CONCURRENTLY needs the unique index above).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        RAISE NOTICE 'pg_cron not enabled — register the nightly refresh manually.';
        RETURN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'refresh_weekly_summary') THEN
        PERFORM cron.schedule(
            'refresh_weekly_summary',
            '0 1 * * *',  -- 01:00 nightly
            'REFRESH MATERIALIZED VIEW CONCURRENTLY weekly_summary'
        );
    END IF;
END $$;
