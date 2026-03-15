"""
navigator.py — step-by-step navigation loop.

Each step:
  1. Extract visible DOM elements
  2. LINK model picks candidate URLs → VERIFY them
  3. NAV model picks the next click
  4. Dismiss overlays, click, repeat
"""

import re
import time

import config
from agent.browser import (
    dismiss_overlays, is_dead_end, load_url,
    make_browser_and_context, normalize_url,
)
from agent.extractor import extract_elements, heuristic_filter
from agent.groq_client import active_model
from agent.llm_tasks import llm_candidate_links, llm_next_click
from agent.models import FoundPage, StepLog
from agent.verifier import verify_candidates
from playwright.sync_api import sync_playwright


def navigate(
    start_url:         str,
    goal:              str,
    keywords:          list[str],
    start_click_depth: int = 0,
) -> tuple[list[FoundPage], list[StepLog]]:
    """Navigates start_url step-by-step. Returns (verified pages, step logs)."""
    found:        list[FoundPage] = []
    logs:         list[StepLog]   = []
    found_urls:   set             = set()
    checked_urls: set             = set()  # all URLs sent to verifier (verified or not)
    visited:      set             = set()
    clicks:       int             = start_click_depth

    with sync_playwright() as p:
        browser, context = make_browser_and_context(p)
        nav_page = context.new_page()

        if not load_url(nav_page, start_url):
            browser.close()
            return [], []

        for step in range(config.MAX_STEPS):

            if len(found) >= config.TARGET_RESULTS:
                print(f"  ⏹  Target reached ({config.TARGET_RESULTS} results)")
                break

            step_start = time.time()
            step_num   = step + 1
            cur_url    = nav_page.url
            cur_norm   = normalize_url(cur_url)

            # ── Guard: dead-end → return to start ──────────────────────
            if is_dead_end(cur_url):
                print(f"\n  ↩  Dead-end at step {step_num} — returning to start.")
                if not load_url(nav_page, start_url):
                    break
                continue

            # ── Guard: already visited → loop (start URL is exempt) ────────
            is_start = (cur_norm == normalize_url(start_url))
            if cur_norm in visited and not is_start:
                print(f"\n  ⚠  Loop at step {step_num} — stopping.")
                break
            visited.add(cur_norm)

            print(f"\n  Step {step_num}  ·  {_short(cur_url)}  [{clicks} click(s) from start]")

            # ── Extract elements, pre-filter by keywords ──────────────────
            all_elements = extract_elements(nav_page)
            if not all_elements:
                print("    ⚠  No elements found")
                break

            # Use keyword-matched subset if rich enough, else all elements
            filtered = heuristic_filter(all_elements, keywords)
            use_filtered = len(filtered) >= 5 and len(filtered) < len(all_elements)
            link_input = filtered if use_filtered else all_elements
            candidates = llm_candidate_links(goal, link_input)

            models_str = (f"nav={active_model('nav').split('/')[-1]}  "
                          f"link={active_model('link').split('/')[-1]}  "
                          f"verify={active_model('verify').split('/')[-1]}")
            filter_str = f"{len(filtered)} keyword-matched" + (" → used" if use_filtered else " → sent all")
            print(f"    {len(all_elements)} elements ({filter_str})"
                  f"  →  {len(candidates)} candidates  |  {models_str}")

            # ── Verify candidates ─────────────────────────────────────────
            new_results = verify_candidates(candidates, goal, context, checked_urls)
            for url in candidates:
                checked_urls.add(normalize_url(url))
            for fp in new_results:
                fp.found_at_step     = step_num
                fp.clicks_from_start = clicks
                found_urls.add(normalize_url(fp.url))
                found.append(fp)

            if new_results:
                print(f"    ✓ {len(new_results)} verified")

            # ── Navigate: try clicking up to MAX_CLICK_RETRIES times ──────
            navigated  = False
            tried_ids: list[int] = []

            for attempt in range(config.MAX_CLICK_RETRIES):
                raw = llm_next_click(
                    goal         = goal,
                    elements     = all_elements,
                    found_count  = len(found),
                    target       = config.TARGET_RESULTS,
                    avoid_ids    = tried_ids,
                    visited_urls = list(visited),
                )
                decision = _parse_decision(raw)
                latency  = round(time.time() - step_start, 1)
                suffix   = f"  (attempt {attempt + 1})" if attempt > 0 else ""
                print(f"    → next: {decision}  |  {latency}s{suffix}")

                if decision == "DONE":
                    logs.append(_make_log(step_num, cur_url, clicks,
                                          len(candidates), len(new_results), latency))
                    print("  ✅  NAV satisfied — stopping.")
                    browser.close()
                    return found, logs

                if decision is None:
                    break

                tried_ids.append(decision)
                navigated = _try_click(nav_page, all_elements, decision)
                if navigated:
                    clicks += 1
                    break

            latency = round(time.time() - step_start, 1)
            logs.append(_make_log(step_num, cur_url, clicks - (1 if navigated else 0),
                                  len(candidates), len(new_results), latency))

            if not navigated:
                # Couldn't navigate anywhere useful — go back to start to try other paths
                print("    ⚠  No navigable element — returning to start.")
                if not load_url(nav_page, start_url):
                    break

        browser.close()

    return found, logs


def _try_click(page, elements: list[dict], element_id: int) -> bool:
    """Attempts to click an element. Returns True if the page changed."""
    try:
        chosen     = elements[element_id]
        target_url = chosen.get("href") or ""
    except IndexError:
        return False

    # Reject dead-end links before even trying
    if is_dead_end(target_url):
        print("    ⏭  Dead-end link — retrying")
        return False

    try:
        url_before = page.url

        # Dismiss overlays right before clicking to clear any modals
        dismiss_overlays(page)

        if target_url and not target_url.startswith("javascript:"):
            page.goto(target_url, wait_until="domcontentloaded",
                      timeout=config.PAGE_TIMEOUT)
        else:
            page.click(f"text={chosen['text']}", timeout=5000)
            page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_TIMEOUT)

        page.wait_for_timeout(config.CLICK_WAIT)
        dismiss_overlays(page)

        if normalize_url(page.url) == normalize_url(url_before):
            print("    ⏭  Page didn't change — retrying")
            return False

        return True

    except Exception as e:
        print(f"    ✗ Click failed: {_short(str(e), 120)} — retrying")
        return False


def _make_log(step, url, clicks, candidates, verified, latency):
    return StepLog(
        step              = step,
        url               = url,
        clicks_from_start = clicks,
        nav_model         = active_model("nav"),
        link_model        = active_model("link"),
        verify_model      = active_model("verify"),
        candidates        = candidates,
        verified          = verified,
        latency_s         = latency,
    )


def _parse_decision(raw: str) -> int | str | None:
    raw = raw.strip()
    if "DONE" in raw.upper():
        return "DONE"
    numbers = re.findall(r"\b(\d+)\b", raw)
    return int(numbers[-1]) if numbers else None


def _short(url: str, max_len: int = 65) -> str:
    url = url.split("?")[0]
    return (url[:max_len] + "…") if len(url) > max_len else url
