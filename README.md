# 🕷️ Web Agent — Groq + Playwright

A modular web navigation agent that browses like a human and returns only **verified** pages matching your goal.

## Project structure

```
web-agent/
├── main.py            ← edit your goal/URL here and run
├── config.py          ← all settings: models, timeouts, limits
├── requirements.txt
├── .env.example
└── agent/
    ├── models.py      ← FoundPage dataclass
    ├── groq_client.py ← Groq API, per-role fallback, cache, <think> stripping
    ├── browser.py     ← Playwright setup, load_url, normalize_url
    ├── extractor.py   ← DOM extraction, page signals, keyword filter
    ├── llm_tasks.py   ← one LLM function per role (nav / link / verify)
    ├── verifier.py    ← two-phase verification (browser sequential + Groq parallel)
    ├── navigator.py   ← step-based navigation loop
    └── crawler.py     ← recursive crawl + run() public API
```

## How it works

```
main.py: run(start_url, goal)
   ↓
crawler.py: crawl()
   ↓
navigator.py: navigate()  ← repeats up to MAX_STEPS
   │
   ├─ extractor.py: extract_elements()      DOM: a/button/[role=button]
   ├─ extractor.py: heuristic_filter()      keyword match — no LLM, fast
   ├─ llm_tasks.py: llm_candidate_links()   LINK model picks candidates
   ├─ verifier.py:  verify_candidates()     Phase 1: browser loads pages (sequential)
   │                                        Phase 2: Groq verifies in parallel
   └─ llm_tasks.py: llm_next_click()        NAV model decides next click
```

## Three-model pipeline

| Role | Model | Why |
|---|---|---|
| **NAV** | `llama-3.1-8b-instant` | Fast, no built-in browser tools |
| **LINK** | `qwen/qwen3-32b` | Strong pattern matching |
| **VERIFY** | `openai/gpt-oss-120b` | Best reasoning, reads full page |

Each role has its own fallback chain — rate limits on VERIFY don't affect NAV or LINK.


## Quickstart

```bash
git clone https://github.com/your-username/web-agent.git
cd web-agent
pip install -r requirements.txt
playwright install chromium
cp .env.example .env    # add your Groq API key
python main.py
```

Get a free Groq API key at: https://console.groq.com/keys

## Configuration (`config.py`)

| Setting | Default | Description |
|---|---|---|
| `MAX_STEPS` | `8` | Max clicks per session |
| `MAX_DEPTH` | `1` | Crawl depth (0 = no recursion) |
| `TARGET_RESULTS` | `5` | Stop after N verified results |
| `PAGE_LOAD_WAIT` | `1500ms` | Wait after page load |
| `VERIFY_WORKERS` | `4` | Parallel Groq threads |
| `HEADLESS` | `False` | False bypasses bot detection |

## Requirements

- Python 3.10+
- Free [Groq API key](https://console.groq.com/keys)
