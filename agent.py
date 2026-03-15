"""
Web Agent — Groq + Playwright
Navigates websites and returns verified pages matching a goal.
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from groq import Groq
from playwright.sync_api import sync_playwright

load_dotenv()


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

MAX_STEPS      = 10   # max navigation clicks per session
MAX_ELEMENTS   = 30   # max DOM elements sent to LLM
MAX_BRANCH     = 3    # verified pages to recurse into
MAX_DEPTH      = 2    # crawl depth
TARGET_RESULTS = 5    # stop early once this many pages are verified
VERIFY_WORKERS = 3    # parallel threads for Groq verification calls

# ── Per-role model chains ─────────────────────────────────────────────────────
#
# Each role has its OWN fallback list, tried independently.
# If VERIFY exhausts its chain it doesn't affect NAV or LINK.
#
#   NAV    — simple click decisions  → fast models, NO built-in browser tools
#   LINK   — candidate link picking  → balanced reasoning
#   VERIFY — reads full page content → strongest models first
#
# NOTE: openai/gpt-oss-20b and openai/gpt-oss-120b have built-in browser
# tools that fire automatically. Keep them out of NAV (causes tool_use_failed
# errors) and only use them for LINK / VERIFY where tool use is harmless.

NAV_MODELS = [
    "llama-3.1-8b-instant",                       # 560 t/s — primary (no tools)
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 750 t/s
    "llama-3.3-70b-versatile",                    # 280 t/s
    "qwen/qwen3-32b",                             # 400 t/s — last nav resort
]

LINK_MODELS = [
    "qwen/qwen3-32b",                             # 400 t/s — primary
    "llama-3.3-70b-versatile",                    # 280 t/s
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 750 t/s
    "openai/gpt-oss-20b",                         # 1000 t/s
    "llama-3.1-8b-instant",                       # last link resort
]

VERIFY_MODELS = [
    "openai/gpt-oss-120b",                        # 500 t/s — primary (best reasoning)
    "llama-3.3-70b-versatile",                    # 280 t/s
    "moonshotai/kimi-k2-instruct-0905",           # 200 t/s, 262k ctx
    "qwen/qwen3-32b",                             # 400 t/s
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 750 t/s
    "openai/gpt-oss-20b",                         # 1000 t/s
    "llama-3.1-8b-instant",                       # last verify resort
]

# Common stop words stripped when extracting keywords from the goal
_STOP_WORDS = {
    "find", "page", "pages", "that", "with", "about", "for", "the", "a",
    "an", "and", "or", "to", "of", "in", "on", "any", "all", "which",
    "mention", "mentions", "mentioning", "include", "includes", "containing",
}


# ══════════════════════════════════════════════════════════════════════════════
# RESULT TYPE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FoundPage:
    url:     str
    title:   str    # page <title>
    snippet: str    # 1-sentence proof from page content
    model:   str    # which model verified this


# ══════════════════════════════════════════════════════════════════════════════
# GROQ CLIENT  —  per-role fallback + cache
# ══════════════════════════════════════════════════════════════════════════════

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# LLM response cache — (model, prompt) → text. Identical prompts are instant.
_LLM_CACHE: dict[tuple, str] = {}

# Per-role index into each model list. Each role fails over independently.
_role_idx: dict[str, int] = {"nav": 0, "link": 0, "verify": 0}
_role_chains: dict[str, list[str]] = {
    "nav":    NAV_MODELS,
    "link":   LINK_MODELS,
    "verify": VERIFY_MODELS,
}


def active_model(role: str) -> str:
    chain = _role_chains[role]
    idx   = _role_idx[role]
    return chain[min(idx, len(chain) - 1)]


def _advance_role(role: str, reason: str) -> bool:
    """Moves a role to its next fallback. Returns False if exhausted."""
    chain = _role_chains[role]
    idx   = _role_idx[role]
    if idx + 1 < len(chain):
        _role_idx[role] = idx + 1
        _log(f"{reason} → [{role}] switching to {chain[idx + 1]}")
        return True
    _log(f"{reason} → [{role}] all fallbacks exhausted.")
    return False


def _strip_thinking(text: str) -> str:
    """
    Removes <think>...</think> reasoning blocks that some models (qwen, kimi)
    prepend before their actual response. Without this, JSON parsing fails.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


