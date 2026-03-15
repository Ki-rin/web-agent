# ══════════════════════════════════════════════════════════════════════════════
# config.py — all tuneable settings in one place
# ══════════════════════════════════════════════════════════════════════════════

# ── Crawl limits ──────────────────────────────────────────────────────────────
MAX_STEPS      = 8    # max navigation clicks per session
MAX_ELEMENTS   = 25   # max DOM elements sent to LLM (lower = faster + cheaper)
MAX_BRANCH     = 2    # verified pages to recurse into
MAX_DEPTH      = 1    # crawl depth  (0 = no recursion, 1 = one level deep)
TARGET_RESULTS = 5    # stop early once this many pages are verified

# ── Speed settings ────────────────────────────────────────────────────────────
PAGE_LOAD_WAIT  = 1500   # ms to wait after domcontentloaded (was 3000)
SCROLL_WAIT     = 500    # ms to wait after scroll (was 1000)
CLICK_WAIT      = 1000   # ms to wait after a nav click (was 2000)
VERIFY_WORKERS  = 4      # parallel threads for Groq verify calls
BODY_TEXT_LIMIT = 2000   # chars of body text sent to verify LLM (was 3000)

# ── Browser ───────────────────────────────────────────────────────────────────
HEADLESS       = False   # False bypasses most bot detection
PAGE_TIMEOUT   = 25000   # ms per page.goto call

# ── Per-role model chains ─────────────────────────────────────────────────────
#
# Each role has its OWN fallback list, tried independently.
#
#   NAV    — simple click decisions  → fast, NO built-in browser tools
#   LINK   — candidate link picking  → balanced reasoning
#   VERIFY — reads full page content → strongest models first
#
# NOTE: openai/gpt-oss-* models have built-in browser tools that fire
# automatically. Keep them OUT of NAV (causes tool_use_failed errors).
# They are fine for LINK and VERIFY.

NAV_MODELS = [
    "llama-3.1-8b-instant",                       # 560 t/s — primary (no tools)
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 750 t/s
    "llama-3.3-70b-versatile",                    # 280 t/s
    "qwen/qwen3-32b",                             # 400 t/s — last nav resort
]

LINK_MODELS = [
    "qwen/qwen3-32b",                             # 400 t/s — primary
    "llama-3.3-70b-versatile",                    # 280 t/s
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 750 t/s
    "openai/gpt-oss-20b",                         # 1000 t/s
    "llama-3.1-8b-instant",                       # last link resort
]

VERIFY_MODELS = [
    "openai/gpt-oss-120b",                        # 500 t/s — primary (best reasoning)
    "llama-3.3-70b-versatile",                    # 280 t/s
    "moonshotai/kimi-k2-instruct-0905",           # 200 t/s, 262k ctx
    "qwen/qwen3-32b",                             # 400 t/s
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 750 t/s
    "openai/gpt-oss-20b",                         # 1000 t/s
    "llama-3.1-8b-instant",                       # last verify resort
]

# ── Stop words stripped when extracting keywords from goal ────────────────────
STOP_WORDS = {
    "find", "page", "pages", "that", "with", "about", "for", "the", "a",
    "an", "and", "or", "to", "of", "in", "on", "any", "all", "which",
    "mention", "mentions", "mentioning", "include", "includes", "containing",
}
