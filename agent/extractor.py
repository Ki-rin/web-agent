"""
extractor.py — DOM extraction, page signals, keyword filter.
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

import config

_DOM_SCRIPT_TPL = """(maxEl) => {
    const items = [];
    const seenHrefs = new Set();
    let i = 0;
    document.querySelectorAll("a, button, [role=button], input[type=submit]").forEach(el => {
        if (el.offsetParent !== null) {
            const text = (el.innerText || el.value || "").trim();
            if (!text) return;
            const href = el.href || null;
            if (href) {
                const clean = href.split('?')[0].split('#')[0];
                if (seenHrefs.has(clean)) return;
                seenHrefs.add(clean);
            }
            items.push({ id: i++, text: text.slice(0, 80), href: href });
        }
    });
    return items.slice(0, maxEl);
}"""


def extract_elements(page) -> list[dict]:
    """Pulls visible links/buttons from the live DOM, falls back to BeautifulSoup."""
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(config.SCROLL_WAIT)
        elements = page.evaluate(_DOM_SCRIPT_TPL, config.MAX_ELEMENTS)
        if elements:
            return elements
    except Exception as e:
        print(f"    DOM extraction failed: {e}")

    print("    DOM empty — falling back to BeautifulSoup")
    try:
        soup = BeautifulSoup(page.content(), "html.parser")
        seen, elements = set(), []
        for a in soup.find_all("a", href=True):
            href = urljoin(page.url, a["href"])
            text = a.get_text(strip=True)
            if href not in seen and href.startswith("http") and text:
                seen.add(href)
                elements.append({"id": len(elements), "text": text[:80], "href": href})
            if len(elements) >= config.MAX_ELEMENTS:
                break
        return elements
    except Exception as e:
        print(f"    BeautifulSoup fallback failed: {e}")
        return []


def extract_signals(page) -> dict:
    """Pulls title, meta description, h1s, and body text for LLM verification."""
    def _get(fn):
        try: return fn()
        except: return None

    return {
        "title": _get(page.title) or "",
        "meta":  _get(lambda: page.locator("meta[name='description']").get_attribute("content")) or "",
        "h1s":   _get(lambda: page.locator("h1").all_inner_texts()) or [],
        "body":  (_get(lambda: page.inner_text("body")) or "")[:config.BODY_TEXT_LIMIT],
    }


def heuristic_filter(elements: list[dict], keywords: list[str]) -> list[dict]:
    """Filters elements by keyword match. Falls back to all elements if none match."""
    if not keywords:
        return elements
    matches = [
        e for e in elements
        if any(kw in (e.get("text") or "").lower() or kw in (e.get("href") or "").lower()
               for kw in keywords)
    ]
    return matches or elements