def call_groq(prompt: str, role: str) -> str:
    """
    Calls Groq using the active model for `role`.

    - Cache hit      → returns instantly, no API call.
    - Rate limit     → waits if short (≤ 2 min), else advances to next model.
    - Decommissioned → advances to next model immediately.
    - Tool use error → advances to next model (gpt-oss models fire browser
                       tools automatically; wrong model for some roles).

    Each role (nav / link / verify) fails over independently.
    """
    for _ in range(len(_role_chains[role])):
        model     = active_model(role)
        cache_key = (model, prompt)

        if cache_key in _LLM_CACHE:
            return _LLM_CACHE[cache_key]

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            text = response.choices[0].message.content.strip()
            text = _strip_thinking(text)          # strip <think> blocks
            _LLM_CACHE[cache_key] = text
            return text

        except Exception as e:
            err = str(e)

            if "rate_limit_exceeded" in err or "429" in err:
                wait = _parse_wait_seconds(err)
                if wait <= 120:
                    _log(f"[{role}] Rate limit on {model} — waiting {wait}s...")
                    time.sleep(wait)
                    continue
                else:
                    _advance_role(role, f"[{role}] Rate limit on {model} ({wait}s wait)")

            elif "decommissioned" in err or "model_not_found" in err:
                _advance_role(role, f"[{role}] {model} decommissioned")

            elif "tool_use_failed" in err or "Tool choice is none" in err:
                # gpt-oss models fire built-in browser tools uninstructed
                _advance_role(role, f"[{role}] {model} fired unwanted tool — switching")

            else:
                _log(f"[{role}] Groq error ({model}): {e}")
                return ""

    return ""


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


# ══════════════════════════════════════════════════════════════════════════════
# HEURISTIC PRE-FILTER  —  reduces LLM calls by ~70%
# ══════════════════════════════════════════════════════════════════════════════

def _keywords_from_goal(goal: str) -> list[str]:
    words = re.findall(r"[a-z]+", goal.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 2]


def heuristic_filter(elements: list[dict], keywords: list[str]) -> list[dict]:
    """
    Returns elements whose text or href contains a goal keyword.
    Falls back to all elements if nothing matches so LLM still gets a chance.
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


# ══════════════════════════════════════════════════════════════════════════════
# DOM EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

DOM_SCRIPT = """() => {
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
}""" % MAX_ELEMENTS


def extract_elements(page) -> list[dict]:
    """
    Pulls visible interactive elements from the live DOM.
    Falls back to BeautifulSoup if the DOM script returns nothing.
    """
    elements = []
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(1000)
        elements = page.evaluate(DOM_SCRIPT)
    except Exception as e:
        _log(f"DOM extraction failed: {e}")

    if not elements:
        _log("DOM empty — falling back to BeautifulSoup")
        try:
            soup = BeautifulSoup(page.content(), "html.parser")
            seen = set()
            for a in soup.find_all("a", href=True):
                href = urljoin(page.url, a["href"])
                text = a.get_text(strip=True)
                if href not in seen and href.startswith("http") and text:
                    seen.add(href)
                    elements.append({"id": len(elements), "text": text[:80], "href": href})
                if len(elements) >= MAX_ELEMENTS:
                    break
        except Exception as e:
            _log(f"BeautifulSoup fallback failed: {e}")

    return elements


def extract_page_signals(page) -> dict:
    """
    Structured signals for verification: title, meta desc, h1s, body text.
    Much better signal than raw body text alone.
    """
    signals = {"title": "", "meta": "", "h1s": [], "body": ""}
    try:
        signals["title"] = page.title() or ""
    except Exception:
        pass
    try:
        signals["meta"] = page.locator("meta[name='description']").get_attribute("content") or ""
    except Exception:
        pass
    try:
        signals["h1s"] = page.locator("h1").all_inner_texts()
    except Exception:
        pass
    try:
        signals["body"] = (page.inner_text("body") or "")[:3000]
    except Exception:
        pass
    return signals


# ══════════════════════════════════════════════════════════════════════════════
# LLM CALLS — one function per role
# ══════════════════════════════════════════════════════════════════════════════

def llm_candidate_links(goal: str, elements: list[dict]) -> list[str]:
    """LINK role — picks candidate URLs likely relevant to the goal."""
    hrefs = [e for e in elements if e.get("href")]
    if not hrefs:
        return []

    prompt = f"""You are a web navigation agent.

