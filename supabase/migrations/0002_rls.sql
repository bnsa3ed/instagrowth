-- 0002_rls.sql — Row-Level Security
-- The Python app/Edge-Function path uses the service_role key server-side (bypasses RLS).
-- These policies scope `authenticated` access by ig_user_id so a future user-facing
-- dashboard is multi-account-ready (single-account now, mostly an RLS change later).

-- service_role bypasses RLS by default in Supabase; no rule needed for the app.
-- We enable RLS on every table and add authenticated-read-by-owner policies.

DO $$
DECLARE t text;
BEGIN
    FOR t IN
        SELECT unnest(ARRAY[
            'ig_profile_metrics','ig_media','ig_media_performance','ig_stories','ig_audience',
            'ai_reports','pipeline_runs','account_config','tracked_competitors','trend_signals',
            'topic_suggestions','content_drafts','best_time_slots','publish_jobs','anomalies'
        ])
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
        -- authenticated users may read only their own rows (keyed by ig_user_id).
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR SELECT TO authenticated USING (ig_user_id = auth.uid()::text);',
            t || '_read_own', t);
    END LOOP;
END $$;

-- pipeline_runs has no ig_user_id column; keep it service_role-only (no authenticated policy).
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs FORCE ROW LEVEL SECURITY;
