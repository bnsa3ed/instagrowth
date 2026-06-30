-- Seed: account_config for the AI / vibecoding creator niche (the relevance gate).
-- Idempotent: re-seed only if no row exists. Update via the app/UI as the niche evolves.
-- Replace '<YOUR_IG_USER_ID>' with the real IG_USER_ID from .env before running, or set it
-- to a placeholder and override after the first real sync.

INSERT INTO account_config (
    ig_user_id, niche, subtopics, keywords, target_hashtags,
    brand_voice, taboos, offtopic_blocklist, monthly_cost_cap_usd, anomaly_sigma_threshold
) VALUES (
    '<YOUR_IG_USER_ID>',
    'AI / vibecoding creator',
    ARRAY['saas','web','mobile','generative-models','productivity-ai','developer-tools'],
    ARRAY[
      'ai coding','vibecoding','cursor','claude code','copilot','llm','agent',
      'برمجة بالذكاء الاصطناعي','فايب كودينج','أدوات ذكاء اصطناعي'
    ],
    ARRAY['vibecoding','aicoding','buildinpublic','cursor','claude','llm','devtools'],
    'accuracy-first, anti-hype, practical, Islamic-friendly Egyptian Arabic tone',
    ARRAY['no hype/scammy claims','no piracy','verify before publish','no exaggeration'],
    ARRAY['generic motivation','crypto shilling','celebrity gossip','political'],
    20.00,
    3.00
)
ON CONFLICT (ig_user_id) DO NOTHING;
