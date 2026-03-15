"""
LLM task functions — one per role.

  llm_candidate_links : LINK role  — which links look relevant?
  llm_verify_page     : VERIFY role — does this page actually satisfy goal?
  llm_next_click      : NAV role   — which element to click next?
"""

import json

from agent.groq_client import call


def llm_candidate_links(goal: str, elements: list[dict]) -> list[str]:
    """
    LINK role — scans link text/URLs and picks candidates likely relevant
    to the goal. Fast pattern matching, not deep content reading.
    """
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
    raw = call(prompt, role="link")
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception:
        print(f"    Could not parse candidate links: {raw[:200]}")
        return []


def llm_verify_page(goal: str, url: str, signals: dict) -> dict | None:
    """
    VERIFY role — reads actual page content (title + meta + h1 + body)
    and confirms whether the goal is satisfied.

    This is the quality gate. Every result must pass before being returned.
    Returns {"verified": bool, "snippet": str} or None on parse failure.
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
    raw = call(prompt, role="verify")
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception:
        print(f"    Could not parse verification: {raw[:200]}")
        return None


def llm_next_click(goal: str, elements: list[dict]) -> str:
    """
    NAV role — decides which element to click next, or returns DONE.
    Uses only fast models with no built-in browser tools to avoid
    tool_use_failed errors from gpt-oss models.
    """
    prompt = f"""You are a web navigation agent.

User goal: {goal}

Visible clickable elements:
{json.dumps(elements, indent=2)}

Return the NUMBER (id) of the best element to click to get closer to the goal.
If the goal is already satisfied, return: DONE
Return ONLY a number or DONE. No explanation, no markdown, no <think> block.
"""
    return call(prompt, role="nav")
