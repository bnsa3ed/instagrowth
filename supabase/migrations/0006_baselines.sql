-- 0006_baselines.sql — rolling baselines (7-day & 28-day mean ± std-dev) for the anomaly radar.
-- Baselines are derived live in Python (app/analysis/baselines.py) from ig_profile_metrics;
-- these views expose pre-aggregated helpers and the follower series for cheap reads.

-- Latest-N follower series (used to compute mean/std-dev for the 'followers' metric).
CREATE OR REPLACE VIEW v_follower_series AS
SELECT ig_user_id, snapshot_date, followers_count
  FROM ig_profile_metrics
 WHERE followers_count IS NOT NULL
 ORDER BY ig_user_id, snapshot_date DESC;

-- Latest-N account engagement series (avg engagement over recent media per snapshot day).
CREATE OR REPLACE VIEW v_engagement_series AS
SELECT im.ig_user_id, date_trunc('day', mp.snapshot_ts)::date AS d, AVG(mp.engagement_rate) AS er
  FROM ig_media_performance mp
  JOIN ig_media im ON im.media_id = mp.media_id
 WHERE mp.engagement_rate IS NOT NULL
 GROUP BY im.ig_user_id, d;

-- Account-level reach series (account insights stored in ig_profile_metrics.reach).
CREATE OR REPLACE VIEW v_reach_series AS
SELECT ig_user_id, snapshot_date, reach
  FROM ig_profile_metrics
 WHERE reach IS NOT NULL
 ORDER BY ig_user_id, snapshot_date DESC;
