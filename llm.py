"""
llm.py — Single-function LLM gateway.

Reads LLM_PROVIDER, GROQ_MODEL (default openai/gpt-oss-120b),
GROQ_API_KEY / GEMINI_API_KEY from environment / .env.

call_llm(prompt, json_mode=False) -> str
  Retries up to 2 times on transient errors.
  When json_mode=True asks the provider for a JSON response.
"""

import os
import time
import json
import re
from dotenv import load_dotenv

load_dotenv()

_PROVIDER    = os.environ.get("LLM_PROVIDER", "groq").lower()
_GROQ_MODEL  = os.environ.get("GROQ_MODEL",   "openai/gpt-oss-120b")
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
_MAX_TOKENS  = 8192
_RETRIES     = 2
_RETRY_DELAY = 2  # seconds


# ── Groq ──────────────────────────────────────────────────────────────────────

def _call_groq(prompt: str, json_mode: bool) -> str:
    from groq import Groq  # type: ignore

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set in .env")

    client = Groq(api_key=api_key)
    kwargs: dict = dict(
        model=_GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=_MAX_TOKENS,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


# ── Gemini ────────────────────────────────────────────────────────────────────

def _call_gemini(prompt: str, json_mode: bool) -> str:
    import google.generativeai as genai  # type: ignore

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in .env")

    genai.configure(api_key=api_key)
    gen_config = {"max_output_tokens": _MAX_TOKENS}
    if json_mode:
        gen_config["response_mime_type"] = "application/json"  # type: ignore[assignment]

    model = genai.GenerativeModel(_GEMINI_MODEL, generation_config=gen_config)
    resp = model.generate_content(prompt)
    return resp.text or ""


# ── Public API ────────────────────────────────────────────────────────────────

def call_llm(prompt: str, json_mode: bool = False) -> str:
    """
    Call the configured LLM provider and return the raw text response.
    Retries up to _RETRIES times on any exception.
    """
    _call = _call_groq if _PROVIDER == "groq" else _call_gemini

    last_err: Exception | None = None
    for attempt in range(_RETRIES + 1):
        try:
            return _call(prompt, json_mode)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < _RETRIES:
                time.sleep(_RETRY_DELAY)

    raise RuntimeError(f"LLM call failed after {_RETRIES + 1} attempts: {last_err}") from last_err


# ── JSON helper ───────────────────────────────────────────────────────────────

def parse_json_response(text: str) -> dict | list:
    """
    Robustly parse a JSON response from the LLM.
    Handles:
      - Markdown fences (```json ... ```)
      - Bare JSON objects or arrays
      - Object-wrapped arrays e.g. {"items": [...]}
    Always returns a dict (wraps bare arrays under {"items": [...]}).
    """
    # Strip markdown fences
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    parsed = json.loads(text)  # may raise json.JSONDecodeError

    if isinstance(parsed, list):
        return {"items": parsed}
    return parsed
