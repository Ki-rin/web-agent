import json
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from groq import Groq
from playwright.sync_api import sync_playwright

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

MAX_STEPS    = 10   # max clicks the agent takes per session
MAX_ELEMENTS = 30   # max links/buttons sent to LLM per page
MAX_BRANCH   = 3    # matched links to recurse into
MAX_DEPTH    = 2    # crawl depth

# Models tried in order on 429 / decommission. Best quality → most token-efficient.
# All verified from https://console.groq.com/docs/models
MODELS = [
    "llama-3.3-70b-versatile",                   # best production model, 280 t/s
    "openai/gpt-oss-120b",                        # top reasoning, 500 t/s, 131k ctx
    "moonshotai/kimi-k2-instruct-0905",           # 262k context, great for large pages
    "qwen/qwen3-32b",                             # strong alternative, 400 t/s
    "meta-llama/llama-4-scout-17b-16e-instruct",  # fast preview, 750 t/s, cheap
    "openai/gpt-oss-20b",                         # fastest: 1000 t/s, very cheap
    "llama-3.1-8b-instant",                       # last resort: 560 t/s, $0.05/1M
]


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class FoundPage:
    url:       str
    title:     str   # page <title> or best guess
    snippet:   str   # short excerpt proving the goal was found
    model:     str   # which LLM verified this result


# ── Groq client ────────────────────────────────────────────────────────────────

client     = Groq(api_key=os.getenv("GROQ_API_KEY"))
_model_idx = 0


def current_model() -> str:
    return MODELS[_model_idx]


def call_groq(prompt: str) -> str:
    """
    Calls Groq with the current model.
    - Short rate limit  (<= 2 min): waits and retries same model.
    - Long rate limit   (> 2 min):  switches to next model.
    - Decommissioned model:         switches to next model immediately.
    """
    global _model_idx

    for _ in range(len(MODELS)):
        model = MODELS[_model_idx]
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            err = str(e)

            if "rate_limit_exceeded" in err or "429" in err:
                wait = _parse_wait_seconds(err)
                if wait <= 120:
                    _log(f"Rate limit on {model} — waiting {wait}s then retrying...")
                    time.sleep(wait)
                    continue
                else:
                    _switch_model(f"Rate limit on {model} (wait: {wait}s)")

            elif "decommissioned" in err or "model_not_found" in err:
                _switch_model(f"{model} is decommissioned")

            else:
                _log(f"Groq error: {e}")
                return ""

    return ""


def _switch_model(reason: str):
    global _model_idx
    if _model_idx < len(MODELS) - 1:
        _model_idx += 1
        _log(f"{reason} → switching to {MODELS[_model_idx]}")
    else:
        _log("All models exhausted.")


def _parse_wait_seconds(error_msg: str) -> int:
    """Parses '17m4.704s' style wait times from Groq 429 error messages."""
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


# ── Logging helpers ────────────────────────────────────────────────────────────

def _log(msg: str, indent: int = 2):
    print(f"{'  ' * indent}{msg}")

def _section(title: str):
    print(f"\n  ── {title}")


# ── DOM extraction ─────────────────────────────────────────────────────────────

DOM_SCRIPT = """() => {
    const items = [];
    let i = 0;
    document.querySelectorAll("a, button").forEach(el => {
        if (el.offsetParent !== null) {
            const text = el.innerText.trim();
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
    Extracts visible links + buttons from the live DOM.
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


def get_page_text(page) -> str:
    """Returns visible body text, capped at 3000 chars to save tokens."""
    try:
        return page.inner_text("body")[:3000]
    except Exception:
        return ""


def get_page_title(page) -> str:
    try:
        return page.title()
    except Exception:
        return page.url


# ── LLM calls ──────────────────────────────────────────────────────────────────

def llm_find_candidate_links(goal: str, elements: list[dict]) -> list[str]:
    """
    Step 1 of 2: asks the LLM which links *might* be relevant to the goal,
    based on link text and URL alone. Returns candidates for verification.
    """
    hrefs = [e for e in elements if e.get("href")]
    if not hrefs:
        return []

    prompt = f"""You are a web navigation agent helping find relevant pages.

User goal: {goal}

Links on the current page:
{json.dumps(hrefs, indent=2)}

Which links are likely to lead to pages relevant to the goal?
Return a JSON array of href values. Only full URLs (starting with http).
Return [] if nothing looks relevant.
Raw JSON only — no explanation, no markdown.
"""
    raw = call_groq(prompt)
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception:
        _log(f"Could not parse candidate links: {raw[:150]}")
        return []


def llm_verify_page(goal: str, url: str, title: str, body_text: str) -> dict | None:
    """
    Step 2 of 2: actually reads the page content and confirms whether the goal
    is satisfied. Returns a dict with {verified, snippet} or None on failure.

    This is the quality gate — no page is added to results without passing this.
    """
    prompt = f"""You are a web content analyst.

User goal: {goal}

Page URL:   {url}
Page title: {title}
Page text (first 3000 chars):
{body_text}

Does this page actually contain content that satisfies the goal?
Answer in JSON:
{{
  "verified": true or false,
  "snippet": "a short 1-sentence quote or summary from the page proving it (or empty string if not verified)"
}}
Raw JSON only.
"""
    raw = call_groq(prompt)
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception:
        _log(f"Could not parse verification response: {raw[:150]}")
        return None


def llm_decide_next_click(goal: str, elements: list[dict]) -> str:
    """Asks the LLM which element to click next, or DONE if goal is satisfied."""
    prompt = f"""You are a web navigation agent.

