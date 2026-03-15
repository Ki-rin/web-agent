import json
import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from groq import Groq
from playwright.sync_api import sync_playwright

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
#MODEL        = "llama-3.3-70b-versatile"
MODEL        = "llama-3.1-8b-instant"
MAX_STEPS    = 10   # max clicks per run
MAX_ELEMENTS = 30   # visible elements sent to LLM per page
MAX_BRANCH   = 3    # matched links to recurse into
MAX_DEPTH    = 2    # recursion depth


# ── DOM extraction ─────────────────────────────────────────────────────────────
# Pulls only VISIBLE a + button elements from the live DOM.
# ~10x fewer tokens than raw HTML. Falls back to BeautifulSoup if DOM is empty.

DOM_SCRIPT = """
() => {
    const items = [];
    let i = 0;
    document.querySelectorAll("a, button").forEach(el => {
        if (el.offsetParent !== null) {
            const text = el.innerText.trim();
            if (text) {
                items.push({
                    id:   i++,
                    text: text.slice(0, 80),
                    href: el.href || null
                });
            }
        }
    });
    return items.slice(0, 30);
}
"""


def extract_elements(page) -> list[dict]:
    try:
        # Scroll to trigger lazy-loaded content
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(1000)
        elements = page.evaluate(DOM_SCRIPT)
    except Exception as e:
        print(f"  [warn] DOM extraction failed: {e}")
        elements = []

    # Fallback: parse raw HTML with BeautifulSoup if DOM returns nothing
    if not elements:
        print("  [info] DOM empty, falling back to BeautifulSoup...")
        try:
            soup = BeautifulSoup(page.content(), "html.parser")
            seen = set()
            for i, a in enumerate(soup.find_all("a", href=True)):
                href = urljoin(page.url, a["href"])
                text = a.get_text(strip=True)
                if href not in seen and href.startswith("http") and text:
                    seen.add(href)
                    elements.append({"id": len(elements), "text": text[:80], "href": href})
                if len(elements) >= MAX_ELEMENTS:
                    break
        except Exception as e:
            print(f"  [warn] BeautifulSoup fallback failed: {e}")

    return elements


# ── LLM: decide what to click ─────────────────────────────────────────────────

def ask_groq_action(goal: str, elements: list[dict]) -> str:
    prompt = f"""You are a web navigation agent.

User goal: {goal}

Visible clickable elements on the current page:
{json.dumps(elements, indent=2)}

Instructions:
- Return the NUMBER (id) of the single best element to click to get closer to the goal.
- If the goal is already satisfied on this page, return: DONE
- Return ONLY a number or DONE. No explanation.
"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()


# ── LLM: which links on this page match the goal ──────────────────────────────

def ask_groq_links(goal: str, elements: list[dict]) -> list[str]:
    hrefs = [e for e in elements if e.get("href")]
    if not hrefs:
        return []

    prompt = f"""You are a web navigation agent.

User goal: {goal}

Links on the current page:
{json.dumps(hrefs, indent=2)}

Instructions:
- Return a JSON array of href values that match the goal.
- Only include full URLs (starting with http).
- Return [] if nothing matches.
- No explanation, no markdown, just raw JSON.
"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    raw = response.choices[0].message.content.strip()
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [warn] Could not parse LLM response: {raw[:200]}")
        return []


# ── Browser ────────────────────────────────────────────────────────────────────

def make_page(playwright):
    browser = playwright.chromium.launch(
        headless=False,   # visible browser bypasses most bot detection
    )
    page = browser.new_page()
    page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    page.set_default_timeout(30000)
    return browser, page


def goto(page, url: str) -> bool:
    try:
        # domcontentloaded is faster and works on sites that never reach networkidle
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Extra wait for JS-heavy / slow sites like Citi
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        print(f"  [error] Failed to load {url}: {e}")
        return False


# ── Step-based agent ───────────────────────────────────────────────────────────
# Navigates like a human: looks at the page, picks what to click, repeats.

def navigate(start_url: str, goal: str) -> list[str]:
    found_links: list[str] = []

    with sync_playwright() as p:
        browser, page = make_page(p)

        if not goto(page, start_url):
            browser.close()
            return []

        for step in range(MAX_STEPS):
            print(f"\n  [step {step}] {page.url}")

            elements = extract_elements(page)
            if not elements:
                print("  No elements found on page.")
                break

            # Collect matching links from current page
            matched = ask_groq_links(goal, elements)
            for url in matched:
                if url not in found_links:
                    print(f"  ✓ Found: {url}")
                    found_links.append(url)

            # Decide what to click next
            decision = ask_groq_action(goal, elements)
            print(f"  LLM decision: {decision}")

            if "DONE" in decision.upper():
                print("  Goal satisfied.")
                break

            try:
                idx = int(decision)
                chosen = elements[idx]
                if chosen.get("href"):
                    page.goto(chosen["href"], wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2000)
                else:
                    page.click(f"text={chosen['text']}")
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(2000)
            except Exception as e:
                print(f"  [error] Navigation failed: {e}")
                break

        browser.close()

    return found_links


# ── Recursive crawl ────────────────────────────────────────────────────────────

def crawl(start_url: str, goal: str, depth: int = 0, visited: set = None) -> list[str]:
    if visited is None:
        visited = set()

    if depth >= MAX_DEPTH or start_url in visited:
        return []

    visited.add(start_url)
    print(f"\n{'  ' * depth}[depth {depth}] Starting at: {start_url}")

    results = navigate(start_url, goal)

    for url in results[:MAX_BRANCH]:
        deeper = crawl(url, goal, depth + 1, visited)
        results.extend(deeper)

    return results


# ── Entry point ────────────────────────────────────────────────────────────────

def run(start_url: str, goal: str) -> list[str]:
    print(f"\n{'─' * 50}")
    print(f" Web Agent")
    print(f" Goal  : {goal}")
    print(f" Start : {start_url}")
    print(f" Model : {MODEL}")
    print(f"{'─' * 50}")

    found = crawl(start_url, goal)
    unique = list(dict.fromkeys(found))

    print(f"\n{'─' * 50}")
    print(f" Found {len(unique)} matching page(s):\n")
    for link in unique:
        print(f"  • {link}")

    return unique


# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run(
        start_url="https://docs.python.org",
        goal="Find pages about async and concurrency",
    )
