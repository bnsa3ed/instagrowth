-- 0009_topic_unique.sql — dedupe topic suggestions per account by title.
-- Allows idempotent ON CONFLICT (ig_user_id, title) DO NOTHING in topic_ideation.
CREATE UNIQUE INDEX IF NOT EXISTS topic_suggestions_ig_user_title_uq
    ON topic_suggestions (ig_user_id, title);
