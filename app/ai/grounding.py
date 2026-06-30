"""Gemini Grounding (Google Search) — live "what's new in [niche]" queries.

The freshness engine: asks for newest AI coding tools / model launches this week and stores
citations in `trend_signals.raw_json` so the model can be told where it saw a launch
(anti-hallucination: never invent tools not in the signals).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.ai.gemini import _client
from app.config import settings

log = logging.getLogger(__name__)


def query(keywords: list[str], *, max_queries: int = 2) -> list[dict]:
    """Run grounding searches; return normalized signal dicts (source='grounding')."""
    if not settings.gemini_api_key:
        log.warning("GEMINI_API_KEY not set — skipping grounding")
        return []

    client = _client()
    results: list[dict] = []
    from google.genai import types  # type: ignore

    for kw in keywords[:max_queries]:
        prompt = (
            f"List the newest AI coding tools, model launches, and notable developer-AI news "
            f"from this week relevant to: {kw}. Return a JSON array of objects with "
            f"'title','url','summary','date'. Only include real, verifiable items with sources."
        )
        try:
            resp = client.models.generate_content(
                model=settings.gemini_model_primary,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    response_mime_type="application/json",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("grounding query failed (%s): %s", kw, exc)
            continue

        citations = _extract_grounding(resp)
        text = getattr(resp, "text", "") or "[]"
        try:
            items = json.loads(text)
        except (ValueError, TypeError):
            items = []
        for it in items:
            if not isinstance(it, dict) or not it.get("title"):
                continue
            results.append({
                "source": "grounding",
                "title": it["title"],
                "url": it.get("url"),
                "summary": it.get("summary"),
                "signal_ts": datetime.now(timezone.utc).isoformat(),
                "momentum": "rising",
                "raw_json": {"keywords": kw, "citations": citations, "item": it},
            })
    return results


def _extract_grounding(response) -> list[str]:
    """Pull grounding citation URIs from the response metadata, if present."""
    out: list[str] = []
    try:
        meta = getattr(response, "candidates", [{}])[0]
        chunks = (getattr(meta, "grounding_metadata", None) or {}).get("grounding_chunks", [])
        for ch in chunks:
            uri = (ch.get("web") or {}).get("uri")
            if uri:
                out.append(uri)
    except Exception:  # noqa: BLE001
        pass
    return out
