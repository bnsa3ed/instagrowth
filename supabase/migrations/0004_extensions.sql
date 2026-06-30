-- 0004_extensions.sql — enable pg_cron + pg_net
-- pg_cron:   nightly weekly_summary + best_time_slots refreshes (plan §4.3, §9.2)
-- pg_net:    optional outbound HTTP (alerts/webhooks) from SQL
--
-- In Supabase: Database → Extensions → enable 'pgcron' / 'pg_net' (or run below).
-- pg_cron requires the extension in the maintenance DB; Supabase exposes `cron` schema.

create extension if not exists pg_cron;
-- Allow pg_cron jobs to reach the app's own DB objects (Supabase does this by default).
select cron.enable_db_cron() where exists (select 1 from pg_proc where proname='enable_db_cron');

create extension if not exists pg_net;
