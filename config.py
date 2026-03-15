# config.py — all tuneable settings in one place

# ── Crawl limits ──────────────────────────────────────────────────────────────
MAX_STEPS      = 8
MAX_ELEMENTS   = 40
MAX_BRANCH     = 2
MAX_DEPTH      = 1
TARGET_RESULTS = 5

# ── Speed ─────────────────────────────────────────────────────────────────────
PAGE_LOAD_WAIT      = 1500   # ms after domcontentloaded
SCROLL_WAIT         = 500    # ms after scroll
CLICK_WAIT          = 1000   # ms after a nav click
VERIFY_WORKERS      = 4      # parallel Groq verify calls
BODY_TEXT_LIMIT     = 2000   # chars of body text sent to verify LLM
MAX_VERIFY_PER_STEP = 5      # max candidates to browser-load per step

# ── Browser ───────────────────────────────────────────────────────────────────
HEADLESS     = False
PAGE_TIMEOUT = 25000     # ms per page.goto call

# ── Dead-end URL patterns (single source of truth) ───────────────────────────
DEAD_END_PATTERNS = [
    "pageNotFound", "/404", "/error",
    "/ag/cards/application",
    "/ag/cards/displayterms",
    "online.citi.com",
]

# ── Click retry ───────────────────────────────────────────────────────────────
MAX_CLICK_RETRIES = 5

# ── Per-role model chains ─────────────────────────────────────────────────────
#
#   NAV    — simple click decisions  → fast, NO built-in browser tools
#   LINK   — candidate link picking  → balanced reasoning
#   VERIFY — reads full page content → strongest models first
#
# NOTE: openai/gpt-oss-* fire browser tools automatically.
# Keep them OUT of NAV (causes tool_use_failed errors).

NAV_MODELS = [
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
]

LINK_MODELS = [
    "qwen/qwen3-32b",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.1-8b-instant",
]

VERIFY_MODELS = [
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.1-8b-instant",
]

