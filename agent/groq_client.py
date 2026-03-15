"""
Groq client with per-role model fallback chains and response caching.

Each role (nav / link / verify) has its own model list and fails over
independently — a VERIFY rate limit doesn't affect NAV or LINK.
"""

import os
import re
import threading
import time

from groq import Groq

import config

# ── Client ────────────────────────────────────────────────────────────────────

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── Cache: (model, prompt) → response text ────────────────────────────────────
_cache: dict[tuple, str] = {}

# ── Per-role state ────────────────────────────────────────────────────────────
_role_idx: dict[str, int] = {"nav": 0, "link": 0, "verify": 0}
_role_chains: dict[str, list[str]] = {
    "nav":    config.NAV_MODELS,
    "link":   config.LINK_MODELS,
    "verify": config.VERIFY_MODELS,
}
_role_lock = threading.Lock()


# ── Public helpers ────────────────────────────────────────────────────────────

def active_model(role: str) -> str:
    """Returns the currently active model for a role."""
    with _role_lock:
        chain = _role_chains[role]
        idx   = _role_idx[role]
        return chain[min(idx, len(chain) - 1)]


def call(prompt: str, role: str) -> str:
    """
    Sends a prompt to Groq using the active model for `role`.

    Handles automatically:
    - Cache hits         → instant return, no API call
    - Rate limits        → wait if short (≤2 min), else switch model
    - Decommissioned     → switch model immediately
    - Tool use errors    → switch model (gpt-oss fires browser tools in NAV)
    - <think> blocks     → stripped before returning
    """
    for _ in range(len(_role_chains[role])):
        model     = active_model(role)
        cache_key = (model, prompt)

        if cache_key in _cache:
            return _cache[cache_key]

        try:
            resp = _client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            text = _strip_thinking(resp.choices[0].message.content.strip())
            _cache[cache_key] = text
            return text

        except Exception as e:
            err = str(e)

            if "rate_limit_exceeded" in err or "429" in err:
                wait = _parse_wait_seconds(err)
                if wait <= 120:
                    _log(f"[{role}] Rate limit on {model} — waiting {wait}s...")
                    time.sleep(wait)
                    continue
                _advance(role, f"[{role}] Rate limit on {model} ({wait}s wait)")

            elif "decommissioned" in err or "model_not_found" in err:
                _advance(role, f"[{role}] {model} decommissioned")

            elif "tool_use_failed" in err or "Tool choice is none" in err:
                _advance(role, f"[{role}] {model} fired unwanted tool")

            else:
                _log(f"[{role}] Groq error ({model}): {e}")
                return ""

    return ""


# ── Internal ──────────────────────────────────────────────────────────────────

def _advance(role: str, reason: str) -> bool:
    with _role_lock:
        chain = _role_chains[role]
        idx   = _role_idx[role]
        if idx + 1 < len(chain):
            _role_idx[role] = idx + 1
            _log(f"{reason} → switching to {chain[idx + 1]}")
            return True
    _log(f"{reason} → all fallbacks exhausted for [{role}].")
    return False


def _strip_thinking(text: str) -> str:
    """Removes <think>...</think> blocks prepended by qwen/kimi models."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _parse_wait_seconds(error_msg: str) -> int:
    """Parses '17m4s' style wait times from Groq 429 errors."""
    try:
        if "Please try again in" in error_msg:
            part  = error_msg.split("Please try again in")[1].split(".")[0].strip()
            total = 0
            if "m" in part:
                mins, part = part.split("m")
                total += int(mins.strip()) * 60
            if "s" in part:
                total += int(part.replace("s", "").strip())
            return total + 5
    except Exception:
        pass
    return 60


def _log(msg: str):
    print(f"    {msg}")