User goal: {goal}

Visible clickable elements:
{json.dumps(elements, indent=2)}

Return the NUMBER (id) of the best element to click to get closer to the goal.
If the goal is already satisfied on this page, return: DONE
Return ONLY a number or DONE. No explanation.
"""
    return call_groq(prompt)


# ── Browser ────────────────────────────────────────────────────────────────────

def make_browser_page(playwright):
    """Launches a visible Chromium window with realistic headers."""
    browser = playwright.chromium.launch(headless=False)
    page    = browser.new_page()
    page.set_extra_http_headers({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    page.set_default_timeout(30000)
    return browser, page


def load_page(page, url: str) -> bool:
    """
    Loads a URL using domcontentloaded.
    Avoids networkidle which hangs on JS-heavy sites like Citi.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        _log(f"Failed to load {url}: {e}")
        return False


# ── Core agent loop ────────────────────────────────────────────────────────────

def navigate(start_url: str, goal: str) -> list[FoundPage]:
    """
    Opens start_url and navigates step-by-step toward the goal.
    Each candidate link is VERIFIED by reading actual page content
    before being added to results.
    """
    found: list[FoundPage] = []

    with sync_playwright() as p:
        browser, page = make_browser_page(p)

        if not load_page(page, start_url):
            browser.close()
            return []

        for step in range(MAX_STEPS):
            _section(f"Step {step + 1}  —  {page.url}")
            _log(f"Model: {current_model()}", indent=3)

            elements = extract_elements(page)
            if not elements:
                _log("No elements found — stopping.")
                break

            # Find candidate links (LLM guesses from link text)
            candidates = llm_find_candidate_links(goal, elements)
            _log(f"Candidates from this page: {len(candidates)}", indent=3)

            # Verify each candidate by actually reading its content
            for url in candidates:
                if url in [r.url for r in found]:
                    continue
                if not load_page(page, url):
                    continue

                title     = get_page_title(page)
                body_text = get_page_text(page)
                result    = llm_verify_page(goal, url, title, body_text)

                if result and result.get("verified"):
                    fp = FoundPage(
                        url     = url,
                        title   = title,
                        snippet = result.get("snippet", ""),
                        model   = current_model(),
                    )
                    found.append(fp)
                    _log(f"✓ VERIFIED: {title}", indent=3)
                    _log(f"  └ {fp.snippet}", indent=3)
                else:
                    _log(f"✗ Not relevant: {title}", indent=3)

                # Go back to the navigation page
                load_page(page, start_url)

            # Decide what to click next
            decision = llm_decide_next_click(goal, elements)
            _log(f"Next click: {decision}", indent=3)

            if "DONE" in decision.upper():
                _log("Goal satisfied — stopping.")
                break

            try:
                chosen = elements[int(decision)]
                if chosen.get("href"):
                    page.goto(chosen["href"], wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2000)
                else:
                    page.click(f"text={chosen['text']}")
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(2000)
            except Exception as e:
                _log(f"Navigation failed: {e}")
                break

        browser.close()

    return found


# ── Recursive crawler ──────────────────────────────────────────────────────────

def crawl(
    start_url: str,
    goal:      str,
    depth:     int       = 0,
    visited:   set       = None,
) -> list[FoundPage]:
    """Recursively navigates matched pages up to MAX_DEPTH."""
    if visited is None:
        visited = set()
    if depth >= MAX_DEPTH or start_url in visited:
        return []

    visited.add(start_url)
    print(f"\n{'  ' * depth}{'━' * 48}")
    print(f"{'  ' * depth}  Crawling depth {depth}: {start_url}")
    print(f"{'  ' * depth}{'━' * 48}")

    results = navigate(start_url, goal)

    for page in results[:MAX_BRANCH]:
        results.extend(crawl(page.url, goal, depth + 1, visited))

    return results


# ── Public API ─────────────────────────────────────────────────────────────────

def run(start_url: str, goal: str) -> list[FoundPage]:
    print(f"\n{'═' * 52}")
    print(f"  🕷  Web Agent")
    print(f"{'═' * 52}")
    print(f"  Goal    : {goal}")
    print(f"  Start   : {start_url}")
    print(f"  Model   : {current_model()} (+ {len(MODELS) - 1} fallbacks)")
    print(f"  Fallbacks: {', '.join(MODELS[1:])}")
    print(f"{'═' * 52}")

    seen_urls = set()
    unique: list[FoundPage] = []
    for fp in crawl(start_url, goal):
        if fp.url not in seen_urls:
            seen_urls.add(fp.url)
            unique.append(fp)

    # ── Final report ──
    print(f"\n{'═' * 52}")
    print(f"  ✅  Results  —  {len(unique)} verified page(s) found")
    print(f"{'═' * 52}\n")

    for i, fp in enumerate(unique, 1):
        print(f"  {i}. {fp.title}")
        print(f"     URL     : {fp.url}")
        print(f"     Verified: \"{fp.snippet}\"")
        print(f"     Model   : {fp.model}")
        print()

    if not unique:
        print("  No pages found that match the goal.")

    print(f"{'═' * 52}\n")
    return unique


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # ── Citi: credit cards with bonus miles ──
    run(
        start_url="https://www.citi.com/credit-cards/compare/view-all-credit-cards",
        goal="Find credit card pages that mention bonus miles",
    )

    # ── Python docs: async & concurrency ──
    # run(
    #     start_url="https://docs.python.org",
    #     goal="Find pages about async and concurrency",
    # )
