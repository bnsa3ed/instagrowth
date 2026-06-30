-- 0002_rls.sql — Row-Level Security
-- The Python app/Edge-Function path uses the service_role key server-side (bypasses RLS).
-- These policies scope `authenticated` access by ig_user_id so a future user-facing
-- dashboard is multi-account-ready (single-account now, mostly an RLS change later).
--
-- NOTE: ig_media_performance and publish_jobs have NO ig_user_id column — they're scoped
-- via their parent FK (ig_media / content_drafts). pipeline_runs is service_role-only.

DO $$
DECLARE t text;
BEGIN
    -- Tables with a direct ig_user_id column → simple owner-scoped SELECT policy.
    FOR t IN
        SELECT unnest(ARRAY[
            'ig_profile_metrics','ig_media','ig_stories','ig_audience',
            'ai_reports','account_config','tracked_competitors','trend_signals',
            'topic_suggestions','content_drafts','best_time_slots','anomalies'
        ])
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format(
            'DROP POLICY IF EXISTS %I ON %I;', t || '_read_own', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR SELECT TO authenticated USING (ig_user_id = auth.uid()::text);',
            t || '_read_own', t);
    END LOOP;
END $$;

-- ig_media_performance → owner resolved through ig_media.media_id.
ALTER TABLE ig_media_performance ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ig_media_performance_read_own ON ig_media_performance;
CREATE POLICY ig_media_performance_read_own ON ig_media_performance
    FOR SELECT TO authenticated
    USING (EXISTS (
        SELECT 1 FROM ig_media im
         WHERE im.media_id = ig_media_performance.media_id
           AND im.ig_user_id = auth.uid()::text));

-- publish_jobs → owner resolved through content_drafts.content_draft_id.
ALTER TABLE publish_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS publish_jobs_read_own ON publish_jobs;
CREATE POLICY publish_jobs_read_own ON publish_jobs
    FOR SELECT TO authenticated
    USING (EXISTS (
        SELECT 1 FROM content_drafts cd
         WHERE cd.id = publish_jobs.content_draft_id
           AND cd.ig_user_id = auth.uid()::text));

-- pipeline_runs has no owner key; service_role-only (no authenticated policy).
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs FORCE ROW LEVEL SECURITY;
