"""
llm_tasks.py — prompts for nav / link / verify LLM calls.
"""

import json

from agent.groq_client import call


def _parse_json(raw: str, fallback):
    """Strips markdown fences and parses JSON. Returns fallback on failure."""
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception:
        print(f"    Could not parse JSON: {raw[:200]}")
        return fallback


def llm_extract_keywords(goal: str) -> list[str]:
    """
    Asks the LLM to generate search keywords from a goal description.

    Returns lowercase terms that might appear in link text or URLs on relevant pages.
    One cheap call at startup — result is cached by groq_client.
    """
    prompt = f"""Given this browsing goal, generate 8-15 short keywords or phrases
that would likely appear in link text or URLs on relevant pages.

Goal: {goal}

Include:
- Obvious terms from the goal itself
- Related product names, brand terms, or category names a site might use
- Synonyms and variations (e.g. "miles" → also "rewards", "points", "earn")

Return a JSON array of lowercase strings. No explanation, no markdown, no <think> block.
Example: ["credit card", "bonus miles", "rewards", "aadvantage", "travel", "earn"]"""
    result = _parse_json(call(prompt, role="link"), [])
    if result:
        print(f"  Keywords: {', '.join(result)}")
    return result


def llm_candidate_links(goal: str, elements: list[dict]) -> list[str]:
    """LINK role — pick candidate URLs that could lead to relevant pages."""
    hrefs = [e for e in elements if e.get("href")]
    if not hrefs:
        return []
    prompt = f"""You are a web navigation agent.
User goal: {goal}

Links on the current page:
{json.dumps(hrefs, indent=2)}

Return a JSON array of href values for links that could lead to pages relevant to the goal.
Include specific product pages AND category pages that might contain relevant content.
Be INCLUSIVE — it is better to check an extra link than to miss one.
Full URLs only (starting with http). Return [] only if truly nothing is relevant.
Raw JSON only — no explanation, no markdown, no <think> block."""
    return _parse_json(call(prompt, role="link"), [])


def llm_verify_page(goal: str, url: str, signals: dict) -> dict | None:
    """
    VERIFY role — strictly checks if this is a SPECIFIC page about the goal topic.
    Rejects homepages, listing pages, and pages that only mention the topic in passing.
    """
    prompt = f"""You are a strict web content analyst verifying search results.
User goal: {goal}

URL  : {url}
Title: {signals['title']}
Meta : {signals['meta']}
H1s  : {signals['h1s']}
Body : {signals['body']}

A page PASSES verification ONLY if ALL of these are true:
1. It is a SPECIFIC page dedicated to one product, topic, or focused content — NOT a homepage, listing page, or category overview
2. The goal topic is a PRIMARY feature of this page, not just mentioned in passing in a list
3. A user who searched specifically for "{goal}" would bookmark THIS page as directly useful

A page FAILS if:
- It is a homepage, "view all cards" page, or generic category/comparison page
- The goal keyword appears only in a sidebar, footer, or small list item
- The page is primarily about something else and only tangentially mentions the goal

Answer in JSON only — no explanation, no markdown, no <think> block:
{{"verified": true or false, "snippet": "exact short quote proving it satisfies the goal (empty string if not verified)"}}"""
    return _parse_json(call(prompt, role="verify"), None)


def llm_next_click(
    goal:         str,
    elements:     list[dict],
    found_count:  int,
    target:       int,
    avoid_ids:    list[int],
    visited_urls: list[str],
) -> str:
    """NAV role — picks the next element to click toward finding more relevant pages."""
    avoid_note = ""
    if avoid_ids:
        avoid_note += f"\nDo NOT pick these element ids (already tried this step): {avoid_ids}"
    if visited_urls:
        avoid_note += f"\nAlready visited these pages (avoid going back): {visited_urls[-6:]}"

    # Remind the LLM to stay focused on the goal topic
    scope_note = f"""
IMPORTANT: Stay focused on the goal. Do NOT click links to unrelated site sections
(e.g. if the goal is about credit cards, don't click Banking, Lending, Investing, etc.).
Only click links that could plausibly lead to content relevant to: "{goal}"."""

    prompt = f"""You are a web navigation agent exploring a website.
User goal: {goal}
Progress: {found_count} of {target} target pages found so far.{avoid_note}{scope_note}

Clickable elements:
{json.dumps(elements, indent=2)}

Rules:
- NEVER click Apply, Sign Up, Login, terms, or any application/form links
- Do NOT pick any id listed in "already tried"
- Prefer links to SPECIFIC individual product or content pages over generic navigation
- Look for card names, product categories, or topic sections to explore
- Only return DONE if {found_count} >= {target} OR you have exhausted all relevant options

Return ONLY a number (element id) or DONE. No explanation, no markdown, no <think> block."""
    return call(prompt, role="nav")
