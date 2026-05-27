"""Free LLM abstraction — Gemini 1.5 Flash → Groq → rule-based fallback.

Priority order:
  1. Google Gemini 1.5 Flash  (free tier: 1,500 req/day, 15 RPM)
     Set GEMINI_API_KEY — get free key at https://aistudio.google.com/app/apikey
  2. Groq                     (free tier: generous rate limits)
     Set GROQ_API_KEY   — get free key at https://console.groq.com/
  3. Rule-based fallback      (always available, no key needed)

Both Gemini and Groq are entirely free to sign up for and use within
their rate-limit tiers.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

import requests

log = logging.getLogger(__name__)

_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
_GROQ_KEY = os.getenv("GROQ_API_KEY", "")

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-1.5-flash:generateContent?key={key}"
)
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama3-8b-8192"   # free, fast, good enough for agent reasoning

_HEADERS_JSON = {"Content-Type": "application/json"}


def call_llm(system_prompt: str, user_message: str, max_tokens: int = 512) -> str:
    """
    Call the best available free LLM and return the text response.

    Tries Gemini → Groq → rule-based fallback.
    """
    if _GEMINI_KEY:
        resp = _call_gemini(system_prompt, user_message, max_tokens)
        if resp:
            return resp

    if _GROQ_KEY:
        resp = _call_groq(system_prompt, user_message, max_tokens)
        if resp:
            return resp

    log.debug("No LLM key available — returning rule-based fallback JSON")
    return _rule_based_fallback(user_message)


# ── Gemini 1.5 Flash ─────────────────────────────────────────────────────────

def _call_gemini(system: str, user: str, max_tokens: int) -> str:
    """
    Gemini 1.5 Flash free tier.
    Free limits: 15 RPM, 1M TPM, 1500 RPD.
    """
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"SYSTEM INSTRUCTIONS:\n{system}\n\nUSER:\n{user}"}],
            }
        ],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.2,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        ],
    }
    try:
        resp = requests.post(
            _GEMINI_URL.format(key=_GEMINI_KEY),
            headers=_HEADERS_JSON,
            json=payload,
            timeout=45,
        )
        if resp.status_code == 429:
            log.debug("Gemini rate limit — trying Groq")
            return ""
        resp.raise_for_status()
        candidates = resp.json().get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return parts[0].get("text", "") if parts else ""
    except Exception as exc:  # noqa: BLE001
        log.debug("Gemini call failed: %s", exc)
    return ""


# ── Groq (llama3-8b) ─────────────────────────────────────────────────────────

def _call_groq(system: str, user: str, max_tokens: int) -> str:
    """
    Groq free tier — llama3-8b-8192.
    No strict daily limit; rate-limited per minute.
    """
    payload = {
        "model": _GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    try:
        resp = requests.post(
            _GROQ_URL,
            headers={**_HEADERS_JSON, "Authorization": f"Bearer {_GROQ_KEY}"},
            json=payload,
            timeout=45,
        )
        if resp.status_code == 429:
            # Groq rate limit — brief back-off
            log.debug("Groq rate limit — waiting 10 s")
            time.sleep(10)
            return ""
        resp.raise_for_status()
        choices = resp.json().get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
    except Exception as exc:  # noqa: BLE001
        log.debug("Groq call failed: %s", exc)
    return ""


# ── Rule-based fallback ───────────────────────────────────────────────────────

def _rule_based_fallback(user_message: str) -> str:
    """
    Minimal heuristic fallback when no LLM is available.
    Returns a valid JSON verdict based on keyword scoring.
    """
    text = user_message.lower()
    pos = sum(text.count(w) for w in [
        "bullish", "breakout", "squeeze", "buy", "long", "moon", "catalyst",
        "earnings beat", "upgrade", "momentum", "flagged", "high", "strong",
    ])
    neg = sum(text.count(w) for w in [
        "bearish", "breakdown", "sell", "short", "crash", "negative", "downgrade",
        "weak", "avoid", "stale", "conflict", "risk",
    ])
    if pos > neg + 2:
        verdict, conf = "BUY", 0.6
    elif neg > pos + 2:
        verdict, conf = "PASS", 0.6
    else:
        verdict, conf = "INVESTIGATE", 0.5

    return json.dumps({
        "verdict": verdict,
        "confidence": conf,
        "reasoning": f"Rule-based: +{pos} bullish signals, -{neg} bearish signals",
        "flags": ["rule_based_fallback"],
    })


def extract_json(text: str) -> dict:
    """Extract the first JSON object from an LLM response."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    # Try parsing the whole string
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    return {}


def llm_available() -> bool:
    """Return True if at least one free LLM is configured."""
    return bool(_GEMINI_KEY or _GROQ_KEY)
