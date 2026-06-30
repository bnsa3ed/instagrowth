-- 0008_hashtag_stats.sql — per-hashtag historical performance (rotation + decay).
-- Hashtags are parsed from ig_media.caption tags; stats flow back into the drafter so
-- weak tags decay out of rotation. Implemented as a view (always live), not a materialized table.

CREATE OR REPLACE VIEW v_hashtag_stats AS
WITH parsed AS (
    SELECT im.ig_user_id,
           lower(m.tag) AS tag,
           im.media_id,
           mp.engagement_rate,
           mp.reach
      FROM ig_media im
      CROSS JOIN LATERAL (
        SELECT match[1] AS tag
          FROM regexp_matches(im.caption, '#([A-Za-z0-9_]+)', 'g') AS match
      ) m
      JOIN ig_media_performance mp ON mp.media_id = im.media_id
     WHERE im.caption IS NOT NULL
       AND mp.engagement_rate IS NOT NULL
)
SELECT ig_user_id,
       tag AS hashtag,
       COUNT(*)                                   AS uses,
       AVG(engagement_rate)                       AS avg_engagement_rate,
       AVG(reach)                                 AS avg_reach,
       MAX(reach)                                 AS max_reach,
       now()                                      AS computed_at
  FROM parsed
 GROUP BY ig_user_id, tag;
