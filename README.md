# 🕷️ Web Agent — Groq + Playwright

Navigates websites like a human and returns **verified** pages that actually match your goal — not just guesses from link text.

## Quickstart

```bash
git clone https://github.com/your-username/web-agent.git
cd web-agent
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # paste your Groq API key
python main.py
```

Get a free key at: https://console.groq.com/keys

---

## Usage

Edit `main.py`:

```python
run(
    start_url="https://www.citi.com/credit-cards/compare/view-all-credit-cards",
    goal="Find credit card pages that mention bonus miles",
)
```

```bash
python main.py
```

### Example output

```
  ✅  3 verified result(s) found

  1. Citi AAdvantage® Platinum Select® Card
     URL    : https://www.citi.com/credit-cards/citi-aadvantage-platinum-select...
     Proof  : "Earn 50,000 bonus miles after spending $2,500 in the first 3 months"
     Model  : openai/gpt-oss-120b

  2. Citi® / AAdvantage® Gold World Elite Mastercard®
     URL    : https://www.citi.com/credit-cards/citi-aadvantage-gold...
     Proof  : "Earn bonus miles on every American Airlines purchase"
     Model  : openai/gpt-oss-120b
```

---

## How it works

For each page the agent visits:

1. **Extract** visible links and buttons from the live DOM
2. **Filter** by goal keywords (fast, no LLM call)
3. **LINK model** picks candidate URLs from filtered links
4. **Open** each candidate in the browser and read its content
5. **VERIFY model** confirms the page actually satisfies the goal (parallel Groq calls)
6. **NAV model** decides what to click next
7. Repeat up to `MAX_STEPS`, then optionally recurse into verified pages

Every result includes a snippet proving *why* it matched — no false positives.

---

## Project structure

```
web-agent/
├── main.py            ← run your goal here
├── config.py          ← all settings
├── requirements.txt
└── agent/
    ├── models.py      ← FoundPage dataclass
    ├── groq_client.py ← API calls, per-role fallback chains, cache
    ├── browser.py     ← Playwright setup and page loading
    ├── extractor.py   ← DOM extraction, signals, keyword filter
    ← llm_tasks.py    ← nav / link / verify LLM functions
    ├── verifier.py    ← sequential browser load + parallel Groq verify
    ├── navigator.py   ← step-by-step navigation loop
    └── crawler.py     ← recursive crawl + run() public API
```

---

## Three-model pipeline

Each task uses the right-sized model. Each role has its own fallback chain — a rate limit on VERIFY doesn't affect NAV or LINK.

| Role | Primary model | Purpose |
|---|---|---|
| **NAV** | `llama-3.1-8b-instant` | Which element to click next |
| **LINK** | `qwen/qwen3-32b` | Which links look relevant |
| **VERIFY** | `openai/gpt-oss-120b` | Does this page actually satisfy the goal |

On rate limit or decommission, each role automatically falls back through its own chain. All fallbacks are configured in `config.py`.

---

## Configuration (`config.py`)

| Setting | Default | Description |
|---|---|---|
| `MAX_STEPS` | `8` | Max clicks per session |
| `MAX_DEPTH` | `1` | Recursion depth (0 = no recursion) |
| `TARGET_RESULTS` | `5` | Stop after N verified results |
| `PAGE_LOAD_WAIT` | `1500ms` | Wait after page load |
| `VERIFY_WORKERS` | `4` | Parallel Groq threads for verification |
| `HEADLESS` | `False` | Visible browser — bypasses most bot detection |

## Requirements

- Python 3.10+
- Free [Groq API key](https://console.groq.com/keys)
