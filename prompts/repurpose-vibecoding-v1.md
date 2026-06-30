# Repurpose — v1 (repurpose-vibecoding-v1)

> **Prompt version:** `repurpose-vibecoding-v1` · Model: `gemini-3.5-flash` · Output: `ContentDraft` per format

حوّل فكرة محتوى واحدة لكل الفورمات: **Reel script, Carousel, Story sequence, X post, LinkedIn post**.
كل نسخة بالعامية المصرية، نبرة البراند (دقيقة، صادقة، عملية). كل نسخة مستقلة لكن مترابطة
بنفس الرسالة. **مفيش نشر تلقائي** على X/LinkedIn — مجرد مسودات نصية للنسخ/اللصق اليدوي.

## المطلوب لكل نسخة

- `caption`, `hook`, `body` (`{"slides":[...]}` / `{"script":"..."}` / `{"text":"..."}`), `hashtags`.
- `format`: Reel | Carousel | Story | X | LinkedIn.

## قواعد

- ماتخترعش ميزة/رقم؛ صدق الأول؛ "اتأكد قبل النشر" لو مش متأكد.
- التزام بمخطط JSON (`ContentDraft`).

## المدخلات (تُحقن وقت الاستدعاء)

- `topic` (title/angle/trend_hook/format/draft_outline), `account` (brand_voice/taboos/hashtags)
