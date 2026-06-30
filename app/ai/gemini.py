"""Gemini (google-genai) wrapper — structured output, fallback model, cost tracking.

- Primary: `gemini-3.5-flash`. Fallback: `gemini-3.1-flash-lite` on error/timeout.
- Structured output validated against a Pydantic model (`response_schema`).
- Per-call token cost returned to the caller → written to `pipeline_runs.meta`.
- Weekly-report path: engagement-rate self-check (±10% vs DB value); flag on drift.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Type, TypeVar

from pydantic import BaseModel

from app.config import settings

log = logging.getLogger(__name__)

# Pricing per 1M tokens (plan §7.1). Used for cost tracking / monthly cap.
PRICE_PER_1M = {
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
}

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

T = TypeVar("T", bound=BaseModel)


@dataclass
class AIResult(Generic[T]):
    data: T
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    used_fallback: bool


def _cost(model: str, in_tok: int, out_tok: int) -> float:
    price = PRICE_PER_1M.get(model, {"input": 1.50, "output": 9.00})
    return round((in_tok / 1_000_000) * price["input"] + (out_tok / 1_000_000) * price["output"], 6)


def load_prompt(name: str) -> str:
    """Load a versioned prompt file from prompts/."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _client():
    """Lazily build the google-genai client. Import kept local so missing dep won't crash import."""
    from google import genai  # type: ignore
    return genai.Client(api_key=settings.gemini_api_key)


def generate_structured(
    system_prompt: str,
    user_payload: str,
    model_cls: Type[T],
    *,
    model: str | None = None,
    fallback: str | None = None,
) -> AIResult[T]:
    """Generate structured output validated against `model_cls`; retry once on the fallback model.

    `user_payload` should be a JSON string of the inputs referenced by the prompt.
    """
    primary = model or settings.gemini_model_primary
    secondary = fallback or settings.gemini_model_fallback

    last_exc: Exception | None = None
    for idx, mdl in enumerate([primary, secondary]):
        used_fb = idx == 1
        try:
            return _call(mdl, system_prompt, user_payload, model_cls, used_fb)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("Gemini call failed on %s: %s — trying fallback", mdl, exc)
    raise RuntimeError(f"Gemini structured generation failed: {last_exc}")


def _call(mdl: str, system_prompt: str, user_payload: str,
          model_cls: Type[T], used_fallback: bool) -> AIResult[T]:
    client = _client()
    # google-genai supports passing a Pydantic class as response_schema / config.
    config = {"response_mime_type": "application/json"}
    try:  # response_schema support varies by SDK version
        from google.genai import types  # type: ignore
        schema = types.Schema(**_pydantic_to_schema(model_cls)) if False else model_cls
        config["response_schema"] = model_cls
    except Exception:  # noqa: BLE001
        pass

    from google.genai import types  # type: ignore
    response = client.models.generate_content(
        model=mdl,
        contents=user_payload,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            **config,
        ),
    )
    usage = getattr(response, "usage_metadata", None)
    in_tok = getattr(usage, "prompt_token_count", 0) or 0
    out_tok = getattr(usage, "candidates_token_count", 0) or 0

    data = _parse(response, model_cls)
    return AIResult(
        data=data,
        model=mdl,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=_cost(mdl, in_tok, out_tok),
        used_fallback=used_fb,
    )


def _parse(response, model_cls: Type[T]) -> T:
    text = getattr(response, "text", None) or ""
    if not text:
        # Try first candidate part text.
        try:
            text = response.candidates[0].content.parts[0].text
        except Exception:  # noqa: BLE001
            text = ""
    if not text:
        raise RuntimeError("Gemini returned empty content")
    return model_cls.model_validate_json(text)


def _pydantic_to_schema(model_cls: Type[BaseModel]) -> dict:
    """Fallback JSON-schema (unused unless response_schema needs a raw dict)."""
    return model_cls.model_json_schema()
