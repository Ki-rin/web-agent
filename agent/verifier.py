"""
verifier.py — load candidate pages and verify them against the goal.

Phase 1: Browser loads each page sequentially (Playwright is not thread-safe)
Phase 2: Groq verification calls fire in parallel (HTTP is thread-safe)
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from agent.browser import is_dead_end, load_url
from agent.extractor import extract_signals
from agent.groq_client import active_model
from agent.llm_tasks import llm_verify_page
from agent.models import FoundPage


def verify_candidates(
    candidates: list[str], goal: str, context, checked_urls: set,
) -> list[FoundPage]:
    """Verifies candidate URLs against the goal. Returns matching pages."""
    from agent.browser import normalize_url
    to_check = [
        u for u in candidates
        if not is_dead_end(u) and normalize_url(u) not in checked_urls
    ][:config.MAX_VERIFY_PER_STEP]
    if not to_check:
        return []

    print(f"      Verifying {len(to_check)} candidate(s)...")
    page_signals = _load_signals(to_check, context)
    return _verify_parallel(page_signals, goal)


def _load_signals(urls: list[str], context) -> list[tuple[str, dict]]:
    """Opens each URL and collects page signals. Must run on main thread."""
    results, page = [], context.new_page()
    try:
        for url in urls:
            if load_url(page, url):
                sig = extract_signals(page)
                results.append((url, sig))
                print(f"        Loaded: {sig['title'] or url}")
            else:
                print(f"        Could not load: {url}")
    finally:
        page.close()
    return results


def _verify_one(goal: str, url: str, sig: dict) -> tuple[str, dict | None, str]:
    """
    Calls llm_verify_page and captures the model name that was active
    at call time (inside the worker thread) so it's accurate even when
    parallel fallbacks occur.
    """
    model_used = active_model("verify")
    result = llm_verify_page(goal, url, sig)
    return url, result, model_used


def _verify_parallel(page_signals: list[tuple[str, dict]], goal: str) -> list[FoundPage]:
    """Calls Groq for all pages in parallel and returns verified results."""
    sig_map  = {url: sig for url, sig in page_signals}
    verified = []

    with ThreadPoolExecutor(max_workers=config.VERIFY_WORKERS) as pool:
        futures = {
            pool.submit(_verify_one, goal, url, sig): url
            for url, sig in page_signals
        }
        for future in as_completed(futures):
            url, result, model_used = future.result()
            sig = sig_map[url]

            if result and result.get("verified"):
                fp = FoundPage(
                    url          = url,
                    title        = sig["title"] or url,
                    snippet      = result.get("snippet", ""),
                    verify_model = model_used,   # captured inside thread — always accurate
                )
                verified.append(fp)
                print(f"      ✓ VERIFIED [{fp.verify_model}]: {fp.title}")
                print(f'        └ "{fp.snippet}"')
            else:
                print(f"      ✗ Not relevant: {sig['title'] or url}")

    return verified
