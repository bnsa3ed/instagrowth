-- 0007_best_time.sql — day×hour engagement heatmap, refreshed nightly by pg_cron.
-- Uses ig_media_performance on posts ≥48h old (the data-delay window). The heatmap is
-- account-local (IG_USER_ID's own timezone is the publish-date hour).

CREATE OR REPLACE VIEW v_best_time_compute AS
SELECT
    im.ig_user_id,
    EXTRACT(DOW FROM im.publish_date AT TIME ZONE current_setting('TimeZone'))::smallint AS day_of_week,
    EXTRACT(HOUR FROM im.publish_date AT TIME ZONE current_setting('TimeZone'))::smallint AS hour,
    AVG(mp.reach)            AS avg_reach,
    AVG(mp.engagement_rate)  AS avg_engagement_rate,
    COUNT(*)                 AS sample_count
  FROM ig_media_performance mp
  JOIN ig_media im ON im.media_id = mp.media_id
 WHERE im.publish_date < now() - interval '48 hours'
   AND mp.reach IS NOT NULL
   AND mp.engagement_rate IS NOT NULL
 GROUP BY im.ig_user_id, day_of_week, hour;

-- Refresh function: recompute best_time_slots from the view, normalizing score to 0..1.
CREATE OR REPLACE FUNCTION refresh_best_time_slots() RETURNS void AS $$
    WITH ranked AS (
        SELECT ig_user_id, day_of_week, hour, sample_count,
               avg_reach, avg_engagement_rate,
               (COALESCE(avg_reach,0) * COALESCE(avg_engagement_rate,0)) AS raw_score
          FROM v_best_time_compute
    ), norm AS (
        SELECT ig_user_id, day_of_week, hour, sample_count, avg_reach, avg_engagement_rate,
               CASE WHEN MAX(raw_score) OVER (PARTITION BY ig_user_id) > 0
                    THEN raw_score / MAX(raw_score) OVER (PARTITION BY ig_user_id)
                    ELSE 0 END AS score
          FROM ranked
    )
    INSERT INTO best_time_slots
        (ig_user_id, day_of_week, hour, sample_count, avg_reach, avg_engagement_rate, score, updated_at)
    SELECT ig_user_id, day_of_week, hour, sample_count, avg_reach, avg_engagement_rate, score, now()
      FROM norm
    ON CONFLICT (ig_user_id, day_of_week, hour)
    DO UPDATE SET sample_count = EXCLUDED.sample_count,
                  avg_reach = EXCLUDED.avg_reach,
                  avg_engagement_rate = EXCLUDED.avg_engagement_rate,
                  score = EXCLUDED.score,
                  updated_at = now();
$$ LANGUAGE sql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        RAISE NOTICE 'pg_cron not enabled — register the nightly refresh manually.';
        RETURN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'refresh_best_time') THEN
        PERFORM cron.schedule('refresh_best_time', '0 4 * * *', 'SELECT refresh_best_time_slots()');
    END IF;
END $$;
