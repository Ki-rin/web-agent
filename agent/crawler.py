"""
Recursive crawler.

crawl() navigates a URL and optionally recurses into verified results.
run()  is the main public API — call this with a start URL and goal.
"""

import config
from agent.browser import normalize_url
from agent.extractor import keywords_from_goal
from agent.groq_client import active_model
from agent.models import FoundPage
from agent.navigator import navigate


def crawl(
    start_url: str,
    goal:      str,
    keywords:  list[str],
    depth:     int = 0,
    visited:   set = None,
) -> list[FoundPage]:
    """
    Navigates start_url and recursively follows verified pages
    up to MAX_DEPTH levels deep.
    """
    if visited is None:
        visited = set()

    norm = normalize_url(start_url)
    if depth >= config.MAX_DEPTH or norm in visited:
        return []
    visited.add(norm)

    indent = "  " * depth
    print(f"\n{indent}{'━' * 54}")
    print(f"{indent}  Depth {depth}  ·  {start_url}")
    print(f"{indent}{'━' * 54}")

    results = navigate(start_url, goal, keywords)

    for fp in results[: config.MAX_BRANCH]:
        results.extend(crawl(fp.url, goal, keywords, depth + 1, visited))

    return results


def run(start_url: str, goal: str) -> list[FoundPage]:
    """
    Main entry point. Navigates start_url toward goal and returns
    a deduplicated list of verified FoundPage results.
    """
    keywords = keywords_from_goal(goal)

    _header(goal, start_url, keywords)

    seen:   set             = set()
    unique: list[FoundPage] = []
    for fp in crawl(start_url, goal, keywords):
        n = normalize_url(fp.url)
        if n not in seen:
            seen.add(n)
            unique.append(fp)

    _report(unique)
    return unique


# ── Output helpers ────────────────────────────────────────────────────────────

def _header(goal: str, start_url: str, keywords: list[str]):
    w = 54
    print(f"\n{'═' * w}")
    print(f"  🕷  Web Agent")
    print(f"{'═' * w}")
    print(f"  Goal         : {goal}")
    print(f"  Start        : {start_url}")
    print(f"  Keywords     : {', '.join(keywords)}")
    print(f"  Nav models   : {' → '.join(config.NAV_MODELS)}")
    print(f"  Link models  : {' → '.join(config.LINK_MODELS)}")
    print(f"  Verify models: {' → '.join(config.VERIFY_MODELS)}")
    print(f"  Max steps    : {config.MAX_STEPS}  |  depth: {config.MAX_DEPTH}  |  target: {config.TARGET_RESULTS}")
    print(f"  Page wait    : {config.PAGE_LOAD_WAIT}ms  |  verify workers: {config.VERIFY_WORKERS}")
    print(f"{'═' * w}")


def _report(results: list[FoundPage]):
    w = 54
    print(f"\n{'═' * w}")
    print(f"  ✅  {len(results)} verified result(s) found")
    print(f"{'═' * w}\n")

    for i, fp in enumerate(results, 1):
        print(f"  {i}. {fp.title}")
        print(f"     URL    : {fp.url}")
        print(f"     Proof  : \"{fp.snippet}\"")
        print(f"     Model  : {fp.model}")
        print()

    if not results:
        print("  No pages found matching the goal.\n")

    print(f"{'═' * w}\n")
