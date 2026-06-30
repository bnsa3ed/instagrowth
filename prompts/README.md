# Prompts

Versioned prompt sources for the Gemini calls. Every AI output in the DB stores the
`prompt_version` that produced it, so reports/topics are reproducible and diffs are meaningful.

## Pin-and-bump rule

- **Pin in code.** Each job reads a specific versioned file (e.g. `egyptian-strategy-v1.md`).
  The version suffix (`-v1`) is the contract; never edit a live prompt silently.
- **Bump, don't edit.** To change behaviour, copy the file to `-v2`, update the job's
  `prompt_version` constant + the `prompts/` reference, and ship both. Old reports keep their
  original `prompt_version` for accurate diffs.
- **Few-shot.** Keep 1–2 canonical good outputs as examples to lock tone/format. Past winning
  topics (closed-loop, Phase 8.6) become few-shot examples in the topic prompt.

## Current prompts

| File | Used by | Structured schema (`app/db/models.py`) |
|---|---|---|
| `egyptian-strategy-v1.md` | `app/jobs/weekly_report.py` | `WeeklyReport` |
| `topics-vibecoding-v1.md` | `app/jobs/topic_ideation.py` | `TopicIdeation` |

All outputs are **Egyptian Arabic (العامية المصرية)**, Islamic-friendly tone, accuracy-first.

## Tone guardrails (baked into every prompt)

- صدق وتجنّب المبالغة — no hype/scammy claims.
- ماتخترعش أداة/ميزة غير موجودة — never invent tools/features; "اتأكد قبل النشر" when unsure.
- استخدام `views`/`total_views` مش `impressions` — current Meta metric.

## Media assets (Phase 7.7 / 9.7)

Content **text** is generated here; **media** (image/video) is a deliberately decoupled step:

- **Manual upload (default):** export the asset → upload to the Supabase Storage bucket
  `content-media` (public-read) → paste the public URL into `content_drafts.media_url`
  (`media_source='manual'`). Nothing here generates or fetches media automatically.
- **AI generation (OFF by default):** an optional, explicitly-enabled-only job may later fill
  `media_url` with `media_source='generated'`. It stays un-wired until the rest is proven.

## Content Publishing limits (Phase 7.6 / US5)

- Requires the `instagram_content_publish` permission + App Review (a separately-reviewed scope).
- Per-account daily container limits apply; image, carousel, AND Reels are all supported via
  create-container → publish, but only when `content_drafts.media_url` is set.
