"""
Page extraction helpers.

- extract_elements : pulls visible links/buttons from live DOM
- extract_signals  : structured page data for LLM verification
- heuristic_filter : keyword pre-filter to cut ~70% of LLM calls
- keywords_from_goal: parses meaningful words from a goal string
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import config

# ── DOM script ────────────────────────────────────────────────────────────────
# Grabs visible a, button, [role=button], input[type=submit] elements.
# MAX_ELEMENTS cap keeps prompts short and cheap.

_DOM_SCRIPT = """() => {
    const items = [];
    let i = 0;
    document.querySelectorAll("a, button, [role=button], input[type=submit]").forEach(el => {
        if (el.offsetParent !== null) {
            const text = (el.innerText || el.value || "").trim();
            if (text) items.push({
                id:   i++,
                text: text.slice(0, 80),
                href: el.href || null
            });
        }
    });
    return items.slice(0, %d);
}""" % config.MAX_ELEMENTS


def extract_elements(page) -> list[dict]:
    """
    Extracts visible interactive elements from the live DOM.
    Falls back to BeautifulSoup if DOM script returns nothing
    (e.g. heavy JS sites that haven't finished rendering).
    """
    elements = []
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(config.SCROLL_WAIT)
        elements = page.evaluate(_DOM_SCRIPT)
    except Exception as e:
        print(f"    DOM extraction failed: {e}")

    if not elements:
        print("    DOM empty — falling back to BeautifulSoup")
        try:
            soup = BeautifulSoup(page.content(), "html.parser")
            seen = set()
            for a in soup.find_all("a", href=True):
                href = urljoin(page.url, a["href"])
                text = a.get_text(strip=True)
                if href not in seen and href.startswith("http") and text:
                    seen.add(href)
                    elements.append({"id": len(elements), "text": text[:80], "href": href})
                if len(elements) >= config.MAX_ELEMENTS:
                    break
        except Exception as e:
            print(f"    BeautifulSoup fallback failed: {e}")

    return elements


def extract_signals(page) -> dict:
    """
    Pulls structured page signals for verification:
      - title          : <title> tag
      - meta           : meta[name=description] content
      - h1s            : all h1 text
      - body           : first BODY_TEXT_LIMIT chars of visible body text

    Sending structured signals gives the LLM much better context than
    raw body text alone.
    """
    signals = {"title": "", "meta": "", "h1s": [], "body": ""}
    try:
        signals["title"] = page.title() or ""
    except Exception:
        pass
    try:
        signals["meta"] = (
            page.locator("meta[name='description']").get_attribute("content") or ""
        )
    except Exception:
        pass
    try:
        signals["h1s"] = page.locator("h1").all_inner_texts()
    except Exception:
        pass
    try:
        signals["body"] = (page.inner_text("body") or "")[: config.BODY_TEXT_LIMIT]
    except Exception:
        pass
    return signals


def keywords_from_goal(goal: str) -> list[str]:
    """Extracts meaningful keywords by stripping stop words and short tokens."""
    words = re.findall(r"[a-z]+", goal.lower())
    return [w for w in words if w not in config.STOP_WORDS and len(w) > 2]


def heuristic_filter(elements: list[dict], keywords: list[str]) -> list[dict]:
    """
    Fast keyword pre-filter — no LLM needed.
    Returns elements whose text or href contains a goal keyword.
    Falls back to all elements if nothing matches so the LLM
    still gets a chance on keyword-sparse pages.
    """
    if not keywords:
        return elements
    matches = [
        e for e in elements
        if any(
            kw in (e.get("text") or "").lower() or kw in (e.get("href") or "").lower()
            for kw in keywords
        )
    ]
    return matches if matches else elements