User goal: {goal}

Links on the current page:
{json.dumps(hrefs, indent=2)}

Which links are likely to lead to pages relevant to the goal?
Return a JSON array of href values. Full URLs only (starting with http).
Return [] if nothing looks relevant.
Raw JSON only — no explanation, no markdown, no <think> block.
"""
    raw = call_groq(prompt, role="link")
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception:
        _log(f"Could not parse candidate links: {raw[:200]}")
        return []


def llm_verify_page(goal: str, url: str, signals: dict) -> dict | None:
    """
    VERIFY role — reads actual page content to confirm the goal is satisfied.
    Uses structured signals (title + meta + h1 + body) for maximum accuracy.
    This is the quality gate — no false positives pass through.
    """
    prompt = f"""You are a web content analyst verifying search results.

User goal: {goal}

Page URL   : {url}
Title      : {signals['title']}
Meta desc  : {signals['meta']}
H1 headings: {signals['h1s']}
Body text  : {signals['body']}

Does this page actually contain content that satisfies the goal?
Answer in JSON only — no explanation, no markdown, no <think> block:
{{
  "verified": true or false,
  "snippet": "a short 1-sentence quote or summary proving it (empty string if not verified)"
}}
"""
    raw = call_groq(prompt, role="verify")
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception:
        _log(f"Could not parse verification: {raw[:200]}")
        return None


def llm_next_click(goal: str, elements: list[dict]) -> str:
    """
    NAV role — decides which element to click next.
    Uses fast models with no built-in browser tools to avoid tool_use_failed errors.
    """
    prompt = f"""You are a web navigation agent.

User goal: {goal}

Visible clickable elements:
{json.dumps(elements, indent=2)}

