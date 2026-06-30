-- 0004_extensions.sql — enable pg_cron + pg_net
-- pg_cron:   nightly weekly_summary + best_time_slots refreshes (plan §4.3, §9.2)
-- pg_net:    optional outbound HTTP (alerts/webhooks) from SQL
--
-- In Supabase: enable 'pgcron' / 'pg_net' under Database → Extensions (or run below).
-- Once enabled, pg_cron jobs run in this DB and are scheduled via cron.schedule(...).

create extension if not exists pg_cron;
create extension if not exists pg_net;
