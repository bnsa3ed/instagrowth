"""Unified LLM client — GLM-5.2 via Z.ai (primary) with Gemini fallback.

- Primary: `glm-5.2` on the Z.ai OpenAI-compatible endpoint (`openai` SDK).
- Fallback: `gemini-3.5-flash` via `google-genai` if the primary errors.
- Structured output validated against a Pydantic model (JSON mode + validation).
- Per-call token cost returned to the caller → written to `pipeline_runs.meta`.

Public API (unchanged): `generate_structured()`, `AIResult`, `load_prompt()`.
Note: module is named `gemini.py` for import compatibility; it now routes to GLM first.
Grounding (Google Search) stays Gemini-only — see app/ai/grounding.py.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Type, TypeVar

from pydantic import BaseModel

from app.config import settings

log = logging.getLogger(__name__)

# Gemini pricing per 1M tokens (plan §7.1). GLM pricing comes from settings (flat plan = 0).
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


def load_prompt(name: str) -> str:
    """Load a versioned prompt file from prompts/."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _cost(model: str, in_tok: int, out_tok: int) -> float:
    if model == settings.glm_model:
        return round((in_tok / 1_000_000) * settings.glm_price_input_per_1m
                     + (out_tok / 1_000_000) * settings.glm_price_output_per_1m, 6)
    price = PRICE_PER_1M.get(model, {"input": 1.50, "output": 9.00})
    return round((in_tok / 1_000_000) * price["input"] + (out_tok / 1_000_000) * price["output"], 6)


def generate_structured(
    system_prompt: str,
    user_payload: str,
    model_cls: Type[T],
    *,
    provider: str | None = None,
    fallback_provider: str | None = None,
) -> AIResult[T]:
    """Generate structured output validated against `model_cls`; try fallback provider on failure."""
    primary = provider or settings.ai_provider_primary
    secondary = fallback_provider or settings.ai_provider_fallback
    providers = [primary] + ([secondary] if secondary and secondary != primary else [])

    last_exc: Exception | None = None
    for idx, prov in enumerate(providers):
        used_fb = idx > 0
        try:
            res = _dispatch(prov, system_prompt, user_payload, model_cls)
            res.used_fallback = used_fb
            return res
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("AI provider %s failed: %s — trying fallback", prov, exc)
    raise RuntimeError(f"AI structured generation failed on all providers: {last_exc}")


def _dispatch(prov: str, system_prompt: str, user_payload: str, model_cls: Type[T]) -> AIResult[T]:
    if prov == "glm":
        return _call_glm(system_prompt, user_payload, model_cls)
    return _call_gemini(system_prompt, user_payload, model_cls)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    return t.strip()


def _extract_json(text: str) -> str:
    """Tolerantly extract the first balanced {...} object (LLMs often add trailing braces/prose)."""
    text = _strip_fences(text)
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_str = esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text  # unbalanced — return as-is so validation gives a clear error


def _validate(model_cls: Type[T], text: str) -> T:
    return model_cls.model_validate_json(_extract_json(text))


def _call_glm(system_prompt: str, user_payload: str, model_cls: Type[T]) -> AIResult[T]:
    """GLM-5.2 via Z.ai (OpenAI-compatible)."""
    from openai import OpenAI  # type: ignore

    client = OpenAI(api_key=settings.glm_api_key, base_url=settings.glm_base_url)
    schema = json.dumps(model_cls.model_json_schema(), ensure_ascii=False)
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\nReturn ONLY valid JSON "
                                      f"(no markdown fences) matching this exact schema:\n{schema}"},
        {"role": "user", "content": user_payload},
    ]
    resp = client.chat.completions.create(
        model=settings.glm_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    text = _strip_fences(resp.choices[0].message.content or "")
    data = _validate(model_cls, text)
    usage = resp.usage
    in_tok = getattr(usage, "prompt_tokens", 0) or 0
    out_tok = getattr(usage, "completion_tokens", 0) or 0
    return AIResult(data=data, model=settings.glm_model, input_tokens=in_tok,
                    output_tokens=out_tok, cost_usd=_cost(settings.glm_model, in_tok, out_tok),
                    used_fallback=False)


def _client():
    """google-genai client (Gemini fallback + Grounding)."""
    from google import genai  # type: ignore
    return genai.Client(api_key=settings.gemini_api_key)


def _call_gemini(system_prompt: str, user_payload: str, model_cls: Type[T]) -> AIResult[T]:
    """Gemini fallback via google-genai (JSON mode + Pydantic validation).

    Uses response_mime_type=json_object with the schema in the system prompt (not response_schema,
    which the Developer API rejects when a model field is dict[str,Any] / additionalProperties)."""
    from google.genai import types  # type: ignore
    client = _client()
    schema = json.dumps(model_cls.model_json_schema(), ensure_ascii=False)
    response = client.models.generate_content(
        model=settings.gemini_model_primary,
        contents=user_payload,
        config=types.GenerateContentConfig(
            system_instruction=f"{system_prompt}\n\nReturn ONLY valid JSON "
                                f"(no markdown fences) matching this exact schema:\n{schema}",
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    usage = getattr(response, "usage_metadata", None)
    in_tok = getattr(usage, "prompt_token_count", 0) or 0
    out_tok = getattr(usage, "candidates_token_count", 0) or 0
    text = _strip_fences(getattr(response, "text", "") or "")
    if not text:
        try:
            text = response.candidates[0].content.parts[0].text
        except Exception:  # noqa: BLE001
            text = ""
    data = _validate(model_cls, text)
    return AIResult(data=data, model=settings.gemini_model_primary, input_tokens=in_tok,
                    output_tokens=out_tok, cost_usd=_cost(settings.gemini_model_primary, in_tok, out_tok),
                    used_fallback=False)
