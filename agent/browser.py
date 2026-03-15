"""
Browser helpers — Playwright setup and page loading.

One browser + one persistent context is reused across all navigation
steps so cookies are shared and pages load faster.
"""

import config


def make_browser_and_context(playwright):
    """
    Launches a Chromium browser with a persistent context.
    headless=False bypasses most bot detection (Citi, etc.).
    """
    browser = playwright.chromium.launch(headless=config.HEADLESS)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    context.set_default_timeout(config.PAGE_TIMEOUT)
    return browser, context


def load_url(page, url: str) -> bool:
    """
    Navigates to url using domcontentloaded.

    Why not networkidle: sites like Citi keep making background requests
    forever, so networkidle never fires and the agent hangs.
    PAGE_LOAD_WAIT gives JS time to render without waiting for all network
    activity to stop.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT)
        page.wait_for_timeout(config.PAGE_LOAD_WAIT)
        return True
    except Exception as e:
        print(f"    Failed to load {url}: {e}")
        return False


def normalize_url(url: str) -> str:
    """Strips fragments and trailing slashes to prevent revisiting same page."""
    return url.split("#")[0].rstrip("/")