Return the NUMBER (id) of the best element to click to get closer to the goal.
If the goal is already satisfied, return: DONE
Return ONLY a number or DONE. No explanation, no markdown, no <think> block.
"""
    return call_groq(prompt, role="nav")


# ══════════════════════════════════════════════════════════════════════════════
# BROWSER
# ══════════════════════════════════════════════════════════════════════════════

def make_browser_and_context(playwright):
    """
    Creates one browser + one persistent context.
    Shared context = shared cookies, faster loads, less overhead.
    headless=False bypasses most bot detection.
    """
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    context.set_default_timeout(30000)
    return browser, context


def load_url(page, url: str) -> bool:
    """
    Loads url using domcontentloaded (not networkidle).
    networkidle hangs on sites like Citi that never stop background requests.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        _log(f"Failed to load {url}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# VERIFICATION  —  sequential browser + parallel Groq calls
# ══════════════════════════════════════════════════════════════════════════════

def verify_candidates(
    candidates: list[str],
    goal:       str,
    context,
    found_urls: set,
) -> list[FoundPage]:
    """
    Two-phase verification:

    Phase 1 (main thread, sequential):
        Open each candidate in a browser page and extract signals.
        Playwright sync API uses greenlets and is NOT thread-safe —
        context.new_page() MUST stay on the main thread.

    Phase 2 (thread pool, parallel):
        Fire all Groq API calls simultaneously.
        HTTP calls are thread-safe — this is where the speed gain is.
    """
    to_check = [u for u in candidates if normalize_url(u) not in found_urls]
    if not to_check:
        return []

    _log(f"Verifying {len(to_check)} candidate(s)...", indent=3)

    # ── Phase 1: load pages on main thread (sequential) ──────────────────────
    page_signals: list[tuple[str, dict]] = []
    verify_page = context.new_page()

    for url in to_check:
        if load_url(verify_page, url):
            signals = extract_page_signals(verify_page)
            page_signals.append((url, signals))
            _log(f"Loaded: {signals['title'] or url}", indent=4)
        else:
            _log(f"Could not load: {url}", indent=4)

    verify_page.close()

    if not page_signals:
        return []

    # ── Phase 2: verify with Groq in parallel (HTTP calls are thread-safe) ───
    sig_map  = {url: sig for url, sig in page_signals}
    verified: list[FoundPage] = []

    def _call_verify(url: str, signals: dict):
        return url, llm_verify_page(goal, url, signals)

    with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as pool:
        futures = {
            pool.submit(_call_verify, url, sig): url
            for url, sig in page_signals
        }
        for future in as_completed(futures):
            url, result = future.result()
            sig = sig_map[url]

            if result and result.get("verified"):
                fp = FoundPage(
                    url     = url,
                    title   = sig["title"] or url,
                    snippet = result.get("snippet", ""),
                    model   = active_model("verify"),
                )
                verified.append(fp)
                _log(f"✓ VERIFIED  [{fp.model}]: {fp.title}", indent=3)
                _log(f'  └ "{fp.snippet}"', indent=3)
            else:
                _log(f"✗ Not relevant: {sig['title'] or url}", indent=3)

    return verified


# ══════════════════════════════════════════════════════════════════════════════
# URL UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def normalize_url(url: str) -> str:
    """Strips fragments and trailing slashes to avoid revisiting the same page."""
    return url.split("#")[0].rstrip("/")


# ══════════════════════════════════════════════════════════════════════════════
# NAVIGATION AGENT
# ══════════════════════════════════════════════════════════════════════════════

def navigate(start_url: str, goal: str, keywords: list[str]) -> list[FoundPage]:
    """
    Opens start_url and navigates step-by-step toward the goal.

    Per step:
      1. Extract DOM elements
      2. Heuristic keyword filter (no LLM — ~70% token savings)
      3. LINK role picks candidate URLs
      4. Browser loads each candidate sequentially, Groq verifies in parallel
      5. NAV role decides next click
    """
    found:      list[FoundPage] = []
    found_urls: set             = set()

    with sync_playwright() as p:
        browser, context = make_browser_and_context(p)
        nav_page = context.new_page()

        if not load_url(nav_page, start_url):
            browser.close()
            return []

        for step in range(MAX_STEPS):

            if len(found) >= TARGET_RESULTS:
                _log(f"Reached TARGET_RESULTS ({TARGET_RESULTS}) — stopping early.")
                break

            _section(f"Step {step + 1}  ·  {nav_page.url}")
            _log(
                f"nav={active_model('nav')}  "
                f"link={active_model('link')}  "
                f"verify={active_model('verify')}",
                indent=3,
            )

            elements = extract_elements(nav_page)
            if not elements:
                _log("No elements found — stopping.")
                break

            # Heuristic filter — keyword match, no LLM
            filtered = heuristic_filter(elements, keywords)
            _log(
                f"Elements: {len(elements)} total → {len(filtered)} after keyword filter",
                indent=3,
            )

            # LINK role: pick candidates from filtered elements
            candidates = llm_candidate_links(goal, filtered)
            _log(f"Candidates: {len(candidates)}", indent=3)

            # Verify (sequential browser load + parallel Groq calls)
            new_results = verify_candidates(candidates, goal, context, found_urls)
            for fp in new_results:
                found_urls.add(normalize_url(fp.url))
                found.append(fp)

            # NAV role: decide next click
            decision = llm_next_click(goal, elements).strip()
            _log(f"Next click: element {decision}", indent=3)

            if not decision or "DONE" in decision.upper():
                _log("NAV model reports goal satisfied — stopping.")
                break

            try:
                chosen = elements[int(decision)]
                target = chosen.get("href", "")

                if not target or target.startswith("javascript:"):
                    _log(f"Skipping non-navigable: {chosen['text']}")
                    break

                nav_page.goto(target, wait_until="domcontentloaded", timeout=30000)
                nav_page.wait_for_timeout(2000)

            except (ValueError, IndexError):
                _log(f"NAV returned invalid decision '{decision}' — stopping.")
                break
            except Exception as e:
                _log(f"Navigation failed: {e}")
                break

        browser.close()

    return found


# ══════════════════════════════════════════════════════════════════════════════
# RECURSIVE CRAWLER
# ══════════════════════════════════════════════════════════════════════════════

def crawl(
    start_url: str,
    goal:      str,
    keywords:  list[str],
    depth:     int = 0,
    visited:   set = None,
) -> list[FoundPage]:
    """Recursively navigates verified pages up to MAX_DEPTH."""
    if visited is None:
        visited = set()

    norm = normalize_url(start_url)
    if depth >= MAX_DEPTH or norm in visited:
        return []
    visited.add(norm)

    print(f"\n{'  ' * depth}{'━' * 54}")
    print(f"{'  ' * depth}  Depth {depth}  ·  {start_url}")
    print(f"{'  ' * depth}{'━' * 54}")

    results = navigate(start_url, goal, keywords)

    for fp in results[:MAX_BRANCH]:
        results.extend(crawl(fp.url, goal, keywords, depth + 1, visited))

    return results


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def run(start_url: str, goal: str) -> list[FoundPage]:
    keywords = _keywords_from_goal(goal)

    print(f"\n{'═' * 54}")
    print(f"  🕷  Web Agent")
    print(f"{'═' * 54}")
    print(f"  Goal         : {goal}")
    print(f"  Start        : {start_url}")
    print(f"  Keywords     : {', '.join(keywords)}")
    print(f"  Nav models   : {' → '.join(NAV_MODELS)}")
    print(f"  Link models  : {' → '.join(LINK_MODELS)}")
    print(f"  Verify models: {' → '.join(VERIFY_MODELS)}")
    print(f"  Target       : stop after {TARGET_RESULTS} verified results")
    print(f"{'═' * 54}")

    seen:   set             = set()
    unique: list[FoundPage] = []
    for fp in crawl(start_url, goal, keywords):
        n = normalize_url(fp.url)
        if n not in seen:
            seen.add(n)
            unique.append(fp)

    # ── Final report ──────────────────────────────────────────────────────────
    print(f"\n{'═' * 54}")
    print(f"  ✅  {len(unique)} verified result(s) found")
    print(f"{'═' * 54}\n")

    for i, fp in enumerate(unique, 1):
        print(f"  {i}. {fp.title}")
        print(f"     URL    : {fp.url}")
        print(f"     Proof  : \"{fp.snippet}\"")
        print(f"     Model  : {fp.model}")
        print()

    if not unique:
        print("  No pages found that match the goal.\n")

    print(f"{'═' * 54}\n")
    return unique


# ══════════════════════════════════════════════════════════════════════════════
# LOGGING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _log(msg: str, indent: int = 2):
    print(f"{'  ' * indent}{msg}")

def _section(title: str):
    print(f"\n  ── {title}")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    # ── Citi: find credit cards mentioning bonus miles ──
    run(
        start_url="https://www.citi.com/credit-cards/compare/view-all-credit-cards",
        goal="Find credit card pages that mention bonus miles",
    )

    # ── Python docs: async & concurrency ──
    # run(
    #     start_url="https://docs.python.org",
    #     goal="Find pages about async and concurrency",
    # )
