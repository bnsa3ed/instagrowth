"""Hugging Face connector — trending models/papers via the public /api/trending endpoint."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.connectors.base import MAX, get_json, normalize

log = logging.getLogger(__name__)

URL = "https://huggingface.co/api/trending"


def fetch(ig_user_id: str, max_items: int = MAX) -> list[dict]:
    try:
        data = get_json(URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("HF trending fetch failed: %s", exc)
        return []

    out: list[dict] = []
    for section in ("models", "datasets", "spaces"):
        for item in (data.get(section) or [])[:max_items]:
            label = item.get("label") or item.get("id") or item.get("name") or ""
            if not label:
                continue
            kind = item.get("type", section[:-1] if section.endswith("s") else section)
            url = f"https://huggingface.co/{label}"
            out.append(normalize(
                source="hf", title=f"{label}", url=url,
                summary=f"trending {kind} on Hugging Face",
                signal_ts=datetime.now(timezone.utc), raw=item))
        if len(out) >= max_items:
            break
    return out[:max_items]
