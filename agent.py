import json
import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from groq import Groq
from playwright.sync_api import sync_playwright

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama3-70b-8192"
MAX_DEPTH = 2
MAX_LINKS_PER_PAGE = 80
MAX_BRANCH = 3


# ── HTML cleaning ──────────────────────────────────────────────────────────────

def extract_clean_links(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        text = a.get_text(strip=True)

        if href in seen or not href.startswith("http") or text == "":
            continue
        seen.add(href)
        links.append(f"- [{text}]: {href}")

    return "\n".join(links[:MAX_LINKS_PER_PAGE])


# ── LLM call ──────────────────────────────────────────────────────────────────

def ask_groq(query: str, links_text: str) -> list[str]:
    prompt = f"""You are a web navigation agent helping find pages that match a user's goal.

User goal: {query}

Links found on the current page:
{links_text}

Instructions:
- Return ONLY a valid JSON array of URLs that best match the goal.
- Include only full URLs (starting with http).
- Return [] if nothing matches.
- No explanation, no markdown, just raw JSON.

Example output: ["https://example.com/pricing", "https://example.com/plans"]
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
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


# ── Browser ───────────────────────────────────────────────────────────────────

def fetch_page(url: str) -> str | None:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            })
            page.set_default_timeout(20000)
            page.goto(url, wait_until="networkidle", timeout=15000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  [error] Failed to load {url}: {e}")
        return None


# ── Agent loop ────────────────────────────────────────────────────────────────

def crawl(start_url: str, query: str, depth: int = 0, visited: set = None) -> list[str]:
    if visited is None:
        visited = set()

    if depth >= MAX_DEPTH or start_url in visited:
        return []

    visited.add(start_url)
    print(f"\n{'  ' * depth}[depth {depth}] Visiting: {start_url}")

    html = fetch_page(start_url)
    if not html:
        return []

    links_text = extract_clean_links(html, start_url)
    if not links_text:
        print(f"{'  ' * depth}  No links found on page.")
        return []

    matched = ask_groq(query, links_text)
    print(f"{'  ' * depth}  LLM matched {len(matched)} link(s): {matched}")

    results = list(matched)

    for url in matched[:MAX_BRANCH]:
        deeper = crawl(url, query, depth + 1, visited)
        results.extend(deeper)

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

def run(start_url: str, query: str) -> list[str]:
    print(f"\n Starting web agent")
    print(f" Goal   : {query}")
    print(f" Start  : {start_url}")
    print(f" Model  : {MODEL}")
    print("─" * 50)

    found = crawl(start_url, query)
    unique = list(dict.fromkeys(found))

    print("\n" + "─" * 50)
    print(f" Found {len(unique)} matching page(s):\n")
    for link in unique:
        print(f"  • {link}")

    return unique


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run(
        start_url="https://docs.python.org",
        query="Find pages about async and concurrency",
    )
