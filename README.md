# 🕷️ Web Agent — Groq + Playwright

Navigates websites like a human and returns only **verified** pages that match your goal — with proof.

## Quickstart

```bash
git clone https://github.com/your-username/web-agent.git
cd web-agent
pip install -r requirements.txt
playwright install chromium
cp .env.example .env    # add your Groq API key
python main.py
```

Free API key: https://console.groq.com/keys

---

## Usage

Edit the bottom of `main.py`:

```python
run(
    start_url="https://www.citi.com/credit-cards/compare/view-all-credit-cards",
    goal="Find credit card pages that mention bonus miles",
)
```

---

## How it works

Each step, the agent:

1. Extracts visible links and buttons from the DOM
2. Filters by goal keywords — no LLM, fast
3. **LINK model** picks candidate URLs
4. Opens each candidate in the browser and reads the page
5. **VERIFY model** confirms the page actually satisfies the goal (parallel)
6. **NAV model** decides what to click next
7. Repeats until `TARGET_RESULTS` found or `MAX_STEPS` reached

Every result includes a snippet proving why it matched.

---

## Project structure

```
web-agent/
├── main.py            ← run your goal here
├── config.py          ← all settings (including dead-end patterns)
└── agent/
    ├── models.py      ← FoundPage and StepLog dataclasses
    ├── groq_client.py ← Groq API: per-role fallback chains + cache
    ├── browser.py     ← Playwright setup, overlay dismissal, URL utils
    ├── extractor.py   ← DOM extraction, page signals, keyword filter
    ├── llm_tasks.py   ← nav / link / verify LLM prompts
    ├── verifier.py    ← load pages + verify in parallel
    ├── navigator.py   ← step-by-step navigation loop
    └── crawler.py     ← recursive crawl + run() + final report
```

---

## Three-model pipeline

Each role uses the right model and fails over independently.

| Role | Primary model | What it does |
|---|---|---|
| **NAV** | `llama-3.1-8b-instant` | Decides what to click next |
| **LINK** | `qwen/qwen3-32b` | Picks candidate URLs from a page |
| **VERIFY** | `openai/gpt-oss-120b` | Reads page content and confirms goal match |

If any model hits a rate limit or is decommissioned, it automatically falls back to the next in its chain without affecting the other roles. All chains are in `config.py`.

---

## Configuration

All settings are in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `MAX_STEPS` | `8` | Max clicks per session |
| `MAX_DEPTH` | `1` | Recursion into verified pages (0 = none) |
| `TARGET_RESULTS` | `5` | Stop after this many verified results |
| `PAGE_LOAD_WAIT` | `1500ms` | Wait after page load |
| `VERIFY_WORKERS` | `4` | Parallel threads for verification |
| `HEADLESS` | `False` | Visible browser bypasses most bot detection |
