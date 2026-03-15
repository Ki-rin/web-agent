"""
browser.py — Playwright setup, page loading, URL utilities, overlay dismissal.
"""

from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import config

# Query params that are purely tracking — strip for deduplication
_TRACKING_PARAMS = {
    "intc", "afc", "pid", "adobe_mc", "cmv", "rCode",
    "walletSegment", "ProspectID", "HKOP",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
}


def make_browser_and_context(playwright):
    """Launches Chromium with a persistent context."""
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
    """Loads url, dismisses overlays, returns success."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT)
        page.wait_for_timeout(config.PAGE_LOAD_WAIT)
        dismiss_overlays(page)
        return True
    except Exception as e:
        print(f"    ✗ Failed to load {url}: {e}")
        return False


def dismiss_overlays(page):
    """
    Dismisses modal overlays that block clicks.

    Many sites (Citi, Chase, etc.) show zipcode modals, cookie banners,
    or promo popups that intercept pointer events. This removes or hides
    the most common patterns so click() calls don't time out.
    """
    page.evaluate("""() => {
        // Strategy 1: Hide any visible modal overlays blocking pointer events
        for (const sel of [
            '#zipcode-modal',
            '.modal.fade.in',
            '.citi-modal',
            '[class*="overlay"]',
            '[class*="cookie"]',
            '[id*="cookie"]',
            '[class*="consent"]',
        ]) {
            document.querySelectorAll(sel).forEach(el => {
                if (el.offsetParent !== null || getComputedStyle(el).display !== 'none') {
                    el.style.display = 'none';
                }
            });
        }

        // Strategy 2: Click common dismiss buttons
        for (const sel of [
            'button[aria-label="Close"]',
            'button[aria-label="close"]',
            '.modal .close',
            '[data-dismiss="modal"]',
            'button.cookie-accept',
        ]) {
            const btn = document.querySelector(sel);
            if (btn && btn.offsetParent !== null) {
                try { btn.click(); } catch {}
            }
        }

        // Strategy 3: Remove backdrop/overlay divs that steal pointer events
        document.querySelectorAll('.modal-backdrop, .overlay-backdrop').forEach(el => {
            el.remove();
        });
    }""")


def normalize_url(url: str) -> str:
    """Strips fragment, trailing slash, and tracking query params."""
    p = urlparse(url)
    filtered_qs = {k: v for k, v in parse_qs(p.query).items()
                   if k not in _TRACKING_PARAMS}
    clean_query = urlencode(filtered_qs, doseq=True)
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", clean_query, ""))


def is_dead_end(url: str) -> bool:
    """Checks if a URL matches any dead-end pattern."""
    if not url:
        return False
    return any(p in url for p in config.DEAD_END_PATTERNS)



