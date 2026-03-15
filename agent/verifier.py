"""
Candidate page verifier.

Two-phase design to work around Playwright's threading constraint:

  Phase 1 (main thread, sequential):
      Open each candidate in the browser and extract page signals.
      Playwright sync API uses greenlets and cannot be called from threads —
      context.new_page() MUST stay on the main thread.

  Phase 2 (thread pool, parallel):
      Fire all Groq verification API calls simultaneously.
      HTTP calls are fully thread-safe. This is where the speed gain is.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from agent.browser import load_url
from agent.extractor import extract_signals
from agent.groq_client import active_model
from agent.llm_tasks import llm_verify_page
from agent.models import FoundPage


def verify_candidates(
    candidates: list[str],
    goal:       str,
    context,
    found_urls: set,
) -> list[FoundPage]:
    """
    Verifies a list of candidate URLs and returns only those that
    actually satisfy the goal.
    """
    # Normalize before dedup — found_urls stores normalized URLs
    to_check = [u for u in candidates if u.split("#")[0].rstrip("/") not in found_urls]
    if not to_check:
        return []

    print(f"      Verifying {len(to_check)} candidate(s)...")

    # ── Phase 1: load pages sequentially on main thread ───────────────────────
    page_signals: list[tuple[str, dict]] = _collect_signals(to_check, context)
    if not page_signals:
        return []

    # ── Phase 2: verify with Groq in parallel ─────────────────────────────────
    return _parallel_verify(page_signals, goal)


def _collect_signals(urls: list[str], context) -> list[tuple[str, dict]]:
    """Opens each URL in a single verify page and collects structured signals."""
    results = []
    page    = context.new_page()
    try:
        for url in urls:
            if load_url(page, url):
                signals = extract_signals(page)
                results.append((url, signals))
                print(f"        Loaded: {signals['title'] or url}")
            else:
                print(f"        Could not load: {url}")
    finally:
        page.close()
    return results


def _parallel_verify(
    page_signals: list[tuple[str, dict]],
    goal:         str,
) -> list[FoundPage]:
    """Calls Groq verification for all pages in parallel threads."""
    sig_map  = {url: sig for url, sig in page_signals}
    verified = []

    def _verify(url: str, signals: dict):
        return url, llm_verify_page(goal, url, signals)

    with ThreadPoolExecutor(max_workers=config.VERIFY_WORKERS) as pool:
        futures = {
            pool.submit(_verify, url, sig): url
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
                print(f"      ✓ VERIFIED [{fp.model}]: {fp.title}")
                print(f'        └ "{fp.snippet}"')
            else:
                print(f"      ✗ Not relevant: {sig['title'] or url}")

    return verified
