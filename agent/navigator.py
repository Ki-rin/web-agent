"""
Step-based navigation agent.

Opens a URL and navigates toward a goal one click at a time:
  1. Extract visible DOM elements
  2. Keyword pre-filter (no LLM)
  3. LINK model picks candidate URLs
  4. Verifier confirms candidates (sequential browser + parallel Groq)
  5. NAV model picks next click
  6. Repeat until DONE, TARGET_RESULTS reached, or MAX_STEPS exhausted
"""

import config
from agent.browser import load_url, make_browser_and_context, normalize_url
from agent.extractor import extract_elements, heuristic_filter
from agent.groq_client import active_model
from agent.llm_tasks import llm_candidate_links, llm_next_click
from agent.models import FoundPage
from agent.verifier import verify_candidates
from playwright.sync_api import sync_playwright


def navigate(start_url: str, goal: str, keywords: list[str]) -> list[FoundPage]:
    """
    Navigates start_url step-by-step toward goal.
    Returns a list of verified FoundPage results.
    """
    found:      list[FoundPage] = []
    found_urls: set             = set()

    with sync_playwright() as p:
        browser, context = make_browser_and_context(p)
        nav_page = context.new_page()

        if not load_url(nav_page, start_url):
            browser.close()
            return []

        for step in range(config.MAX_STEPS):

            if len(found) >= config.TARGET_RESULTS:
                print(f"    Target ({config.TARGET_RESULTS} results) reached — stopping.")
                break

            print(f"\n  ── Step {step + 1}  ·  {nav_page.url}")
            print(
                f"    nav={active_model('nav')}  "
                f"link={active_model('link')}  "
                f"verify={active_model('verify')}"
            )

            # 1. Extract DOM
            elements = extract_elements(nav_page)
            if not elements:
                print("    No elements found — stopping.")
                break

            # 2. Keyword pre-filter
            filtered = heuristic_filter(elements, keywords)
            print(f"    Elements: {len(elements)} → {len(filtered)} after keyword filter")

            # 3. LINK model: pick candidates
            candidates = llm_candidate_links(goal, filtered)
            print(f"    Candidates: {len(candidates)}")

            # 4. Verify candidates
            new_results = verify_candidates(candidates, goal, context, found_urls)
            for fp in new_results:
                found_urls.add(normalize_url(fp.url))
                found.append(fp)

            # 5. NAV model: next click
            decision = llm_next_click(goal, elements).strip()
            print(f"    Next click: {decision}")

            if not decision or "DONE" in decision.upper():
                print("    NAV model satisfied — stopping.")
                break

            # 6. Execute click
            try:
                chosen = elements[int(decision)]
                target = chosen.get("href", "")

                if not target or target.startswith("javascript:"):
                    print(f"    Skipping non-navigable: {chosen['text']}")
                    break

                nav_page.goto(target, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT)
                nav_page.wait_for_timeout(config.CLICK_WAIT)

            except (ValueError, IndexError):
                print(f"    Invalid NAV decision '{decision}' — stopping.")
                break
            except Exception as e:
                print(f"    Navigation failed: {e}")
                break

        browser.close()

    return found
