"""
crawler.py — recursive crawl + run() entry point + final report.
"""

import time

import config
from agent.browser import normalize_url
from agent.llm_tasks import llm_extract_keywords
from agent.models import FoundPage, StepLog
from agent.navigator import navigate


def crawl(
    start_url:   str,
    goal:        str,
    keywords:    list[str],
    depth:       int = 0,
    click_depth: int = 0,
    visited:     set = None,
) -> tuple[list[FoundPage], list[StepLog]]:
    """Navigates start_url and recursively follows verified pages up to MAX_DEPTH."""
    if visited is None:
        visited = set()

    norm = normalize_url(start_url)
    if depth > config.MAX_DEPTH or norm in visited:
        return [], []
    visited.add(norm)

    print(f"\n{'━' * 60}")
    print(f"  Depth {depth}  ·  {start_url}")
    print(f"{'━' * 60}")

    pages, logs = navigate(start_url, goal, keywords, start_click_depth=click_depth)

    for fp in pages[:config.MAX_BRANCH]:
        sub_pages, sub_logs = crawl(
            fp.url, goal, keywords,
            depth       = depth + 1,
            click_depth = fp.clicks_from_start + 1,
            visited     = visited,
        )
        pages.extend(sub_pages)
        logs.extend(sub_logs)

    return pages, logs


def run(start_url: str, goal: str) -> list[FoundPage]:
    """Main entry point. Returns deduplicated verified pages."""
    run_start = time.time()

    _header(goal, start_url)
    keywords = llm_extract_keywords(goal, start_url)

    all_pages, all_logs = crawl(start_url, goal, keywords)

    # Deduplicate
    seen, unique = set(), []
    for fp in all_pages:
        n = normalize_url(fp.url)
        if n not in seen:
            seen.add(n)
            unique.append(fp)

    _report(unique, all_logs, round(time.time() - run_start, 1))
    return unique


# ── Output ────────────────────────────────────────────────────────────────────

W = 60

def _header(goal: str, start_url: str):
    print(f"\n{'═' * W}")
    print(f"  🕷  Web Agent")
    print(f"{'═' * W}")
    print(f"  Goal     : {goal}")
    print(f"  Start    : {start_url}")
    print(f"  NAV      : {' → '.join(config.NAV_MODELS)}")
    print(f"  LINK     : {' → '.join(config.LINK_MODELS)}")
    print(f"  VERIFY   : {' → '.join(config.VERIFY_MODELS)}")
    print(f"{'═' * W}")


def _report(results: list[FoundPage], logs: list[StepLog], total_time: float):
    print(f"\n{'─' * W}")
    print(f"  Run summary  ({len(logs)} step(s)  ·  {total_time}s total)")
    print(f"{'─' * W}")
    print(f"  {'#':<4} {'Clicks':<7} {'✓/Cand':<9} {'Time':>6}  Page visited")
    print(f"  {'─'*3} {'─'*6} {'─'*8} {'─'*6}  {'─'*35}")

    for log in logs:
        ratio = f"{log.verified}/{log.candidates}"
        page  = log.url.split("?")[0].replace("https://", "")
        page  = (page[:38] + "…") if len(page) > 38 else page
        print(f"  {log.step:<4} {log.clicks_from_start:<7} {ratio:<9} {log.latency_s:>5.1f}s  {page}")

    total_cand = sum(l.candidates for l in logs)
    total_ver  = sum(l.verified   for l in logs)
    total_lat  = round(sum(l.latency_s for l in logs), 1)
    print(f"  {'─'*3} {'─'*6} {'─'*8} {'─'*6}")
    print(f"  {'':4} {'':7} {f'{total_ver}/{total_cand}':<9} {total_lat:>5.1f}s")

    print(f"\n{'═' * W}")
    print(f"  ✅  {len(results)} result(s) found")
    print(f"{'═' * W}\n")

    for i, fp in enumerate(results, 1):
        print(f"  {i}. {fp.title}")
        print(f"     {fp.url}")
        print(f"     💬 \"{fp.snippet}\"")
        print(f"     step {fp.found_at_step}  ·  {fp.clicks_from_start} click(s) from start  ·  {fp.verify_model}")
        print()

    if not results:
        print("  No matching pages found.\n")
        print("  Try: increase MAX_STEPS or MAX_DEPTH in config.py,")
        print("       or use a broader goal description.\n")

    print(f"{'═' * W}\n")
